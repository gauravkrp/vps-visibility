import json
import os
import time


def append_record(public_dir, current, now_ts):
    record = {
        "ts": now_ts,
        "mem_pct": _mem_pct(current),
        "disk": {f["mount"]: f["pct"] for f in current["host"].get("filesystems", [])},
        "apps": {a["name"]: [a["mem_bytes"], a["disk_bytes"] or 0, 1 if _app_ok(a) else 0]
                 for a in current["apps"]},
    }
    day = time.strftime("%Y-%m-%d", time.gmtime(now_ts))
    path = os.path.join(public_dir, "history", day + ".jsonl")
    with open(path, "a") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


def prune(public_dir, retention_days, now_ts):
    hist = os.path.join(public_dir, "history")
    cutoff = time.strftime("%Y-%m-%d", time.gmtime(now_ts - retention_days * 86400))
    for name in os.listdir(hist):
        if name.endswith(".jsonl") and name[:-6] < cutoff:
            os.remove(os.path.join(hist, name))


def refresh_du(apps, state, now_ts, runner):
    if now_ts - state.get("du_ts", 0) < 3600:
        return state.get("du_cache", {})
    cache = {}
    for app in apps:
        directory = app.get("dir")
        if directory and directory not in cache and os.path.isdir(directory):
            rc, out = runner(["du", "-s", "--block-size=1", directory], timeout=120)
            if rc == 0 and out.split():
                cache[directory] = int(out.split()[0])
    state["du_cache"] = cache
    state["du_ts"] = now_ts
    return cache


def _mem_pct(current):
    mem = current["host"].get("mem", {})
    total = mem.get("total_bytes") or 0
    return round(mem.get("used_bytes", 0) * 100.0 / total, 1) if total else 0.0


def _app_ok(app):
    if not app["domains"]:
        return True
    return all(d.get("ok") for d in app["domains"])
