import random
from contextlib import contextmanager
from socket import SHUT_RDWR

from rexpro import exceptions, messages
from rexpro.exceptions import RexProConnectionException
from rexpro.messages import ErrorResponse


class RexProBaseConnectionPool(object):
    """ Base RexProConnectionPool Framework

    Start from here if you want to build additional support or modify the core structure
    """

    QUEUE_CLASS = None
    CONN_CLASS = None

    def __init__(self, host, port, graph_name, graph_obj_name='g', username='', password='', timeout=None):
        """
        Connection constructor

        :param host: the server to connect to
        :type host: str (ip address)
        :param port: the server port to connect to
        :type port: int
        :param graph_name: the graph to connect to
        :type graph_name: str
        :param graph_obj_name: The graph object to use
        :type graph_obj_name: str
        :param username: the username to use for authentication (optional)
        :type username: str
        :param password: the password to use for authentication (optional)
        :type password: str
        """

        self.host = host
        self.port = port
        self.graph_name = graph_name
        self.graph_obj_name = graph_obj_name
        self.username = username
        self.password = password
        self.timeout = timeout

        self.pool = self.QUEUE_CLASS()

    def get(self, *args, **kwargs):
        """ Retrieve a rexpro connection from the pool

        :param host: the rexpro server to connect to
        :type host: str (ip address)
        :param port: the rexpro server port to connect to
        :type port: int
        :param graph_name: the graph to connect to
        :type graph_name: str
        :param graph_obj_name: The graph object to use
        :type graph_obj_name: str
        :param username: the username to use for authentication (optional)
        :type username: str
        :param password: the password to use for authentication (optional)
        :type password: str
        :rtype: RexProConnection
        """
        pool = self.pool
        if pool.qsize():
            return pool.get()
        else:
            try:
                new_item = self._create_connection(*args, **kwargs)
            except:
                raise
            return new_item

    def put(self, conn):
        """ Restore a connection to the pool

        :param conn: A rexpro connection to restore to the pool
        :type conn: RexProSyncConnection | RexProGeventConnection | RexProEventletConnection | RexProConnection
        """
        self.pool.put(conn)

    def close_all(self):
        """ Close all pool connections for a clean shutdown """
        while not self.pool.empty():
            conn = self.pool.get_nowait()
            try:
                conn.close()
            except Exception:
                pass

    @contextmanager
    def connection(self, *args, **kwargs):
        """ Context manager that conveniently grabs a connection from the pool and provides it with the context
        cleanly closes up the connection and restores it to the pool afterwards

        :param host: the rexpro server to connect to
        :type host: str (ip address)
        :param port: the rexpro server port to connect to
        :type port: int
        :param graph_name: the graph to connect to
        :type graph_name: str
        :param graph_obj_name: The graph object to use
        :type graph_obj_name: str
        :param username: the username to use for authentication (optional)
        :type username: str
        :param password: the password to use for authentication (optional)
        :type password: str
        """
        conn = self.create_connection(*args, **kwargs)
        if not conn:
            raise RexProConnectionException("Cannot commit because connection was closed: %r" % (conn, ))

        try:
            with conn.transaction():
                yield conn
        finally:
            self.close_connection(conn, soft=True)

    def _create_connection(self, host=None, port=None, graph_name=None, graph_obj_name=None, username=None,
                           password=None, timeout=None):
        """ Create a RexProSyncConnection using the provided parameters, defaults to Pool defaults

        :param host: the rexpro server to connect to
        :type host: str (ip address)
        :param port: the rexpro server port to connect to
        :type port: int
        :param graph_name: the graph to connect to
        :type graph_name: str
        :param graph_obj_name: The graph object to use
        :type graph_obj_name: str
        :param username: the username to use for authentication (optional)
        :type username: str
        :param password: the password to use for authentication (optional)
        :type password: str
        :rtype: RexProConnection
        """
        return self.CONN_CLASS(host=host or self.host,
                               port=port or self.port,
                               graph_name=graph_name or self.graph_name,
                               graph_obj_name=graph_obj_name or self.graph_obj_name,
                               username=username or self.username,
                               password=password or self.password,
                               timeout=timeout or self.timeout)

    def create_connection(self, *args, **kwargs):
        """ Get a connection from the pool if available, otherwise return a new connection if the pool isn't full

        :param host: the rexpro server to connect to
        :type host: str (ip address)
        :param port: the rexpro server port to connect to
        :type port: int
        :param graph_name: the graph to connect to
        :type graph_name: str
        :param graph_obj_name: The graph object to use
        :type graph_obj_name: str
        :param username: the username to use for authentication (optional)
        :type username: str
        :param password: the password to use for authentication (optional)
        :type password: str
        :rtype: RexProConnection
        """
        conn = self.get(*args, **kwargs)
        conn.open(soft=conn._opened)  # if opened, soft open, else hard open
        return conn

    def close_connection(self, conn, soft=False):
        """ Close a connection and restore it to the pool

        :param conn: a rexpro connection that was pull from the Pool
        :type conn: RexProConnection
        :param soft: define whether to soft-close the connection or hard-close the socket
        :type soft: bool
        """
        if conn._opened:
            conn.close(soft=soft)
        self.put(conn)


class RexProBaseConnection(object):
    """ Base RexProConnection Framework

    Start from here if you want to build additional support or modify the core structure
    """

    SOCKET_CLASS = None

    def __init__(self, host, port, graph_name, graph_obj_name='g', username='', password='', timeout=None):
        """
        Connection constructor

        :param host: the rexpro server to connect to
        :type host: str (ip address)
        :param port: the rexpro server port to connect to
        :type port: int
        :param graph_name: the graph to connect to
        :type graph_name: str
        :param graph_obj_name: The graph object to use
        :type graph_obj_name: str
        :param username: the username to use for authentication (optional)
        :type username: str
        :param password: the password to use for authentication (optional)
        :type password: str
        """
        self.host = host
        self.port = port
        self.graph_name = graph_name
        self.graph_obj_name = graph_obj_name
        self.username = username
        self.password = password
        self.timeout = timeout

        self._conn = None
        self._in_transaction = False
        self._session_key = None
        self._opened = False

        self.open()

    def _select(self, rlist, wlist, xlist, timeout=None):
        raise NotImplementedError

    def _open_session(self):
        """ Creates a session with rexster and creates the graph object """
        self._conn.send_message(
            messages.SessionRequest(
                username=self.username,
                password=self.password,
                graph_name=self.graph_name
            )
        )
        response = self._conn.get_response()
        if isinstance(response, ErrorResponse):
            response.raise_exception()
        self._session_key = response.session_key

    def open_transaction(self):
        """ opens a transaction """
        if self._in_transaction:
            raise exceptions.RexProScriptException("transaction is already open")
        self.execute(
            script='g.stopTransaction(FAILURE)',
            isolate=False,
            transaction=False,
        )
        self._in_transaction = True

    def close_transaction(self, success=True):
        """
        closes an open transaction

        :param success: indicates which status to close the transaction with, True will commit the changes,
                         False will roll them back
        :type success: bool
        """
        if not self._in_transaction:
            raise exceptions.RexProScriptException("transaction is not open")
        self.execute(
            script='g.stopTransaction({})'.format('SUCCESS' if success else 'FAILURE'),
            isolate=False,
            transaction=False
        )
        self._in_transaction = False

    def close(self, soft=False):
        """ Close a connection

        :param soft: Softly close the connection - do not actually close the socket (default: False)
        :type soft: bool
        """
        self._conn.send_message(
            messages.SessionRequest(
                session_key=self._session_key,
                graph_name=self.graph_name,
                kill_session=True
            )
        )
        response = self._conn.get_response()
        if not soft:
            self._opened = False
        self._session_key = None
        self._in_transaction = False
        if isinstance(response, ErrorResponse):
            response.raise_exception()

    def open(self, soft=False):
        """ open the connection to the database

        :param soft: Attempt to re-use the connection, if False (default), create a new socket
        :type soft: bool
        """
        if not soft:
            # connect to server
            self._conn = self.SOCKET_CLASS()
            self._conn.settimeout(self.timeout)

            if isinstance(self.host, list):
                host = random.choice(self.host)
            else:
                host = self.host

            if isinstance(self.port, list):
                port = random.choice(self.port)
            else:
                port = self.port

            try:
                self._conn.connect((host, port))
            except Exception as e:
                raise RexProConnectionException("Could not connect to database: %s" % e)

        # indicates that we're in a transaction
        self._in_transaction = False

        # stores the session key
        self._session_key = None
        self._opened = True
        self._open_session()

    def test_connection(self):
        """ Test the socket, if it's errored or closed out, try to reconnect. Otherwise raise and Exception """
        readable, writeable, in_error = self._select([self._conn], [self._conn], [], 1)
        if not readable and not writeable:
            for timeout in [2, 4, 8]:
                try:
                    self._conn.shutdown(SHUT_RDWR)
                    self._conn.close()
                    self._conn.connect((self.host, self.port))
                    readable, writeable, _ = self._select([self._conn], [self._conn], [], timeout)
                    if not readable and not writeable:
                        pass
                    else:
                        # We have reconnected
                        self._conn.settimeout(self.timeout)
                        # indicates that we're in a transaction
                        self._in_transaction = False

                        # stores the session key
                        self._session_key = None
                        self._open_session()
                        return None
                except Exception as e:
                    # Ignore this at let the outer handler handle iterations
                    pass

            raise RexProConnectionException("Could not reconnect to database %s:%s" % (self.host, self.port))

    @contextmanager
    def transaction(self):
        """
        Context manager that opens a transaction and closes it at the end of it's code block, use with the 'with'
        statement

        Example::

            conn = RexproSyncConnection(host, port, graph_name)
            with conn.transaction():
                results = conn.execute(script, params)

        """
        self.test_connection()
        self.open_transaction()
        try:
            yield
        except:
            self.close_transaction(False)
            raise
        else:
            self.close_transaction(True)

    def execute(self, script, params={}, isolate=True, transaction=True):
        """
        executes the given gremlin script with the provided parameters

        :param script: the gremlin script to isolate
        :type script: str
        :param params: the parameters to execute the script with
        :type params: dictionary
        :param isolate: wraps the script in a closure so any variables set aren't persisted for the next execute call
        :type isolate: bool
        :param transaction: query will be wrapped in a transaction if set to True (default)
        :type transaction: bool

        :rtype: list
        """
        if self._in_transaction:
            transaction = False

        self._conn.send_message(
            messages.ScriptRequest(
                script=script,
                params=params,
                session_key=self._session_key,
                isolate=isolate,
                in_transaction=transaction,
            )
        )
        response = self._conn.get_response()

        if isinstance(response, messages.ErrorResponse):
            response.raise_exception()

        return response.results
