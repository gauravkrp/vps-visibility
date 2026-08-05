import socket

from collector.util import error, ok, run_command


def gather(config, runner=run_command):
    try:
        with open("/proc/meminfo") as f:
            mem = parse_meminfo(f.read())
        with open("/proc/loadavg") as f:
            load = [float(x) for x in f.read().split()[:3]]
        with open("/proc/uptime") as f:
            uptime = int(float(f.read().split()[0]))
        rc, out = runner(["df", "-P"] + list(config.get("filesystems", ["/"])))
        return ok({
            "hostname": socket.gethostname(),
            "public_ip": config.get("public_ip") or _detect_ip(runner),
            "uptime_seconds": uptime,
            "load": load,
            "mem": mem,
            "filesystems": parse_df(out) if rc == 0 else [],
        })
    except Exception as e:
        return error("host stats failed: %s" % e)


def parse_meminfo(text):
    kv = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(":"):
            kv[parts[0][:-1]] = int(parts[1]) * 1024
    total = kv.get("MemTotal", 0)
    return {"total_bytes": total, "used_bytes": total - kv.get("MemAvailable", 0)}


def parse_df(text):
    out = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 6:
            total = int(parts[1]) * 1024
            used = int(parts[2]) * 1024
            out.append({"mount": parts[5], "total_bytes": total, "used_bytes": used,
                        "pct": round(used * 100.0 / total, 1) if total else 0.0})
    return out


def _detect_ip(runner):
    rc, out = runner(["hostname", "-I"])
    if rc != 0:
        return None
    for ip in out.split():
        # 172.* is broader than RFC1918 but on a VPS the public address never sits there
        if ":" in ip or ip.startswith(("10.", "192.168.", "127.", "172.")):
            continue
        return ip
    return None
