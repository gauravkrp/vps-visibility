from collector import join

VHOSTS = [
    {"domains": ["app.example.com", "www.app.example.com"], "upstream_host": "127.0.0.1",
     "upstream_port": 3000, "static_root": None, "tls": True,
     "cert_path": "/etc/letsencrypt/live/app.example.com/fullchain.pem", "remote": False},
    {"domains": ["cms.example.com"], "upstream_host": "127.0.0.1", "upstream_port": 8055,
     "static_root": None, "tls": True, "cert_path": None, "remote": False},
    {"domains": ["monitoring.example.com"], "upstream_host": "127.0.0.1", "upstream_port": 8080,
     "static_root": None, "tls": True, "cert_path": None, "remote": False},
]

CONTAINERS = [
    {"name": "shop-web-1", "image": "shop-web", "state": "running", "health": None,
     "started_at": "2026-08-04T18:00:00.000000000Z", "compose_project": "shop",
     "compose_workdir": "/root/shop",
     "published_ports": [{"host_ip": "127.0.0.1", "host_port": 3000, "container_port": "80/tcp"}],
     "mem_bytes": 5000000},
    {"name": "shop-backend-1", "image": "shop-backend", "state": "running", "health": "healthy",
     "started_at": "2026-08-04T18:00:05.000000000Z", "compose_project": "shop",
     "compose_workdir": "/root/shop", "published_ports": [], "mem_bytes": 700000000},
    {"name": "game", "image": "game:latest", "state": "running", "health": None,
     "started_at": "2026-06-15T08:00:00.000000000Z", "compose_project": None,
     "compose_workdir": None,
     "published_ports": [{"host_ip": "0.0.0.0", "host_port": 65410, "container_port": "65410/tcp"}],
     "mem_bytes": 1800000000},
]

DOCKER_DATA = {"containers": CONTAINERS, "projects": {"shop": {"working_dir": "/root/shop"}}}

PM2 = [{"name": "cms", "pid": 2222, "status": "online", "mem_bytes": 190000000,
        "restarts": 3, "started_at": "2025-08-04T09:33:20+00:00", "cwd": "/var/www/cms"}]

LISTENERS = [
    {"addr": "127.0.0.1", "port": 3000, "pid": 1111, "process": "docker-proxy", "public": False},
    {"addr": "0.0.0.0", "port": 8055, "pid": 2222, "process": "node", "public": True},
    {"addr": "0.0.0.0", "port": 65410, "pid": 1520869, "process": "docker-proxy", "public": True},
    {"addr": "::", "port": 65410, "pid": 1520881, "process": "docker-proxy", "public": True},
    {"addr": "0.0.0.0", "port": 80, "pid": 3333, "process": "nginx", "public": True},
    {"addr": "0.0.0.0", "port": 22, "pid": 44, "process": "sshd", "public": True},
]

PROBE = {
    "domains": {
        "app.example.com": {"scheme": "https", "status_code": 200, "latency_ms": 12, "ok": True, "tls_valid": True},
        "www.app.example.com": {"scheme": "https", "status_code": 200, "latency_ms": 15, "ok": True, "tls_valid": True},
        "cms.example.com": {"scheme": "https", "status_code": 401, "latency_ms": 30, "ok": True, "tls_valid": False},
        "monitoring.example.com": {"scheme": "https", "status_code": 502, "latency_ms": 5, "ok": False, "tls_valid": True},
    },
    "upstreams": {3000: True, 8055: True, 8080: False},
}

CERTS = {"/etc/letsencrypt/live/app.example.com/fullchain.pem":
         {"not_after": "2026-11-01T00:00:00+00:00", "days_left": 88}}

DU = {"/root/shop": 800000000}

# Deliberately mismatched case against the "game" app name, to catch a
# one-sided .lower() bug in the override matching.
OVERRIDES = [{"match": "GAME", "dir": "/root/game", "label": "Game Server"}]


def _build():
    return join.build(VHOSTS, DOCKER_DATA, PM2, LISTENERS, PROBE, CERTS, DU, OVERRIDES)


def test_apps_are_assembled_and_sorted():
    apps = _build()["apps"]
    assert [a["name"] for a in apps] == ["cms", "game", "shop"]


def test_compose_app_aggregates_containers():
    shop = [a for a in _build()["apps"] if a["name"] == "shop"][0]
    assert shop["runtime"] == "compose"
    assert shop["mem_bytes"] == 705000000
    assert len(shop["containers"]) == 2
    assert shop["started_at"] == "2026-08-04T18:00:05.000000000Z"
    assert shop["disk_bytes"] == 800000000
    assert [d["domain"] for d in shop["domains"]] == ["app.example.com", "www.app.example.com"]
    assert shop["domains"][0]["cert_days_left"] == 88


def test_pm2_app_matched_via_listener_pid():
    cms = [a for a in _build()["apps"] if a["name"] == "cms"][0]
    assert cms["runtime"] == "pm2"
    assert [d["domain"] for d in cms["domains"]] == ["cms.example.com"]
    assert cms["dir"] == "/var/www/cms"


def test_override_applies_label_and_dir():
    game = [a for a in _build()["apps"] if a["name"] == "game"][0]
    assert game["label"] == "Game Server"
    assert game["dir"] == "/root/game"
    assert game["domains"] == []
    assert game["disk_bytes"] is None


def test_dead_vhost_warning_and_status():
    result = _build()
    dead = [w for w in result["warnings"] if w["kind"] == "dead_vhost"]
    assert len(dead) == 1 and "monitoring.example.com" in dead[0]["message"]
    mon = [v for v in result["vhosts"] if "monitoring.example.com" in v["domains"]][0]
    assert mon["status"] == "dead" and mon["app"] is None


def test_exposed_ports_deduped_and_named():
    exposed = [w for w in _build()["warnings"] if w["kind"] == "exposed_port"]
    messages = " | ".join(w["message"] for w in exposed)
    assert len(exposed) == 2
    assert "65410" in messages and "8055" in messages
    assert "game" in messages
    # Port 8055 is backed by the pm2 process "cms", not its raw listener
    # name "node" - the exposed-port warning must name the same owner the
    # vhost loop does.
    assert "cms" in messages


def test_tls_invalid_warning():
    tls = [w for w in _build()["warnings"] if w["kind"] == "tls_invalid"]
    assert len(tls) == 1 and "cms.example.com" in tls[0]["message"]


def test_static_vhosts_collapse_into_one_app():
    vhosts = [
        {"domains": ["blog.example.com"], "upstream_host": None, "upstream_port": None,
         "static_root": "/var/www/blog", "tls": True, "cert_path": None, "remote": False},
        {"domains": ["blog-alias.example.com"], "upstream_host": None, "upstream_port": None,
         "static_root": "/var/www/blog", "tls": True, "cert_path": None, "remote": False},
    ]
    result = join.build(vhosts, {"containers": [], "projects": {}}, [], [], {}, {}, {}, [])
    static_apps = [a for a in result["apps"] if a["runtime"] == "static"]
    assert len(static_apps) == 1
    assert [d["domain"] for d in static_apps[0]["domains"]] == \
        ["blog.example.com", "blog-alias.example.com"]


def test_dead_vhost_precedence_over_real_container_port_match():
    containers = [
        {"name": "api", "image": "api:latest", "state": "running", "health": None,
         "started_at": "2026-08-04T18:00:00.000000000Z", "compose_project": None,
         "compose_workdir": None,
         "published_ports": [{"host_ip": "127.0.0.1", "host_port": 4000, "container_port": "80/tcp"}],
         "mem_bytes": 1000000},
    ]
    vhosts = [
        {"domains": ["api.example.com"], "upstream_host": "127.0.0.1", "upstream_port": 4000,
         "static_root": None, "tls": True, "cert_path": None, "remote": False},
    ]
    probe = {"domains": {}, "upstreams": {4000: False}}
    result = join.build(vhosts, {"containers": containers, "projects": {}}, [], [], probe, {}, {}, [])

    api_vhost = result["vhosts"][0]
    assert api_vhost["status"] == "dead"
    assert api_vhost["app"] is None

    api_apps = [a for a in result["apps"] if a["name"] == "api"]
    assert len(api_apps) == 1
    assert api_apps[0]["domains"] == []


def test_dead_process_fallback_vhost_does_not_create_phantom_app():
    vhosts = [
        {"domains": ["ghost.example.com"], "upstream_host": "127.0.0.1", "upstream_port": 9100,
         "static_root": None, "tls": True, "cert_path": None, "remote": False},
    ]
    listeners = [{"addr": "0.0.0.0", "port": 9100, "pid": 999, "process": "ghost-proc", "public": True}]
    probe = {"domains": {}, "upstreams": {9100: False}}
    result = join.build(vhosts, {"containers": [], "projects": {}}, [], listeners, probe, {}, {}, [])

    assert not any(a["name"] == "ghost-proc" for a in result["apps"])
    v = result["vhosts"][0]
    assert v["status"] == "dead" and v["app"] is None


def test_tls_invalid_warning_names_only_the_bad_domain_on_multi_domain_vhost():
    vhosts = [
        {"domains": ["good.example.com", "bad.example.com"], "upstream_host": "127.0.0.1",
         "upstream_port": 9000, "static_root": None, "tls": True, "cert_path": None, "remote": False},
    ]
    probe = {
        "domains": {
            "good.example.com": {"scheme": "https", "status_code": 200, "latency_ms": 10,
                                  "ok": True, "tls_valid": True},
            "bad.example.com": {"scheme": "https", "status_code": 200, "latency_ms": 10,
                                 "ok": True, "tls_valid": False},
        },
        "upstreams": {9000: True},
    }
    result = join.build(vhosts, {"containers": [], "projects": {}}, [], [], probe, {}, {}, [])

    tls = [w for w in result["warnings"] if w["kind"] == "tls_invalid"]
    assert len(tls) == 1
    assert "bad.example.com" in tls[0]["message"]
    assert "good.example.com" not in tls[0]["message"]
