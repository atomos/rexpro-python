from nose.plugins.attrib import attr
from rexpro.messages import ScriptRequest, MsgPackScriptResponse, ErrorResponse, SessionRequest, SessionResponse
from rexpro.tests.base import BaseRexProTestCase, multi_graph
from rexpro._compat import string_types


@attr('unit')
class TestRexProScriptRequestMessage(BaseRexProTestCase):

    @multi_graph
    def test_non_transactional_sessionless_message(self):
        conn = self.get_socket()
        out_msg = ScriptRequest(
            """
            v = g.addVertex([xyz:5,test:'test'])
            v
            """,
            in_session=False,
            graph_name=self.graphname,
            in_transaction=False
        )
        conn.send_message(out_msg)
        response = conn.get_response()

        self.assertNotErrorResponse(response)
        self.assertIsInstance(response, MsgPackScriptResponse)
        self.assertIsInstance(response.results, dict)
        self.assertIn('_properties', response.results)
        self.assertIn('xyz', response.results['_properties'])
        self.assertEqual(response.results['_properties']['xyz'], 5)
        self.assertIn('test', response.results['_properties'])
        self.assertEqual(response.results['_properties']['test'], 'test')
        self.assertIsInstance(response.results['_properties']['test'], string_types)

    @multi_graph
    def test_sessionless_message(self):
        conn = self.get_socket()
        out_msg = ScriptRequest(
            """
            v = g.addVertex([xyz:5])
            v
            """,
            in_session=False,
            graph_name=self.graphname
        )
        conn.send_message(out_msg)
        response = conn.get_response()

        self.assertNotErrorResponse(response)
        self.assertIsInstance(response, MsgPackScriptResponse)
        self.assertIsInstance(response.results, dict)
        self.assertIn('_properties', response.results)
        self.assertIn('xyz', response.results['_properties'])
        self.assertEqual(response.results['_properties']['xyz'], 5)

    def test_query_value_isolation(self):
        conn = self.get_socket()

        session_msg = SessionRequest(username=self.username, password=self.password)
        conn.send_message(session_msg)
        response = conn.get_response()
        self.assertIsInstance(response, SessionResponse)
        session_key = response.session_key

        out_msg = ScriptRequest(
            """
            x = 5
            x
            """,
            session_key=session_key
        )
        conn.send_message(out_msg)
        response = conn.get_response()

        self.assertNotErrorResponse(response)
        self.assertIsInstance(response, MsgPackScriptResponse)
        self.assertEqual(response.results, 5)

        out_msg = ScriptRequest(
            """
            y = 5 + x
            y
            """,
            session_key=session_key
        )
        conn.send_message(out_msg)
        response = conn.get_response()

        self.assertErrorResponse(response)

    def test_disabled_query_isolation(self):
        conn = self.get_socket()

        session_msg = SessionRequest(username=self.username, password=self.password)
        conn.send_message(session_msg)
        response = conn.get_response()
        self.assertIsInstance(response, SessionResponse)
        session_key = response.session_key

        out_msg = ScriptRequest(
            """
            x = 5
            x
            """,
            isolate=False,
            session_key=session_key
        )
        conn.send_message(out_msg)
        response = conn.get_response()

        self.assertNotErrorResponse(response)
        self.assertIsInstance(response, MsgPackScriptResponse)
        self.assertEqual(response.results, 5)

        out_msg = ScriptRequest(
            """
            y = 5 + x
            y
            """,
            session_key=session_key
        )
        conn.send_message(out_msg)
        response = conn.get_response()

        self.assertNotErrorResponse(response)
        self.assertIsInstance(response, MsgPackScriptResponse)
        self.assertEqual(response.results, 10)

    @multi_graph
    def test_graph_definition(self):
        conn = self.get_socket()
        out_msg = ScriptRequest(
            """
            g.getFeatures().toMap()
            """,
            isolate=False,
            in_transaction=False,
            graph_name=self.graphname,
            in_session=False
        )
        conn.send_message(out_msg)
        response = conn.get_response()

        self.assertNotErrorResponse(response)
        self.assertIsInstance(response, MsgPackScriptResponse)
        self.assertIsInstance(response.results, dict)

    def test_omitting_session_key_in_sessioned_message_returns_proper_error(self):
        conn = self.get_socket()
        out_msg = ScriptRequest(
            """
            g.getFeatures().toMap()
            """,
        )
        conn.send_message(out_msg)
        response = conn.get_response()

        self.assertErrorResponse(response)
        self.assertEqual(response.meta_orig.get('flag'), ErrorResponse.SCRIPT_FAILURE_ERROR)
        self.assertEqual(response.meta, ErrorResponse.SCRIPT_FAILURE_ERROR)

    def test_object_persistence_within_transactions(self):
        """ Tests that objects defined in one request are available in the next, within an open transaction """
        pass

    @attr('test_double')
    def test_full_double(self):
        conn = self.get_connection()

        script = "try { g.makeKey('testdouble').dataType(FullDouble.class).make() } catch (err) { }; v = g.addVertex(); v.testdouble = value; g.commit(); return v"

        response = conn.execute(script, {'value': 1.2345678901234567890})

        self.assertEqual(response['_properties']['testdouble'], 1.2345678901234567890)