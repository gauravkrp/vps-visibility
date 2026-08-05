import json
import urllib.request


def compute(prev, current, config, now_ts):
    msgs = []
    thresholds = config["thresholds"]
    state = {"domains": {}, "apps": {}, "breaches": {},
             "cert_sent": dict(prev.get("cert_sent", {})), "gerrs": {}}

    prev_domains = prev.get("domains", {})
    for app in current["apps"]:
        for d in app["domains"]:
            name = d["domain"]
            was = prev_domains.get(name, {"ok": True, "fails": 0})
            if d["ok"]:
                if not was["ok"]:
                    msgs.append("RECOVERED: %s is serving again (status %s)" % (name, d["status_code"]))
                state["domains"][name] = {"ok": True, "fails": 0}
            else:
                fails = was["fails"] + 1
                if was["ok"] and fails >= 2:
                    msgs.append("DOWN: %s (status %s)" % (name, d["status_code"]))
                state["domains"][name] = {"ok": was["ok"] and fails < 2, "fails": fails}

    prev_apps = prev.get("apps", {})
    for app in current["apps"]:
        if app["runtime"] not in ("compose", "container", "pm2"):
            continue
        state["apps"][app["name"]] = {"started_at": app["started_at"]}
        old = prev_apps.get(app["name"])
        if (old and old.get("started_at") and app["started_at"]
                and app["started_at"] > old["started_at"]):
            msgs.append("RESTARTED: %s (started %s)" % (app["name"], app["started_at"]))
    for name in prev_apps:
        if name not in state["apps"]:
            msgs.append("GONE: %s is no longer running" % name)

    prev_breaches = prev.get("breaches", {})
    checks = []
    for fs in current["host"].get("filesystems", []):
        checks.append(("disk:%s" % fs["mount"], fs["pct"], thresholds["disk_pct"],
                       "Disk %s at %s%%" % (fs["mount"], fs["pct"])))
    mem = current["host"].get("mem", {})
    if mem.get("total_bytes"):
        pct = round(mem["used_bytes"] * 100.0 / mem["total_bytes"], 1)
        checks.append(("mem", pct, thresholds["mem_pct"], "Memory at %s%%" % pct))
    for key, value, limit, text in checks:
        breached = value >= limit
        if breached and not prev_breaches.get(key):
            msgs.append("THRESHOLD: " + text)
        state["breaches"][key] = breached

    warn_days = thresholds["cert_warn_days"]
    for path, info in current.get("certs", {}).items():
        days = info.get("days_left")
        if days is not None and days <= warn_days:
            if now_ts - state["cert_sent"].get(path, float("-inf")) >= 3 * 86400:
                msgs.append("CERT: %s expires in %s days" % (path, days))
                state["cert_sent"][path] = now_ts
        else:
            state["cert_sent"].pop(path, None)

    prev_gerrs = prev.get("gerrs", {})
    for name, result in current["gatherers"].items():
        if result["status"] == "error":
            state["gerrs"][name] = result.get("message", "")
            if name not in prev_gerrs:
                msgs.append("COLLECTOR: %s gatherer failing: %s" % (name, result.get("message", "")))

    return msgs, state


def send_telegram(token, chat_id, text, timeout=10):
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/sendMessage" % token,
        data=json.dumps({"chat_id": chat_id, "text": text}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode() == 200
    except OSError:
        return False
