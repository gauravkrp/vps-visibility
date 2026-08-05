import re
import socket
import ssl
import time

from collector.util import ok


def gather(vhosts, via="localhost"):
    domains, upstreams = {}, {}
    for v in vhosts:
        for d in v["domains"]:
            r = probe_domain(d, v["tls"], via)
            if v["tls"] and r["status_code"] is None:
                fallback = probe_domain(d, False, via)
                if fallback["status_code"] is not None:
                    r = fallback
            domains[d] = r
        port = v.get("upstream_port")
        if port and not v.get("remote") and port not in upstreams:
            upstreams[port] = check_tcp(port)
    return ok({"domains": domains, "upstreams": upstreams})


def probe_domain(domain, tls, via="localhost", timeout=5):
    host = "127.0.0.1" if via == "localhost" else domain
    start = time.monotonic()
    code, tls_valid = None, None
    try:
        code = _request(domain, host, tls, True, timeout)
        tls_valid = True if tls else None
    except ssl.SSLCertVerificationError:
        # Bad or mismatched cert: record it, but still learn whether the app answers.
        tls_valid = False
        try:
            code = _request(domain, host, tls, False, timeout)
        except OSError:
            pass
    except OSError:
        pass
    return {
        "scheme": "https" if tls else "http",
        "status_code": code,
        "latency_ms": int((time.monotonic() - start) * 1000),
        "ok": code is not None and code < 500,
        "tls_valid": tls_valid,
    }


def _request(domain, host, tls, verify, timeout):
    sock = socket.create_connection((host, 443 if tls else 80), timeout)
    try:
        if tls:
            ctx = ssl.create_default_context()
            if not verify:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            sock = ctx.wrap_socket(sock, server_hostname=domain)
        sock.settimeout(timeout)
        request = ("GET / HTTP/1.1\r\nHost: %s\r\nUser-Agent: vps-visibility\r\n"
                   "Connection: close\r\n\r\n" % domain)
        sock.sendall(request.encode())
        return parse_status_line(sock.recv(1024))
    finally:
        try:
            sock.close()
        except OSError:
            pass


def parse_status_line(data):
    m = re.match(rb"HTTP/[\d.]+\s+(\d{3})", data or b"")
    return int(m.group(1)) if m else None


def check_tcp(port, timeout=3):
    try:
        socket.create_connection(("127.0.0.1", port), timeout).close()
        return True
    except OSError:
        return False
