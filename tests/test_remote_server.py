from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import queue
import socket
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sara.remote.commands import CommandSession
from sara.remote.server import MainThreadDispatcher, MAX_LINE_BYTES, RemoteServer
from test_remote_commands import Frame


def pump_until(futures, callbacks):
    deadline = time.monotonic() + 5
    while not all(future.done() for future in futures):
        assert time.monotonic() < deadline, "TCP request stalled"
        try:
            callback = callbacks.get(timeout=0.01)
        except queue.Empty:
            continue
        callback()
    return [future.result() for future in futures]


@pytest.fixture
def remote():
    frame = Frame()
    callbacks = queue.Queue()
    dispatcher = MainThreadDispatcher(callbacks.put, timeout=0.2)
    server = RemoteServer(dispatcher, lambda: CommandSession(frame, program_version="1.2.3"), port=0)
    server.start()
    yield frame, callbacks, dispatcher, server
    server.stop()


def exchange(address, payload, lines):
    with socket.create_connection(address, timeout=2) as client:
        client.sendall(payload)
        with client.makefile("rb") as reader:
            return [reader.readline() for _ in range(lines)]


def test_socket_bind_is_loopback_and_other_local_address_cannot_connect(remote):
    _, _, _, server = remote
    assert server.address[0] == "127.0.0.1"
    # Nawet inny adres loopback nie jest interfejsem nasłuchu.
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.2", server.address[1]), timeout=0.2)
    assert not server._server.verify_request(None, ("192.0.2.1", 1))
    assert not server._server.verify_request(None, ("127.0.0.2", 1))


def test_real_socket_commands_run_on_main_thread(remote):
    frame, callbacks, _, server = remote
    threads = []
    frame._on_global_play_next = lambda event: threads.append(threading.current_thread())
    with ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(exchange, server.address, b"Play\r\nSkip\n", 2)
        result = pump_until([request], callbacks)[0]
    assert result == [b"0000001\r\n", b"0000001\r\n"]
    assert threads == [threading.main_thread(), threading.main_thread()]


def test_real_socket_framing_batch_case_and_trackinfo(remote):
    _, callbacks, _, server = remote
    with ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(exchange, server.address,
                              b"hElO,Stat\r\nSelectIndex=1\nCheckToggle\nTrackInfoEx=0-1\nUNKNOWN\n", 7)
        result = pump_until([request], callbacks)[0]
    assert result == [b"SARA v1.2.3\r\n", b"0000001\r\n", b"1\r\n", b"1\r\n",
                      "0|0|pending|Żółw|Tytuł|120000|0\r\n".encode(),
                      b"1|1|pending|Autor|Drugi|45000|0\r\n", b"ERR unknown\r\n"]


def test_fragmented_tcp_and_multiple_clients(remote):
    _, callbacks, _, server = remote

    def client():
        with socket.create_connection(server.address, timeout=2) as sock:
            sock.sendall(b"He")
            sock.sendall(b"lo\r")
            sock.sendall(b"\nStat,Stat\n")
            with sock.makefile("rb") as reader:
                return [reader.readline() for _ in range(3)]

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = pump_until([pool.submit(client) for _ in range(3)], callbacks)
    assert results == [[b"SARA v1.2.3\r\n", b"0000001\r\n", b"0000000\r\n"]] * 3


def test_main_thread_timeout_does_not_execute_late(remote):
    frame, callbacks, _, server = remote
    assert exchange(server.address, b"Play\n", 1) == [b"ERR timeout\r\n"]
    callbacks.get(timeout=1)()
    frame._on_global_play_next.assert_not_called()


def test_close_cancels_queued_command_and_closes_clients(remote):
    frame, callbacks, _, server = remote
    with ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(exchange, server.address, b"Play\n", 1)
        callback = callbacks.get(timeout=1)
        server.stop()
        callback()
        assert request.result(timeout=2) in ([b"ERR closed\r\n"], [b""])
    frame._on_global_play_next.assert_not_called()
    with pytest.raises(OSError):
        socket.create_connection(server.address, timeout=0.2)
    server.stop()


def test_wrong_dispatcher_thread_is_rejected():
    function = Mock(return_value=["OK"])
    dispatcher = MainThreadDispatcher(lambda callback: callback())
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(dispatcher.call, function).result(timeout=1) == ["ERR internal"]
    function.assert_not_called()


def test_dispatcher_error_and_closed_state():
    dispatcher = MainThreadDispatcher(lambda callback: callback())
    assert dispatcher.call(Mock(side_effect=ValueError("test"))) == ["ERR internal"]
    dispatcher.close()
    callback = Mock()
    assert dispatcher.call(callback) == ["ERR closed"]
    callback.assert_not_called()


@pytest.mark.parametrize("payload,reply", [
    (b"\xff\n", b"ERR encoding\r\n"),
    (b"x" * MAX_LINE_BYTES + b"\n", b"ERR line too long\r\n"),
])
def test_malformed_transport(remote, payload, reply):
    frame, _, _, server = remote
    assert exchange(server.address, payload, 1) == [reply]
    frame._on_global_play_next.assert_not_called()


def test_restart_same_port_after_closing_connected_client():
    callbacks = queue.Queue()
    dispatcher = MainThreadDispatcher(callbacks.put)
    server = RemoteServer(dispatcher, lambda: CommandSession(Frame()), port=0)
    server.start()
    address = server.address
    with socket.create_connection(address, timeout=1) as client:
        # Oczekujące polecenie gwarantuje przyjęcie klienta przed zamknięciem.
        client.sendall(b"Helo\n")
        callback = callbacks.get(timeout=1)
        server.stop()
        callback()
        while client.recv(1024):
            pass
    replacement = RemoteServer(MainThreadDispatcher(callbacks.put), lambda: CommandSession(Frame()), port=address[1])
    replacement.start()
    replacement.stop()


def test_port_conflict_is_not_shared(remote):
    _, _, dispatcher, server = remote
    with pytest.raises(OSError):
        RemoteServer(dispatcher, lambda: SimpleNamespace(), port=server.address[1])
