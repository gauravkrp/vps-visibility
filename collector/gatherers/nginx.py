import glob
import os
import re

from collector.util import absent, error, ok

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def gather(sites_dir="/etc/nginx/sites-enabled"):
    if not os.path.isdir(sites_dir):
        return absent("no nginx sites-enabled directory")
    try:
        blocks = []
        for path in sorted(glob.glob(os.path.join(sites_dir, "*"))):
            if os.path.isfile(path):
                with open(path, errors="replace") as f:
                    blocks.extend(parse_server_blocks(f.read()))
        return ok(merge_blocks(blocks))
    except Exception as e:
        return error("nginx parse failed: %s" % e)


def parse_server_blocks(text):
    text = re.sub(r"#[^\n]*", "", text)
    out = []
    for m in re.finditer(r"\bserver\s*\{", text):
        depth, j = 1, m.end()
        while j < len(text) and depth:
            depth += (text[j] == "{") - (text[j] == "}")
            j += 1
        out.append(_parse_block(text[m.end():j - 1]))
    return [b for b in out if b["domains"]]


def _parse_block(body):
    names = re.search(r"\bserver_name\s+([^;]+);", body)
    domains = sorted(set(names.group(1).split())) if names else []
    domains = [d for d in domains if d != "_"]

    ssl = False
    for lm in re.finditer(r"\blisten\s+([^;]+);", body):
        ssl = ssl or (" ssl" in " " + lm.group(1))

    upstream_host = upstream_port = None
    pp = re.search(r"\bproxy_pass\s+https?://([^;/\s]+)", body)
    if pp:
        target = pp.group(1)
        if ":" in target.strip("[]"):
            host, _, port = target.rpartition(":")
            upstream_host = host.strip("[]")
            upstream_port = int(port) if port.isdigit() else None
        else:
            upstream_host, upstream_port = target, 80

    root = re.search(r"\broot\s+([^;]+);", body)
    cert = re.search(r"\bssl_certificate\s+([^;]+);", body)
    return {
        "domains": domains,
        "ssl": ssl,
        "upstream_host": upstream_host,
        "upstream_port": upstream_port,
        "static_root": root.group(1).strip() if root else None,
        "cert_path": cert.group(1).strip() if cert else None,
    }


def merge_blocks(blocks):
    merged = {}
    for b in blocks:
        v = merged.setdefault(tuple(b["domains"]), {
            "domains": b["domains"], "upstream_host": None, "upstream_port": None,
            "static_root": None, "tls": False, "cert_path": None,
        })
        v["tls"] = v["tls"] or b["ssl"]
        for field in ("upstream_host", "upstream_port", "static_root", "cert_path"):
            if v[field] is None and b[field] is not None:
                v[field] = b[field]
    result = []
    for v in merged.values():
        v["remote"] = bool(v["upstream_host"]) and v["upstream_host"] not in LOCAL_HOSTS
        result.append(v)
    return result
