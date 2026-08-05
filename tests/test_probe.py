import socket
import threading
from unittest.mock import patch

from collector.gatherers.probe import check_tcp, gather, parse_status_line, probe_domain


def test_parse_status_line():
    assert parse_status_line(b"HTTP/1.1 200 OK\r\n") == 200
    assert parse_status_line(b"HTTP/1.0 502 Bad Gateway\r\n") == 502
    assert parse_status_line(b"HTTP/2 401\r\n") == 401
    assert parse_status_line(b"not http") is None
    assert parse_status_line(b"") is None
    assert parse_status_line(None) is None


def test_check_tcp_open_and_closed():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    accepter = threading.Thread(target=lambda: server.accept(), daemon=True)
    accepter.start()
    try:
        assert check_tcp(port) is True
    finally:
        server.close()
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    free_port = closed.getsockname()[1]
    closed.close()
    assert check_tcp(free_port) is False


def _serve_once(server, response):
    conn, _ = server.accept()
    try:
        conn.recv(4096)
        conn.sendall(response)
    finally:
        conn.close()


def test_probe_domain_direct_against_local_server():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    response = b"HTTP/1.1 200 OK\r\n\r\n"
    thread = threading.Thread(target=_serve_once, args=(server, response), daemon=True)
    thread.start()
    try:
        # probe_domain hardcodes the connect port to 443/tls or 80/plain, so we
        # can't point it at an ephemeral port through the public API; patch the
        # low-level socket connect target instead of the production code.
        real_create_connection = socket.create_connection

        def fake_create_connection(address, timeout=None):
            host, _ = address
            return real_create_connection((host, port), timeout)

        with patch("collector.gatherers.probe.socket.create_connection", side_effect=fake_create_connection):
            result = probe_domain("127.0.0.1", False, via="direct", timeout=2)
    finally:
        server.close()

    assert result["scheme"] == "http"
    assert result["status_code"] == 200
    assert result["ok"] is True
    assert result["tls_valid"] is None


def test_gather_iterates_vhosts_dedups_upstreams_and_skips_remote():
    calls = {"probe": [], "tcp": []}

    def fake_probe_domain(domain, tls, via="localhost", timeout=5):
        calls["probe"].append(domain)
        return {"scheme": "https" if tls else "http", "status_code": 200,
                "latency_ms": 1, "ok": True, "tls_valid": True if tls else None}

    def fake_check_tcp(port, timeout=3):
        calls["tcp"].append(port)
        return True

    vhosts = [
        {"domains": ["a.example.com"], "tls": True, "upstream_port": 3000},
        {"domains": ["b.example.com"], "tls": True, "upstream_port": 3000},
        {"domains": ["c.example.com"], "tls": False, "upstream_port": 4000, "remote": True},
    ]

    import collector.gatherers.probe as probe_mod
    orig_probe_domain, orig_check_tcp = probe_mod.probe_domain, probe_mod.check_tcp
    probe_mod.probe_domain = fake_probe_domain
    probe_mod.check_tcp = fake_check_tcp
    try:
        result = gather(vhosts)
    finally:
        probe_mod.probe_domain = orig_probe_domain
        probe_mod.check_tcp = orig_check_tcp

    assert result["status"] == "ok"
    assert calls["probe"] == ["a.example.com", "b.example.com", "c.example.com"]
    assert set(result["data"]["domains"]) == {"a.example.com", "b.example.com", "c.example.com"}
    assert calls["tcp"] == [3000]
    assert result["data"]["upstreams"] == {3000: True}
