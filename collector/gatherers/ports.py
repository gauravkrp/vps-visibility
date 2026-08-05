import re

from collector.util import error, ok, run_command


def gather(runner=run_command):
    rc, out = runner(["ss", "-Htlnp"])
    if rc != 0:
        return error("ss failed (rc=%s)" % rc)
    return ok(parse_ss(out))


def parse_ss(text):
    listeners = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        addr, _, port = parts[3].rpartition(":")
        if not port.isdigit():
            continue
        addr = addr.strip("[]").split("%")[0]
        m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        listeners.append({
            "addr": addr,
            "port": int(port),
            "pid": int(m.group(2)) if m else None,
            "process": m.group(1) if m else None,
            "public": addr in ("0.0.0.0", "::", "*"),
        })
    return listeners
