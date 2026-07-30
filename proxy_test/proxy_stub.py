#!/usr/bin/env python3
"""Tiny HTTP forward-proxy stub. Logs the absolute-URI request line to
PROXY_LOG (default /tmp/proxy.log) and replies with FROM_PROXY!. Doesn't
actually forward upstream - we only need to know the proxy was reached.
"""
import os
import socket
import sys
import threading

PORT = int(os.environ.get("PROXY_PORT", "18888"))
LOG = os.environ.get("PROXY_LOG", "/tmp/proxy.log")


def handle(conn: socket.socket) -> None:
    try:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
            if len(data) > 65536:
                break
        first_line = data.split(b"\r\n", 1)[0].decode("latin-1", "replace")
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(first_line + "\n")
        body = b"FROM_PROXY!\n"
        resp = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"Connection: close\r\n\r\n"
        ) + body
        conn.sendall(resp)
    finally:
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        conn.close()


def main() -> None:
    open(LOG, "w").close()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", PORT))
    sock.listen(8)
    sys.stdout.write(f"proxy_stub listening on 127.0.0.1:{PORT}, log={LOG}\n")
    sys.stdout.flush()
    while True:
        conn, _ = sock.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
