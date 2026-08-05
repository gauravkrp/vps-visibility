import json

from collector.util import absent, error, ok, parse_size, run_command


def gather(runner=run_command):
    rc, out = runner(["docker", "ps", "-aq"])
    if rc == -1:
        return absent("docker not installed")
    if rc != 0:
        return error("docker ps failed (rc=%s)" % rc)
    ids = out.split()
    if not ids:
        return ok({"containers": [], "projects": {}})
    rc, out = runner(["docker", "inspect"] + ids, timeout=30)
    if rc != 0:
        return error("docker inspect failed (rc=%s)" % rc)
    try:
        items = json.loads(out)
    except ValueError as e:
        return error("docker inspect unparseable: %s" % e)
    stats = _mem_by_name(runner)
    containers = [_container(item, stats) for item in items]
    projects = {}
    for c in containers:
        if c["compose_project"]:
            entry = projects.setdefault(c["compose_project"], {"working_dir": None})
            entry["working_dir"] = entry["working_dir"] or c["compose_workdir"]
    return ok({"containers": containers, "projects": projects})


def _mem_by_name(runner):
    rc, out = runner(["docker", "stats", "--no-stream", "--format",
                      "{{.Name}}\t{{.MemUsage}}"], timeout=30)
    mem = {}
    if rc == 0:
        for line in out.splitlines():
            if "\t" in line:
                name, usage = line.split("\t", 1)
                mem[name] = parse_size(usage.split("/")[0])
    return mem


def _container(item, stats):
    labels = item.get("Config", {}).get("Labels") or {}
    published = []
    for cport, bindings in (item.get("NetworkSettings", {}).get("Ports") or {}).items():
        for b in bindings or []:
            if str(b.get("HostPort", "")).isdigit():
                published.append({"host_ip": b.get("HostIp", ""),
                                  "host_port": int(b["HostPort"]),
                                  "container_port": cport})
    state = item.get("State", {})
    name = item.get("Name", "").lstrip("/")
    return {
        "name": name,
        "image": item.get("Config", {}).get("Image"),
        "state": state.get("Status"),
        "health": (state.get("Health") or {}).get("Status"),
        "started_at": state.get("StartedAt"),
        "compose_project": labels.get("com.docker.compose.project"),
        "compose_workdir": labels.get("com.docker.compose.project.working_dir"),
        "published_ports": published,
        "mem_bytes": stats.get(name, 0),
    }
