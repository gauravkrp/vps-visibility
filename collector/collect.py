#!/usr/bin/env python3
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import alerts, history, join
from collector.gatherers import certs, docker, host, nginx, pm2, ports, probe
from collector.util import atomic_write_json, run_command

DEFAULTS = {
    "schema_version": 1,
    "dashboard_domain": None,
    "data_dir": "/var/lib/vps-visibility",
    "retention_days": 14,
    "probe_via": "localhost",
    "public_ip": None,
    "filesystems": ["/"],
    "thresholds": {"disk_pct": 90, "mem_pct": 90, "cert_warn_days": 14},
    "telegram": {"bot_token": None, "chat_id": None},
    "app_overrides": [],
}


def load_config(path):
    with open(path) as f:
        user = json.load(f)
    cfg = json.loads(json.dumps(DEFAULTS))
    for key, value in user.items():
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(value)
        else:
            cfg[key] = value
    return cfg


def _safe(fn):
    try:
        return fn()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    path = argv[0] if argv else "/etc/vps-visibility/config.json"
    try:
        cfg = load_config(path)
    except (OSError, ValueError) as e:
        print("cannot read config %s: %s" % (path, e), file=sys.stderr)
        return 1

    public = os.path.join(cfg["data_dir"], "public")
    os.makedirs(os.path.join(public, "history"), exist_ok=True)
    state_path = os.path.join(cfg["data_dir"], "state.json")
    try:
        with open(state_path) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    now = int(time.time())

    g = {
        "nginx": _safe(lambda: nginx.gather()),
        "docker": _safe(lambda: docker.gather()),
        "pm2": _safe(lambda: pm2.gather()),
        "ports": _safe(lambda: ports.gather()),
        "host": _safe(lambda: host.gather(cfg)),
    }
    vhosts = g["nginx"].get("data") or []
    cert_paths = sorted({v["cert_path"] for v in vhosts if v.get("cert_path")})
    g["certs"] = _safe(lambda: certs.gather(cert_paths, now))
    g["probe"] = _safe(lambda: probe.gather(vhosts, cfg["probe_via"]))

    joined = join.build(
        vhosts,
        g["docker"].get("data") or {"containers": [], "projects": {}},
        g["pm2"].get("data") or [],
        g["ports"].get("data") or [],
        g["probe"].get("data") or {"domains": {}, "upstreams": {}},
        g["certs"].get("data") or {},
        state.get("du_cache", {}),
        cfg["app_overrides"],
    )
    du_cache = history.refresh_du(joined["apps"], state, now, run_command)
    for app in joined["apps"]:
        if app.get("dir") and du_cache.get(app["dir"]) is not None:
            app["disk_bytes"] = du_cache[app["dir"]]

    warnings = list(joined["warnings"])
    for name, result in g.items():
        if result["status"] == "error":
            warnings.append({"kind": "gatherer_error",
                            "message": "%s: %s" % (name, result.get("message"))})
    certs_data = g["certs"].get("data") or {}
    for cert_path, info in certs_data.items():
        if info["days_left"] <= cfg["thresholds"]["cert_warn_days"]:
            warnings.append({"kind": "cert_expiring",
                            "message": "%s expires in %s days" % (cert_path, info["days_left"])})
    host_data = g["host"].get("data") or {}
    for fs in host_data.get("filesystems", []):
        if fs["pct"] >= cfg["thresholds"]["disk_pct"]:
            warnings.append({"kind": "disk", "message": "disk %s at %s%%" % (fs["mount"], fs["pct"])})
    mem = host_data.get("mem", {})
    if mem.get("total_bytes"):
        mem_pct = round(mem["used_bytes"] * 100.0 / mem["total_bytes"], 1)
        if mem_pct >= cfg["thresholds"]["mem_pct"]:
            warnings.append({"kind": "mem", "message": "memory at %s%%" % mem_pct})

    current = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "interval_seconds": 300,
        "host": host_data,
        "apps": joined["apps"],
        "vhosts": joined["vhosts"],
        "certs": certs_data,
        "warnings": warnings,
        "gatherers": {k: {kk: vv for kk, vv in v.items() if kk != "data"}
                      for k, v in g.items()},
        # From the previous run: alerts fire after current.json is written
        "telegram_error": state.get("telegram_error"),
    }
    atomic_write_json(os.path.join(public, "current.json"), current)
    history.append_record(public, current, now)
    history.prune(public, cfg["retention_days"], now)

    msgs, alert_state = alerts.compute(state.get("alert", {}), current, cfg, now)
    telegram = cfg["telegram"]
    state["telegram_error"] = None
    if msgs and telegram.get("bot_token") and telegram.get("chat_id"):
        sent = alerts.send_telegram(telegram["bot_token"], telegram["chat_id"], "\n".join(msgs))
        state["telegram_error"] = None if sent else "send failed at %s" % now
    state["alert"] = alert_state
    atomic_write_json(state_path, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
