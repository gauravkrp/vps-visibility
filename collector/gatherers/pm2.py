import json
from datetime import datetime, timezone

from collector.util import absent, error, ok, run_command


def gather(runner=run_command):
    rc, out = runner(["pm2", "jlist"], timeout=30)
    if rc == -1:
        return absent("pm2 not installed")
    if rc != 0:
        return error("pm2 jlist failed (rc=%s)" % rc)
    start = out.find("[")
    if start == -1:
        return error("pm2 jlist returned no JSON")
    try:
        procs = json.loads(out[start:])
    except ValueError as e:
        return error("pm2 jlist unparseable: %s" % e)
    return ok([_proc(p) for p in procs])


def _proc(p):
    env = p.get("pm2_env", {})
    uptime_ms = env.get("pm_uptime")
    started = None
    if isinstance(uptime_ms, (int, float)):
        started = datetime.fromtimestamp(uptime_ms / 1000, tz=timezone.utc).isoformat()
    return {
        "name": p.get("name"),
        "pid": p.get("pid") or None,
        "status": env.get("status"),
        "mem_bytes": p.get("monit", {}).get("memory", 0),
        "restarts": env.get("restart_time", 0),
        "started_at": started,
        "cwd": env.get("pm_cwd"),
    }
