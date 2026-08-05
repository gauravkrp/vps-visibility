def build(vhosts, docker_data, pm2_procs, listeners, probe_data, cert_info, du_cache, overrides):
    containers = docker_data.get("containers", [])
    projects = docker_data.get("projects", {})

    port_to_container = {}
    for c in containers:
        for p in c["published_ports"]:
            port_to_container.setdefault(p["host_port"], c)
    port_to_listener = {}
    for l in listeners:
        port_to_listener.setdefault(l["port"], l)
    pm2_by_pid = {p["pid"]: p for p in pm2_procs if p.get("pid")}
    over_by_name = {o["match"].lower(): o for o in overrides}

    apps = {}

    def container_key(c):
        return ("compose:" + c["compose_project"]) if c["compose_project"] else ("container:" + c["name"])

    for c in containers:
        if c["compose_project"]:
            directory = projects.get(c["compose_project"], {}).get("working_dir")
            app = apps.setdefault(container_key(c), _new_app(c["compose_project"], "compose", directory))
        else:
            app = apps.setdefault(container_key(c), _new_app(c["name"], "container", None))
        app["containers"].append({"name": c["name"], "state": c["state"], "health": c["health"]})
        app["mem_bytes"] += c["mem_bytes"] or 0
        started = c.get("started_at")
        if c["state"] == "running" and started:
            # ISO timestamps from docker share one format, so string comparison is safe
            if app["started_at"] is None or started > app["started_at"]:
                app["started_at"] = started

    for p in pm2_procs:
        app = apps.setdefault("pm2:" + p["name"], _new_app(p["name"], "pm2", p.get("cwd")))
        app["mem_bytes"] += p.get("mem_bytes") or 0
        app["started_at"] = app["started_at"] or p.get("started_at")

    vhosts_out, warnings = [], []
    for v in vhosts:
        app_key = None
        status = "ok"
        port = v.get("upstream_port")
        if v.get("remote"):
            status = "remote"
        elif port:
            c = port_to_container.get(port)
            listener = port_to_listener.get(port)
            dead = probe_data.get("upstreams", {}).get(port) is False
            if c:
                app_key = container_key(c)
            elif listener and listener["pid"] in pm2_by_pid:
                app_key = "pm2:" + pm2_by_pid[listener["pid"]]["name"]
            elif listener:
                name = _owner_name_for_port(port, port_to_container, port_to_listener, pm2_by_pid)
                app_key = "process:" + name
                # Only register the app once we know the port is alive - a container
                # or pm2 app already exists regardless, but this bare-process entry
                # is created purely from this vhost and must not outlive a dead verdict.
                if not dead:
                    apps.setdefault(app_key, _new_app(name, "process", None))
            if dead:
                status = "dead"
                app_key = None
                warnings.append({"kind": "dead_vhost",
                                 "message": "%s points at 127.0.0.1:%s but nothing is listening there"
                                            % (", ".join(v["domains"]), port)})
        elif v.get("static_root"):
            status = "static"
            app_key = "static:" + v["static_root"]
            apps.setdefault(app_key, _new_app(v["static_root"], "static", v["static_root"]))
        else:
            status = "dead"
            warnings.append({"kind": "dead_vhost",
                             "message": "%s has no proxy_pass or root directive" % ", ".join(v["domains"])})

        # Every vhost gets its domains probed for a bad cert, attached app or not -
        # a dead or remote vhost can still be serving a broken certificate.
        for d in v["domains"]:
            pr = probe_data.get("domains", {}).get(d, {})
            if app_key and app_key in apps:
                cert = cert_info.get(v.get("cert_path") or "", {})
                apps[app_key]["domains"].append({
                    "domain": d,
                    "scheme": pr.get("scheme"),
                    "status_code": pr.get("status_code"),
                    "ok": pr.get("ok"),
                    "tls_valid": pr.get("tls_valid"),
                    "cert_days_left": cert.get("days_left"),
                })
            if pr.get("tls_valid") is False:
                warnings.append({"kind": "tls_invalid",
                                 "message": "%s serves a certificate that fails verification" % d})
        vhosts_out.append({
            "domains": v["domains"], "upstream_port": port, "static_root": v.get("static_root"),
            "tls": v["tls"], "app": apps[app_key]["name"] if app_key and app_key in apps else None,
            "status": status,
        })

    seen_ports = set()
    for l in listeners:
        if l["public"] and l["port"] not in (22, 80, 443) and l["port"] not in seen_ports:
            seen_ports.add(l["port"])
            who = _owner_name_for_port(l["port"], port_to_container, port_to_listener, pm2_by_pid)
            warnings.append({"kind": "exposed_port",
                             "message": "port %s (%s) is bound to %s and bypasses nginx and TLS"
                                        % (l["port"], who, l["addr"])})

    for app in apps.values():
        override = over_by_name.get(app["name"].lower())
        if override:
            app["dir"] = override.get("dir", app["dir"])
            app["label"] = override.get("label", app["label"])
        if app["dir"] and du_cache.get(app["dir"]) is not None:
            app["disk_bytes"] = du_cache[app["dir"]]

    return {"apps": sorted(apps.values(), key=lambda a: a["name"].lower()),
            "vhosts": vhosts_out, "warnings": warnings}


def _owner_name_for_port(port, port_to_container, port_to_listener, pm2_by_pid):
    """Resolve the name of whatever owns a port, in one priority order used
    everywhere: container (or its compose project) beats a pm2 process
    listening on that port, which beats the raw listener process name."""
    c = port_to_container.get(port)
    if c:
        return c["compose_project"] or c["name"]
    listener = port_to_listener.get(port)
    if listener:
        pm2 = pm2_by_pid.get(listener["pid"])
        if pm2:
            return pm2["name"]
        return listener["process"] or "unknown"
    return "unknown"


def _new_app(name, runtime, directory):
    return {"name": name, "label": name, "runtime": runtime, "dir": directory,
            "domains": [], "mem_bytes": 0, "disk_bytes": None, "started_at": None,
            "containers": []}
