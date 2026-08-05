from datetime import datetime, timezone

from collector.util import ok, run_command


def gather(cert_paths, now_ts, runner=run_command):
    data = {}
    for path in cert_paths:
        rc, out = runner(["openssl", "x509", "-enddate", "-noout", "-in", path])
        if rc == 0 and "notAfter=" in out:
            try:
                data[path] = parse_enddate(out.strip(), now_ts)
            except ValueError:
                pass
    return ok(data)


def parse_enddate(text, now_ts):
    value = " ".join(text.split("notAfter=", 1)[1].split())
    dt = datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    return {"not_after": dt.isoformat(),
            "days_left": int((dt.timestamp() - now_ts) // 86400)}
