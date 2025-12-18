import json
import socket


"""
Common helper functions shared by:
- Clients
- Server / participant nodes
- The coordinator node

All components talk over TCP using a very small JSON-over-newline protocol.
"""


def send_json(conn: socket.socket, message: dict) -> None:
    """
    Serialize a Python dict to JSON and send it over a TCP socket.

    We terminate each JSON document with a newline so that the receiver
    can detect message boundaries (one line = one message).
    """
    data = (json.dumps(message) + "\n").encode("utf-8")
    conn.sendall(data)


def recv_json(conn: socket.socket) -> dict | None:
    """
    Read a single JSON message from a TCP socket.

    - Blocks until at least one full line is received OR the peer closes.
    - Returns a Python dict parsed from the JSON line.
    - Returns None if the connection is closed before any data arrives.
    """
    buffer = b""
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            # Connection closed
            if not buffer:
                return None
            break
        buffer += chunk
        if b"\n" in buffer:
            # Split at the first newline; ignore any extra bytes for simplicity.
            line, _, _rest = buffer.partition(b"\n")
            try:
                return json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                # In this toy system we just treat malformed JSON as a dropped message.
                return None
    return None


def make_address(host: str, port: int) -> tuple[str, int]:
    """
    Convenience wrapper so all components build socket addresses the same way.
    """
    return host, port

