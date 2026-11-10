"""The deadline socket must stay readable after http.client closes the connection ("Connection: close"): the response
keeps reading the body through makefile(). Before the fix every real server that closed the connection showed up as
"unreachable" (MCP servers and publish-and-check pages alike), while the stubbed transport tests passed."""

import http.client
import socket
import threading
import time

from apps.learning.safe_fetch import _DeadlineSocket


def _serve(server_sock, body: bytes):
    conn = server_sock
    conn.recv(65536)
    head = (
        b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n"
        b"Connection: close\r\n\r\n"
    )
    chunk = f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
    conn.sendall(head + chunk)
    conn.close()


def test_body_is_readable_after_the_connection_closes_itself():
    client, server = socket.socketpair()
    body = b'data: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'
    t = threading.Thread(target=_serve, args=(server, body))
    t.start()
    conn = http.client.HTTPConnection("example.test")
    guarded = _DeadlineSocket(client, time.monotonic() + 5, 1 << 20)
    conn.sock = guarded
    conn.request("POST", "/mcp", body=b"{}", headers={"Connection": "close"})
    resp = conn.getresponse()  # http.client closes `conn` here because of Connection: close
    assert resp.read() == body  # ...and the body must still be readable
    guarded.force_close()
    t.join(2)


def test_close_waits_for_open_readers_then_releases_the_socket():
    a, b = socket.socketpair()
    guarded = _DeadlineSocket(a, time.monotonic() + 5, 1 << 20)
    reader = guarded.makefile("rb")
    guarded.close()
    b.sendall(b"hello")
    assert reader.read1(5) == b"hello"  # still open while a reader holds it
    reader.close()
    assert a.fileno() == -1  # released once the last reader is done
    b.close()


def test_force_close_releases_even_with_readers_left():
    a, b = socket.socketpair()
    guarded = _DeadlineSocket(a, time.monotonic() + 5, 1 << 20)
    guarded.makefile("rb")
    guarded.force_close()
    assert a.fileno() == -1
    b.close()
