"""Wieloklientowy serwer loopback i bezpieczna kolejka do wątku GUI."""

from __future__ import annotations

from concurrent.futures import Future, TimeoutError
import logging
import os
import socket
import socketserver
import threading
from typing import Callable, cast


logger = logging.getLogger(__name__)
MAX_LINE_BYTES = 4096


class MainThreadDispatcher:
    """Nie wykonuje opóźnionego polecenia po timeout ani po zamknięciu ramki."""

    def __init__(self, call_after: Callable, *, timeout: float = 2.0) -> None:
        self._call_after = call_after
        self.timeout = timeout
        self._lock = threading.Lock()
        self._pending: set[Future] = set()
        self._closed = False

    def call(self, function: Callable, *args) -> list[str]:
        future: Future = Future()
        with self._lock:
            if self._closed:
                return ["ERR closed"]
            self._pending.add(future)

        def invoke() -> None:
            if not future.set_running_or_notify_cancel():
                return
            try:
                if threading.current_thread() is not threading.main_thread():
                    raise RuntimeError("Remote command outside main thread")
                future.set_result(function(*args))
            except Exception as exc:  # Nie przenosimy wyjątku do pętli wx.
                future.set_exception(exc)

        try:
            self._call_after(invoke)
            return future.result(timeout=self.timeout)
        except TimeoutError:
            future.cancel()
            return ["ERR timeout"]
        except Exception:
            cancelled = future.cancelled()
            future.cancel()
            if cancelled:
                return ["ERR closed"]
            logger.exception("Remote command failed")
            return ["ERR internal"]
        finally:
            with self._lock:
                self._pending.discard(future)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for future in self._pending:
                future.cancel()


class _ClientHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        threading.current_thread().name = "sara-remote-client"
        server = cast(_LoopbackServer, self.server)
        session = server.session_factory()
        self.connection.settimeout(30.0)
        try:
            while not server.closing.is_set():
                data = self.rfile.readline(MAX_LINE_BYTES + 1)
                if not data:
                    return
                if len(data) > MAX_LINE_BYTES:
                    self.wfile.write(b"ERR line too long\r\n")
                    return
                if not data.endswith(b"\n"):
                    return
                try:
                    line = data.rstrip(b"\r\n").decode("utf-8")
                except UnicodeDecodeError:
                    self.wfile.write(b"ERR encoding\r\n")
                    continue
                responses = server.dispatcher.call(session.execute_line, line)
                self.wfile.write(("\r\n".join(responses) + "\r\n").encode("utf-8"))
        except (OSError, TimeoutError):
            return


class _LoopbackServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    # POSIX: szybki restart po TIME_WAIT. Windows: wyłączność portu.
    allow_reuse_address = os.name != "nt"
    request_queue_size = 16

    def __init__(self, port, dispatcher, session_factory):
        self.dispatcher = dispatcher
        self.session_factory = session_factory
        self.closing = threading.Event()
        self.clients: set[socket.socket] = set()
        self.clients_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), _ClientHandler)

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def verify_request(self, request, client_address):
        return client_address[0] == "127.0.0.1" and not self.closing.is_set()

    def process_request(self, request, client_address):
        with self.clients_lock:
            if len(self.clients) >= 16 or self.closing.is_set():
                self.shutdown_request(request)
                return
            self.clients.add(cast(socket.socket, request))
        try:
            super().process_request(request, client_address)
        except Exception:
            with self.clients_lock:
                self.clients.discard(request)
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self.clients_lock:
                self.clients.discard(request)


class RemoteServer:
    """Adres jest stały; port 0 służy testom z prawdziwym gniazdem TCP."""

    def __init__(self, dispatcher: MainThreadDispatcher, session_factory: Callable, *, port: int = 51443) -> None:
        self._server = _LoopbackServer(port, dispatcher, session_factory)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="sara-remote-server",
            daemon=True,
        )
        self._stopped = False

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), port

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._server.closing.set()
        self._server.dispatcher.close()
        if self._thread.is_alive():
            self._server.shutdown()
            self._thread.join(timeout=1.0)
        with self._server.clients_lock:
            clients = list(self._server.clients)
        for client in clients:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self._server.server_close()
