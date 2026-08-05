import json
from datetime import datetime, timezone

from collector.util import absent, error, ok, run_command


def gather(runner=run_command):
    rc, out = runner(["pm2", "jlist"], timeout=30)
    if rc == -1:
        return absent("pm2 not installed")
    if rc != 0:
        return error("pm2 jlist failed (rc=%s)" % rc)
    procs = _parse_jlist(out)
    if procs is None:
        return error("pm2 jlist returned no JSON")
    return ok([_proc(p) for p in procs])


def _parse_jlist(out):
    # pm2 jlist often prints daemon-spawn banner lines before the JSON, and
    # those banners can themselves start with "[" (e.g. "[PM2] Spawning...").
    # Try every line that looks like a JSON start and keep the first one
    # that actually parses, instead of trusting the first "[" in the output.
    pos = 0
    for line in out.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("["):
            start = pos + (len(line) - len(stripped))
            try:
                return json.loads(out[start:])
            except ValueError:
                pass
        pos += len(line)
    return None


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
