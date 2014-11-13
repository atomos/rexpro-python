import json
import re
import struct
import warnings
from uuid import uuid1

import msgpack

from rexpro import exceptions
from rexpro._compat import string_types, integer_types, float_types, array_types, iteritems


def int_to_32bit_array(val):
    """Converts an integer to 32 bit bytearray

    :param val: the value to convert to bytes
    :type val: int
    :rtype: bytearray
    """
    value = val
    bytes = bytearray()
    for i in range(4):
        bytes.insert(0, (value & 0xff))
        value >>= 8
    return str(bytes)


def int_from_32bit_array(val):
    """Converts an integer from a 32 bit bytearray

    :param val: the value to convert to an int
    :type val: int

    :rtype: int
    """
    rval = 0
    for fragment in bytearray(val):
        rval <<= 8
        rval |= fragment
    return rval


def bytearray_to_text(data):
    if data is None:
        return None
    if isinstance(data, array_types) and not isinstance(data, bytearray):
        return [bytearray_to_text(obj) for obj in data]
    elif isinstance(data, dict):
        response = {}
        for key, value in iteritems(data):
            response[bytearray_to_text(key)] = bytearray_to_text(value)
        return response
    elif isinstance(data, integer_types + float_types + string_types):
        return data
    elif isinstance(data, (bytes, bytearray)):
        return data.decode('UTF-8')
    elif isinstance(data, string_types):
        return data
    elif isinstance(data, (bytes, bytearray)):
        return data.decode('UTF-8')
    elif data is None:
        return None
    else:  # all else fails
        warnings.warn("Defaulting no known way to handle {}: {}".format(type(data), data), stacklevel=2)
        return data


class MessageTypes(object):
    """
    Enumeration of RexPro send message types
    """
    ERROR = 0
    SESSION_REQUEST = 1
    SESSION_RESPONSE = 2
    SCRIPT_REQUEST = 3
    SCRIPT_RESPONSE = 5


class RexProMessage(object):
    """ Base class for rexpro message types """

    MESSAGE_TYPE = None

    def get_meta(self):
        """
        Returns a dictionary of message meta data depending on other set values
        """
        return {}

    def get_message_list(self):
        """
        Creates and returns the list containing the data to be serialized into a message
        """
        return [
            # session
            self.session,

            # unique request id
            uuid1().bytes,

            # meta
            self.get_meta()
        ]

    def serialize(self):
        """
        Serializes this message to send to rexster

        The format as far as I can tell is this:

        +--------------+----------------------------+
        | type (bytes) | description                |
        +==============+============================+
        | byte(1)      | Message type               |
        +--------------+----------------------------+
        | byte(4)      | Message Length             |
        +--------------+----------------------------+
        | byte(n)      | msgpack serialized message |
        +--------------+----------------------------+

        the actual message is just a list of values, all seem to start with version, session, and a unique request id
        the session and unique request id are uuid bytes, and the version and are each 1 byte unsigned integers
        """
        # msgpack list
        msg = self.get_message_list()
        bytes = msgpack.dumps(msg)

        # add protocol version
        message = bytearray([1])

        # add serializer type
        message += bytearray([0])

        # add padding
        message += bytearray([0, 0, 0, 0])

        # add message type
        message += bytearray([self.MESSAGE_TYPE])

        # add message length
        message += struct.pack('!I', len(bytes))

        # add message
        message += bytes

        return message

    @classmethod
    def deserialize(cls, data):  # pragma: no cover
        """
        Constructs a message instance from the given data

        :param data: the raw data, minus the type and size info, from rexster
        :type data: str/bytearray

        :rtype: RexProMessage
        """
        # redefine in subclasses
        raise NotImplementedError

    @staticmethod
    def interpret_response(response):
        """
        interprets the response from rexster, returning the relevant response message object
        """


class ErrorResponse(RexProMessage):

    # meta flags
    INVALID_MESSAGE_ERROR = 0
    INVALID_SESSION_ERROR = 1
    SCRIPT_FAILURE_ERROR = 2
    AUTH_FAILURE_ERROR = 3
    GRAPH_CONFIG_ERROR = 4
    CHANNEL_CONFIG_ERROR = 5
    RESULT_SERIALIZATION_ERROR = 6

    def __init__(self, meta, message, data=None, **kwargs):
        super(ErrorResponse, self).__init__(**kwargs)
        self.meta = meta
        self.meta_orig = meta
        if isinstance(self.meta, dict):
            self.meta = self.meta['flag']
        self.message = message
        self.data = data

    @classmethod
    def deserialize(cls, data):
        message = msgpack.loads(data)
        session, request, meta, msg = message
        return cls(message=bytearray_to_text(msg), meta=bytearray_to_text(meta), data=data)

    def raise_exception(self):
        if self.meta == self.INVALID_MESSAGE_ERROR:
            raise exceptions.RexProInvalidMessageException(self.message)
        elif self.meta == self.INVALID_SESSION_ERROR:
            raise exceptions.RexProInvalidSessionException(self.message)
        elif self.meta == self.SCRIPT_FAILURE_ERROR:
            raise exceptions.RexProScriptException(self.message)
        elif self.meta == self.AUTH_FAILURE_ERROR:
            raise exceptions.RexProAuthenticationFailure(self.message)
        elif self.meta == self.GRAPH_CONFIG_ERROR:
            raise exceptions.RexProGraphConfigException(self.message)
        elif self.meta == self.CHANNEL_CONFIG_ERROR:
            raise exceptions.RexProChannelConfigException(self.message)
        elif self.meta == self.RESULT_SERIALIZATION_ERROR:
            raise exceptions.RexProSerializationException("Meta: {} ({}), Message: {}, Raw Data: {}".format(
                self.meta, type(self.meta), self.message, repr(self.data))
            )
        else:
            raise exceptions.RexProScriptException("Meta: {} ({}), Message: {}, Raw Data: {}".format(
                self.meta, type(self.meta), self.message, repr(self.data))
            )


class SessionRequest(RexProMessage):
    """
    Message for creating a session with rexster
    """

    MESSAGE_TYPE = MessageTypes.SESSION_REQUEST

    def __init__(self, graph_name=None, graph_obj_name=None, username='', password='', session_key=None,
                 kill_session=False, *args, **kwargs):
        """
        :param graph_name: the name of the rexster graph to connect to
        :type graph_name: str
        :param graph_obj_name: the name of the variable to bind the graph object to (defaults to 'g')
        :type graph_obj_name: str
        :param username: the username to use for authentication (optional)
        :type username: str
        :param password: the password to use for authentication (optional)
        :type password: str
        :param session_key: the session key to reference (used only for killing existing session)
        :type session_key: str
        :param kill_session: sets this request to kill the server session referenced by the session key parameter, defaults to False
        :type kill_session: bool
        """
        super(SessionRequest, self).__init__(*args, **kwargs)
        self.username = username
        self.password = password
        self.session = session_key
        self.graph_name = graph_name
        self.graph_obj_name = graph_obj_name
        self.kill_session = kill_session

    def get_meta(self):
        if self.kill_session:
            return {'killSession': True}

        meta = super(SessionRequest, self).get_meta()

        if self.graph_name:
            meta['graphName'] = self.graph_name
            if self.graph_obj_name:
                meta['graphObjName'] = self.graph_obj_name

        return meta

    def get_message_list(self):
        """ Constructs a Session Request Message List

        +-----------+-----------+------------------------------------------------------------------------------------+
        | field     | type      | description                                                                        |
        +===========+===========+====================================================================================+
        | Session   | byte (16) | The UUID for the Session. Set each byte to zero for an "empty" session.            |
        +-----------+-----------+------------------------------------------------------------------------------------+
        | Request   | byte (16) | The UUID for the request. Uniquely identifies the request from the client.         |
        |           |           | Get's passed back and forth so the response can be mapped to a request.            |
        +-----------+-----------+------------------------------------------------------------------------------------+
        | Meta      | Map       | Message specific properties described below                                        |
        +-----------+-----------+------------------------------------------------------------------------------------+
        | Username  | String    | The username to access the RexPro Server assuming auth is turned on. Ignored if no |
        |           |           | auth.                                                                              |
        +-----------+-----------+------------------------------------------------------------------------------------+
        | Password  | String    | The password to access the RexPro Server assuming auth is turned on. Ignored if no |
        |           |           | auth.                                                                              |
        +-----------+-----------+------------------------------------------------------------------------------------+


        Meta Attributes:

        +--------------+--------+---------------------------------------------------------------------------------+
        | field        | type   | description                                                                     |
        +==============+========+=================================================================================+
        | graphName    | String | The name of the graph to open a session on. Optional                            |
        +--------------+--------+---------------------------------------------------------------------------------+
        | graphObjName | String | The variable name of the Graph object, defaults to `g`. Optional                |
        +--------------+--------+---------------------------------------------------------------------------------+
        | killSession  | Bool   | If true, the given session will be destroyed, else one will be created, default |
        +--------------+--------+---------------------------------------------------------------------------------+
        |              |        | False                                                                           |
        +--------------+--------+---------------------------------------------------------------------------------+
        """

        message_list = super(SessionRequest, self).get_message_list() + [
            self.username,
            self.password
        ]
        if not self.session:
            message_list[0] = '\x00'*16
        return message_list


class SessionResponse(RexProMessage):

    def __init__(self, session_key, meta, languages, **kwargs):
        """
        """
        super(SessionResponse, self).__init__(**kwargs)
        self.session_key = session_key
        self.meta = meta
        self.languages = languages

    @classmethod
    def deserialize(cls, data):
        message = msgpack.loads(data)
        session, request, meta, languages = message
        return cls(
            session_key=session,
            meta=bytearray_to_text(meta),
            languages=languages
        )


class ScriptRequest(RexProMessage):
    """
    Message that executes a gremlin script and returns the response
    """

    class Language(object):
        GROOVY = 'groovy'
        SCALA = 'scala'
        JAVA = 'java'

    MESSAGE_TYPE = MessageTypes.SCRIPT_REQUEST

    def __init__(self, script, params=None, session_key=None, graph_name=None, graph_obj_name=None, in_session=True,
                 isolate=True, in_transaction=True, language=Language.GROOVY, **kwargs):
        """
        :param script: script to execute
        :type script: str/unicode
        :param params: parameter values to bind to request
        :type params: dict (json serializable)
        :param session_key: the session key to execute the script with
        :type session_key: str
        :param graph_name: the name of the rexster graph to connect to
        :type graph_name: str
        :param graph_obj_name: the name of the variable to bind the graph object to (defaults to 'g')
        :type graph_obj_name: str
        :param in_session: indicates this message should be executed in the context of the included session
        :type in_session:bool
        :param isolate: indicates variables defined in this message should not be available to subsequent message
        :type isolate:bool
        :param in_transaction: indicates this message should be wrapped in a transaction
        :type in_transaction:bool
        :param language: the language used by the script (only groovy has been tested)
        :type language: ScriptRequest.Language
        """
        super(ScriptRequest, self).__init__(**kwargs)
        self.script = script
        self.params = params or {}
        self.session = session_key
        self.graph_name = graph_name
        self.graph_obj_name = graph_obj_name
        self.in_session = in_session
        self.isolate = isolate
        self.in_transaction = in_transaction
        self.language = language

    def get_meta(self):
        meta = {}

        if self.graph_name:
            meta['graphName'] = self.graph_name
            if self.graph_obj_name:
                meta['graphObjName'] = self.graph_obj_name

        # defaults to False
        if self.in_session:
            meta['inSession'] = True

        # defaults to True
        if not self.isolate:
            meta['isolate'] = False

        # defaults to True
        if not self.in_transaction:
            meta['transaction'] = False

        return meta

    def _validate_params(self):
        """
        Checks that the parameters are ok
        (no invalid types, no weird key names)
        """
        for k, v in self.params.items():

            if re.findall(r'^[0-9]', k):
                raise exceptions.RexProScriptException(
                    "parameter names can't begin with a number")
            if re.findall(r'[\s\.]', k):
                raise exceptions.RexProException(
                    "parameter names can't contain {}".format(
                        re.findall(r'^[0-9]', k)[0]
                    )
                )

            if not isinstance(v, string_types + integer_types + float_types + array_types):
                raise exceptions.RexProScriptException(
                    "{} is an unsupported type".format(type(v))
                )

    def serialize_parameters(self):
        """
        returns a serialization of the supplied parameters
        """
        data = bytearray()
        for k, v in self.params.items():
            key = k.encode('utf-8')
            val = json.dumps(v).encode('utf-8')
            data += int_to_32bit_array(len(key))
            data += key
            data += int_to_32bit_array(len(val))
            data += val
        return str(data)

    def get_message_list(self):
        return super(ScriptRequest, self).get_message_list() + [
            self.language,
            self.script.encode('utf-8'),
            self.params
        ]


class MsgPackScriptResponse(RexProMessage):

    def __init__(self, results, bindings, **kwargs):
        super(MsgPackScriptResponse, self).__init__(**kwargs)
        self.results = results
        self.bindings = bindings

    @classmethod
    def deserialize(cls, data):
        message = msgpack.loads(data)
        session, request, meta, results, bindings = message

        return cls(
            results=bytearray_to_text(results),
            bindings=bytearray_to_text(bindings)
        )
