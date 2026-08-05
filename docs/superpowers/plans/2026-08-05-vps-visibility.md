# vps-visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the open-source VPS visibility tool from `docs/superpowers/specs/2026-08-05-vps-visibility-design.md`: a stdlib-Python cron collector that joins nginx vhosts to Docker/PM2/bare-process apps, a static HTML dashboard behind basic auth, slim history with sparklines, and Telegram alerts on state transitions.

**Architecture:** Isolated gatherer modules (nginx, docker, pm2, ports, host, certs, probe) each return `{status, data|message}` and never crash the run. A pure `join` module builds the app list. `collect.py` orchestrates: gather, join, write `current.json` + history JSONL to a public data dir, diff against previous state, send Telegram alerts. nginx serves `dashboard/index.html` plus the data dir behind basic auth and TLS.

**Tech Stack:** Python 3.8+ standard library only at runtime. pytest as the only dev dependency. Vanilla HTML/JS/CSS dashboard, no build step, no external assets. bash for `setup.sh`/`uninstall.sh`.

## Global Constraints

- Runtime is Python 3.8 stdlib only: no pip installs, and nothing that needs 3.9+ (`str.removeprefix`, `tomllib`, `zoneinfo` are all off-limits).
- Every subprocess call goes through `collector/util.py:run_command` with a timeout: default 10s, `docker inspect`/`docker stats`/`pm2 jlist` 30s, `du` 120s, HTTP probes 5s, TCP checks 3s.
- Collector cron interval is 300 seconds; history retention default 14 days; thresholds default `disk_pct` 90, `mem_pct` 90, `cert_warn_days` 14.
- Config path `/etc/vps-visibility/config.json`, mode 0600. Data dir default `/var/lib/vps-visibility`; only its `public/` subdirectory is ever served by nginx.
- ASCII hyphens only. Never emit an em dash or en dash in any file, comment, commit message, or doc.
- Comments explain non-obvious "why" only. Never reference tasks, steps, sessions, or "new"/"recent" changes in code, comments, or commit messages.
- Fixtures, sample data, and docs use fictional hosts (`*.example.com`, `/root/shop`); never real customer domains, IPs, or tokens.
- Commit style: conventional commits (`feat:`, `chore:`, `docs:`, `test:`), short subject, no co-author lines.
- Tests run from the repo root with `python3 -m pytest tests/ -v`; the root `conftest.py` puts the repo root on `sys.path`.

## File Structure

```
vps-visibility/
├── conftest.py                      # sys.path bootstrap for pytest
├── .gitignore
├── LICENSE                          # MIT
├── README.md
├── config.example.json
├── collector/
│   ├── __init__.py
│   ├── util.py                      # run_command, parse_size, atomic_write_json, result helpers
│   ├── collect.py                   # entry point: orchestration + config loading
│   ├── join.py                      # pure: vhosts + containers + processes -> apps/vhosts/warnings
│   ├── history.py                   # history JSONL append/prune + hourly du cache
│   ├── alerts.py                    # state diff -> messages; telegram sender
│   └── gatherers/
│       ├── __init__.py
│       ├── nginx.py                 # parse sites-enabled server blocks
│       ├── ports.py                 # ss -tlnp parser
│       ├── docker.py                # docker ps/inspect/stats
│       ├── pm2.py                   # pm2 jlist
│       ├── host.py                  # meminfo, loadavg, df, uptime, public ip
│       ├── certs.py                 # openssl x509 enddate
│       └── probe.py                 # HTTP(S) domain probes + upstream TCP checks
├── dashboard/index.html             # entire UI, single file
├── nginx/vhost.conf.template
├── setup.sh
├── uninstall.sh
├── sample-data/current.json         # fictional data for dev rendering + screenshots
└── tests/
    ├── fixtures/
    │   ├── sites-enabled/multiapp.conf
    │   ├── sites-enabled/static.conf
    │   └── docker_inspect.json
    ├── test_util.py
    ├── test_nginx.py
    ├── test_ports.py
    ├── test_docker.py
    ├── test_pm2.py
    ├── test_host_certs.py
    ├── test_probe.py
    ├── test_join.py
    ├── test_history.py
    ├── test_alerts.py
    └── test_collect.py
```

Key shared data shapes (produced by gatherers, consumed by `join` and `collect`):

```
vhost      {domains: [str], upstream_host: str|None, upstream_port: int|None,
            static_root: str|None, tls: bool, cert_path: str|None, remote: bool}
listener   {addr: str, port: int, pid: int|None, process: str|None, public: bool}
container  {name, image, state, health, started_at, compose_project, compose_workdir,
            published_ports: [{host_ip, host_port, container_port}], mem_bytes}
pm2 proc   {name, pid, status, mem_bytes, restarts, started_at, cwd}
probe      {scheme, status_code, latency_ms, ok}
app        {name, label, runtime: compose|container|pm2|process|static, dir,
            domains: [{domain, scheme, status_code, ok, cert_days_left}],
            mem_bytes, disk_bytes, started_at, containers: [{name, state, health}]}
result     {status: "ok"|"absent"|"error", data?: any, message?: str}
```

---

### Task 1: Repo scaffolding and util helpers

**Files:**
- Create: `.gitignore`, `LICENSE`, `README.md` (stub), `conftest.py`, `collector/__init__.py`, `collector/gatherers/__init__.py`, `collector/util.py`
- Test: `tests/test_util.py`

**Interfaces:**
- Produces: `run_command(cmd: list, timeout: int = 10) -> (int, str)` where rc `-1` means missing binary or timeout; `parse_size(text: str) -> int` (bytes); `atomic_write_json(path: str, obj) -> None`; `ok(data) -> dict`, `absent(message) -> dict`, `error(message) -> dict`. Every later task imports these from `collector.util`.

- [ ] **Step 1: Create scaffolding files**

`.gitignore`:

```
__pycache__/
*.pyc
.pytest_cache/
config.json
/data/
dashboard/data
.DS_Store
```

`LICENSE` (MIT, full standard text):

```
MIT License

Copyright (c) 2026 Gaurav Pandey

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

`README.md` stub (replaced by Task 14):

```markdown
# vps-visibility

One dashboard for a hand-rolled VPS: every nginx vhost mapped to the app
actually serving it (Docker, PM2, or bare process), with per-app memory,
disk, uptime, HTTPS health, cert expiry, and Telegram alerts when
something breaks. Zero runtime dependencies: Python 3 stdlib + one static
HTML page. Full docs land with the first release.
```

`conftest.py`:

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
```

`collector/__init__.py` and `collector/gatherers/__init__.py`: empty files.

- [ ] **Step 2: Write the failing tests**

`tests/test_util.py`:

```python
from collector.util import absent, error, ok, parse_size, run_command


def test_parse_size_units():
    assert parse_size("55.09MiB") == int(55.09 * 1024**2)
    assert parse_size("1.702GiB") == int(1.702 * 1024**3)
    assert parse_size("741MiB") == int(741 * 1024**2)
    assert parse_size("0B") == 0
    assert parse_size("garbage") == 0
    assert parse_size("") == 0


def test_run_command_missing_binary():
    rc, out = run_command(["definitely-not-a-real-binary-xyz"])
    assert rc == -1 and out == ""


def test_run_command_captures_stdout():
    rc, out = run_command(["echo", "hello"])
    assert rc == 0 and out.strip() == "hello"


def test_result_helpers():
    assert ok([1]) == {"status": "ok", "data": [1]}
    assert absent("no pm2") == {"status": "absent", "message": "no pm2"}
    assert error("boom") == {"status": "error", "message": "boom"}


def test_atomic_write_json(tmp_path):
    from collector.util import atomic_write_json
    import json

    target = tmp_path / "out.json"
    atomic_write_json(str(target), {"a": 1})
    assert json.loads(target.read_text()) == {"a": 1}
    assert not (tmp_path / "out.json.tmp").exists()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_util.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'collector.util'`

- [ ] **Step 4: Implement `collector/util.py`**

```python
import json
import os
import re
import subprocess

_UNITS = {"b": 1, "kb": 1000, "kib": 1024, "mb": 1000**2, "mib": 1024**2,
          "gb": 1000**3, "gib": 1024**3, "tb": 1000**4, "tib": 1024**4}


def run_command(cmd, timeout=10):
    """Returns (returncode, stdout). rc -1 means the binary is missing or it timed out."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1, ""


def parse_size(text):
    match = re.match(r"\s*([\d.]+)\s*([a-zA-Z]+)?", text or "")
    if not match:
        return 0
    unit = (match.group(2) or "b").lower()
    return int(float(match.group(1)) * _UNITS.get(unit, 1))


def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)


def ok(data):
    return {"status": "ok", "data": data}


def absent(message):
    return {"status": "absent", "message": message}


def error(message):
    return {"status": "error", "message": message}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_util.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add .gitignore LICENSE README.md conftest.py collector/ tests/
git commit -m "chore: scaffold repo with util helpers"
```

---

### Task 2: nginx vhost parser

**Files:**
- Create: `collector/gatherers/nginx.py`, `tests/fixtures/sites-enabled/multiapp.conf`, `tests/fixtures/sites-enabled/static.conf`
- Test: `tests/test_nginx.py`

**Interfaces:**
- Consumes: `ok/absent/error` from `collector.util`.
- Produces: `gather(sites_dir="/etc/nginx/sites-enabled") -> result` with `data` = list of vhost dicts `{domains, upstream_host, upstream_port, static_root, tls, cert_path, remote}` (shape in File Structure section). Also pure helpers `parse_server_blocks(text) -> [block]` and `merge_blocks(blocks) -> [vhost]` used by tests.

- [ ] **Step 1: Create fixtures**

`tests/fixtures/sites-enabled/multiapp.conf` (models a certbot-managed file: several server blocks in one file, rewritten listen directives, an `if` block with nested braces, separate port-80 redirect blocks for the same names):

```nginx
server {
    server_name app.example.com www.app.example.com;
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    client_max_body_size 20M;
    listen [::]:443 ssl; # managed by Certbot
    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/app.example.com/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/app.example.com/privkey.pem; # managed by Certbot
}
server {
    if ($host = app.example.com) {
        return 301 https://$host$request_uri;
    } # managed by Certbot
    server_name app.example.com www.app.example.com;
    listen 80;
    listen [::]:80;
    return 404; # managed by Certbot
}
server {
    server_name dead.example.com;
    location / {
        proxy_pass http://127.0.0.1:8080;
    }
    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/dead.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dead.example.com/privkey.pem;
}
```

`tests/fixtures/sites-enabled/static.conf`:

```nginx
server {
    listen 80;
    server_name docs.example.com;
    root /var/www/docs;
    index index.html;
}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_nginx.py`:

```python
import os

from collector.gatherers import nginx

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "sites-enabled")


def _by_domain(vhosts, domain):
    return next(v for v in vhosts if domain in v["domains"])


def test_gather_parses_fixture_dir():
    result = nginx.gather(FIXTURES)
    assert result["status"] == "ok"
    assert len(result["data"]) == 3


def test_certbot_blocks_merge_into_one_vhost():
    v = _by_domain(nginx.gather(FIXTURES)["data"], "app.example.com")
    assert v["domains"] == ["app.example.com", "www.app.example.com"]
    assert v["upstream_port"] == 3000
    assert v["upstream_host"] == "127.0.0.1"
    assert v["tls"] is True
    assert v["cert_path"] == "/etc/letsencrypt/live/app.example.com/fullchain.pem"
    assert v["remote"] is False


def test_dead_upstream_vhost_still_parses():
    v = _by_domain(nginx.gather(FIXTURES)["data"], "dead.example.com")
    assert v["upstream_port"] == 8080
    assert v["tls"] is True


def test_static_root_vhost():
    v = _by_domain(nginx.gather(FIXTURES)["data"], "docs.example.com")
    assert v["upstream_port"] is None
    assert v["static_root"] == "/var/www/docs"
    assert v["tls"] is False


def test_remote_upstream_flagged():
    blocks = nginx.parse_server_blocks(
        "server { server_name r.example.com; listen 80;"
        " location / { proxy_pass http://10.0.0.9:9000; } }"
    )
    v = nginx.merge_blocks(blocks)[0]
    assert v["remote"] is True and v["upstream_port"] == 9000


def test_missing_dir_reports_absent():
    assert nginx.gather("/nonexistent/path")["status"] == "absent"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_nginx.py -v`
Expected: FAIL with `ImportError` (module does not exist)

- [ ] **Step 4: Implement `collector/gatherers/nginx.py`**

```python
import glob
import os
import re

from collector.util import absent, error, ok

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def gather(sites_dir="/etc/nginx/sites-enabled"):
    if not os.path.isdir(sites_dir):
        return absent("no nginx sites-enabled directory")
    try:
        blocks = []
        for path in sorted(glob.glob(os.path.join(sites_dir, "*"))):
            if os.path.isfile(path):
                with open(path, errors="replace") as f:
                    blocks.extend(parse_server_blocks(f.read()))
        return ok(merge_blocks(blocks))
    except Exception as e:
        return error("nginx parse failed: %s" % e)


def parse_server_blocks(text):
    text = re.sub(r"#[^\n]*", "", text)
    out = []
    for m in re.finditer(r"\bserver\s*\{", text):
        depth, j = 1, m.end()
        while j < len(text) and depth:
            depth += (text[j] == "{") - (text[j] == "}")
            j += 1
        out.append(_parse_block(text[m.end():j - 1]))
    return [b for b in out if b["domains"]]


def _parse_block(body):
    names = re.search(r"\bserver_name\s+([^;]+);", body)
    domains = sorted(set(names.group(1).split())) if names else []
    domains = [d for d in domains if d != "_"]

    ssl = False
    for lm in re.finditer(r"\blisten\s+([^;]+);", body):
        ssl = ssl or (" ssl" in " " + lm.group(1))

    upstream_host = upstream_port = None
    pp = re.search(r"\bproxy_pass\s+https?://([^;/\s]+)", body)
    if pp:
        target = pp.group(1)
        if ":" in target.strip("[]"):
            host, _, port = target.rpartition(":")
            upstream_host = host.strip("[]")
            upstream_port = int(port) if port.isdigit() else None
        else:
            upstream_host, upstream_port = target, 80

    root = re.search(r"\broot\s+([^;]+);", body)
    cert = re.search(r"\bssl_certificate\s+([^;]+);", body)
    return {
        "domains": domains,
        "ssl": ssl,
        "upstream_host": upstream_host,
        "upstream_port": upstream_port,
        "static_root": root.group(1).strip() if root else None,
        "cert_path": cert.group(1).strip() if cert else None,
    }


def merge_blocks(blocks):
    merged = {}
    for b in blocks:
        v = merged.setdefault(tuple(b["domains"]), {
            "domains": b["domains"], "upstream_host": None, "upstream_port": None,
            "static_root": None, "tls": False, "cert_path": None,
        })
        v["tls"] = v["tls"] or b["ssl"]
        for field in ("upstream_host", "upstream_port", "static_root", "cert_path"):
            if v[field] is None and b[field] is not None:
                v[field] = b[field]
    result = []
    for v in merged.values():
        v["remote"] = bool(v["upstream_host"]) and v["upstream_host"] not in LOCAL_HOSTS
        result.append(v)
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_nginx.py -v`
Expected: 6 PASS

- [ ] **Step 6: Commit**

```bash
git add collector/gatherers/nginx.py tests/test_nginx.py tests/fixtures/
git commit -m "feat: nginx vhost parser"
```

---

### Task 3: Listening ports gatherer

**Files:**
- Create: `collector/gatherers/ports.py`
- Test: `tests/test_ports.py`

**Interfaces:**
- Consumes: `run_command`, `ok`, `error` from `collector.util`.
- Produces: `gather(runner=run_command) -> result` with `data` = list of listener dicts `{addr, port, pid, process, public}`. Pure helper `parse_ss(text) -> [listener]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_ports.py`:

```python
from collector.gatherers.ports import parse_ss

SS = """LISTEN 0 4096 127.0.0.1:3000 0.0.0.0:* users:(("docker-proxy",pid=1111,fd=8))
LISTEN 0 511 0.0.0.0:8055 0.0.0.0:* users:(("node",pid=2222,fd=21))
LISTEN 0 4096 [::]:80 [::]:* users:(("nginx",pid=3333,fd=8),("nginx",pid=3334,fd=8))
LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=44,fd=3))
LISTEN 0 128 127.0.0.53%lo:53 0.0.0.0:* users:(("systemd-resolve",pid=99,fd=15))"""


def test_parse_ss_extracts_listeners():
    listeners = parse_ss(SS)
    assert listeners[0] == {"addr": "127.0.0.1", "port": 3000, "pid": 1111,
                            "process": "docker-proxy", "public": False}
    assert len(listeners) == 5


def test_public_detection():
    flags = [(l["port"], l["public"]) for l in parse_ss(SS)]
    assert (8055, True) in flags and (3000, False) in flags and (80, True) in flags


def test_first_pid_wins_on_multi_process_socket():
    l = [x for x in parse_ss(SS) if x["port"] == 80][0]
    assert l["process"] == "nginx" and l["pid"] == 3333


def test_scoped_address_is_not_public():
    l = [x for x in parse_ss(SS) if x["port"] == 53][0]
    assert l["public"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_ports.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `collector/gatherers/ports.py`**

```python
import re

from collector.util import error, ok, run_command


def gather(runner=run_command):
    rc, out = runner(["ss", "-Htlnp"])
    if rc != 0:
        return error("ss failed (rc=%s)" % rc)
    return ok(parse_ss(out))


def parse_ss(text):
    listeners = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        addr, _, port = parts[3].rpartition(":")
        if not port.isdigit():
            continue
        addr = addr.strip("[]").split("%")[0]
        m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        listeners.append({
            "addr": addr,
            "port": int(port),
            "pid": int(m.group(2)) if m else None,
            "process": m.group(1) if m else None,
            "public": addr in ("0.0.0.0", "::", "*"),
        })
    return listeners
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_ports.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add collector/gatherers/ports.py tests/test_ports.py
git commit -m "feat: listening ports gatherer"
```

---

### Task 4: Docker gatherer

**Files:**
- Create: `collector/gatherers/docker.py`, `tests/fixtures/docker_inspect.json`
- Test: `tests/test_docker.py`

**Interfaces:**
- Consumes: `run_command`, `parse_size`, `ok`, `absent`, `error` from `collector.util`.
- Produces: `gather(runner=run_command) -> result` with `data` = `{"containers": [container], "projects": {name: {"working_dir": str|None}}}` (container shape in File Structure section).

- [ ] **Step 1: Create fixture**

`tests/fixtures/docker_inspect.json`:

```json
[
  {
    "Name": "/shop-web-1",
    "Created": "2026-08-01T10:00:00.000000000Z",
    "State": {"Status": "running", "StartedAt": "2026-08-04T18:00:00.000000000Z"},
    "Config": {"Image": "shop-web", "Labels": {"com.docker.compose.project": "shop", "com.docker.compose.project.working_dir": "/root/shop"}},
    "NetworkSettings": {"Ports": {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "3000"}]}}
  },
  {
    "Name": "/shop-backend-1",
    "Created": "2026-08-01T10:00:00.000000000Z",
    "State": {"Status": "running", "StartedAt": "2026-08-04T18:00:05.000000000Z", "Health": {"Status": "healthy"}},
    "Config": {"Image": "shop-backend", "Labels": {"com.docker.compose.project": "shop", "com.docker.compose.project.working_dir": "/root/shop"}},
    "NetworkSettings": {"Ports": {"8000/tcp": null}}
  },
  {
    "Name": "/game",
    "Created": "2026-06-15T08:00:00.000000000Z",
    "State": {"Status": "running", "StartedAt": "2026-06-15T08:00:00.000000000Z"},
    "Config": {"Image": "game:latest", "Labels": {}},
    "NetworkSettings": {"Ports": {"65410/tcp": [{"HostIp": "0.0.0.0", "HostPort": "65410"}]}}
  }
]
```

- [ ] **Step 2: Write the failing tests**

`tests/test_docker.py`:

```python
import os

from collector.gatherers import docker

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fake_runner(cmd, timeout=10):
    if cmd[:2] == ["docker", "ps"]:
        return 0, "aaa\nbbb\nccc\n"
    if cmd[:2] == ["docker", "inspect"]:
        with open(os.path.join(FIXTURES, "docker_inspect.json")) as f:
            return 0, f.read()
    if cmd[:2] == ["docker", "stats"]:
        return 0, ("shop-web-1\t5.4MiB / 15.62GiB\n"
                   "shop-backend-1\t741MiB / 15.62GiB\n"
                   "game\t1.702GiB / 15.62GiB\n")
    raise AssertionError("unexpected command %s" % cmd)


def test_gather_builds_containers_and_projects():
    data = docker.gather(fake_runner)["data"]
    assert len(data["containers"]) == 3
    assert data["projects"] == {"shop": {"working_dir": "/root/shop"}}


def test_container_fields():
    containers = docker.gather(fake_runner)["data"]["containers"]
    web = next(c for c in containers if c["name"] == "shop-web-1")
    assert web["published_ports"] == [{"host_ip": "127.0.0.1", "host_port": 3000,
                                       "container_port": "80/tcp"}]
    assert web["mem_bytes"] == int(5.4 * 1024**2)
    assert web["health"] is None
    backend = next(c for c in containers if c["name"] == "shop-backend-1")
    assert backend["health"] == "healthy"
    assert backend["published_ports"] == []


def test_docker_missing_reports_absent():
    assert docker.gather(lambda cmd, timeout=10: (-1, ""))["status"] == "absent"


def test_no_containers():
    def runner(cmd, timeout=10):
        return 0, ""
    assert docker.gather(runner)["data"] == {"containers": [], "projects": {}}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_docker.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 4: Implement `collector/gatherers/docker.py`**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_docker.py -v`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add collector/gatherers/docker.py tests/test_docker.py tests/fixtures/docker_inspect.json
git commit -m "feat: docker gatherer"
```

---

### Task 5: PM2 gatherer

**Files:**
- Create: `collector/gatherers/pm2.py`
- Test: `tests/test_pm2.py`

**Interfaces:**
- Consumes: `run_command`, `ok`, `absent`, `error` from `collector.util`.
- Produces: `gather(runner=run_command) -> result` with `data` = list of `{name, pid, status, mem_bytes, restarts, started_at, cwd}`. `started_at` is an ISO-8601 UTC string derived from pm2's `pm_uptime` epoch milliseconds.

- [ ] **Step 1: Write the failing tests**

`tests/test_pm2.py`:

```python
import json

from collector.gatherers import pm2

JLIST = json.dumps([{
    "name": "cms",
    "pid": 2222,
    "monit": {"memory": 190000000},
    "pm2_env": {"status": "online", "restart_time": 3,
                "pm_uptime": 1754300000000, "pm_cwd": "/var/www/cms"},
}])


def test_gather_parses_processes():
    procs = pm2.gather(lambda cmd, timeout=30: (0, JLIST))["data"]
    assert procs == [{
        "name": "cms", "pid": 2222, "status": "online", "mem_bytes": 190000000,
        "restarts": 3, "started_at": "2025-08-04T09:33:20+00:00", "cwd": "/var/www/cms",
    }]


def test_leading_noise_before_json_is_skipped():
    out = "some pm2 banner\n" + JLIST
    assert pm2.gather(lambda cmd, timeout=30: (0, out))["status"] == "ok"


def test_pm2_missing_reports_absent():
    assert pm2.gather(lambda cmd, timeout=30: (-1, ""))["status"] == "absent"


def test_no_json_reports_error():
    assert pm2.gather(lambda cmd, timeout=30: (0, "garbage"))["status"] == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pm2.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `collector/gatherers/pm2.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pm2.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add collector/gatherers/pm2.py tests/test_pm2.py
git commit -m "feat: pm2 gatherer"
```

---

### Task 6: Host and cert gatherers

**Files:**
- Create: `collector/gatherers/host.py`, `collector/gatherers/certs.py`
- Test: `tests/test_host_certs.py`

**Interfaces:**
- Consumes: `run_command`, `ok`, `error` from `collector.util`.
- Produces: `host.gather(config, runner=run_command) -> result` with `data` = `{hostname, public_ip, uptime_seconds, load: [f,f,f], mem: {total_bytes, used_bytes}, filesystems: [{mount, total_bytes, used_bytes, pct}]}`. Pure helpers `host.parse_meminfo(text)`, `host.parse_df(text)`.
- Produces: `certs.gather(cert_paths: [str], now_ts: int, runner=run_command) -> result` with `data` = `{path: {not_after: iso, days_left: int}}`. Pure helper `certs.parse_enddate(text, now_ts)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_host_certs.py`:

```python
from collector.gatherers import certs, host

MEMINFO = """MemTotal:       16000000 kB
MemFree:         1000000 kB
MemAvailable:   10000000 kB
Buffers:          500000 kB
"""

DF = """Filesystem     1024-blocks      Used Available Capacity Mounted on
/dev/sda1        202000000 155000000  38000000      81% /
"""


def test_parse_meminfo():
    mem = host.parse_meminfo(MEMINFO)
    assert mem["total_bytes"] == 16000000 * 1024
    assert mem["used_bytes"] == (16000000 - 10000000) * 1024


def test_parse_df():
    fs = host.parse_df(DF)
    assert fs == [{"mount": "/", "total_bytes": 202000000 * 1024,
                   "used_bytes": 155000000 * 1024, "pct": 76.7}]


def test_parse_enddate():
    now_ts = 1754300000
    info = certs.parse_enddate("notAfter=Aug  5 12:34:56 2026 GMT", now_ts)
    assert info["not_after"].startswith("2026-08-05T12:34:56")
    assert info["days_left"] == 366


def test_certs_gather_skips_unreadable_paths():
    def runner(cmd, timeout=10):
        return 1, ""
    assert certs.gather(["/nope.pem"], 1754300000, runner)["data"] == {}
```

Note on `test_parse_df`: `pct` is computed from used/total bytes, not read from the Capacity column, so the fixture's 81% column is intentionally ignored (155/202 rounds to 76.7).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_host_certs.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `collector/gatherers/host.py`**

```python
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
```

- [ ] **Step 4: Implement `collector/gatherers/certs.py`**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_host_certs.py -v`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add collector/gatherers/host.py collector/gatherers/certs.py tests/test_host_certs.py
git commit -m "feat: host and cert gatherers"
```

---

### Task 7: Domain and upstream prober

**Files:**
- Create: `collector/gatherers/probe.py`
- Test: `tests/test_probe.py`

**Interfaces:**
- Consumes: vhost dicts from Task 2; `ok` from `collector.util`.
- Produces: `gather(vhosts, via="localhost") -> result` with `data` = `{"domains": {domain: probe}, "upstreams": {port: bool}}` where probe = `{scheme, status_code, latency_ms, ok, tls_valid}`. `ok` is true when a response arrived with status < 500 (401/403 mean the app is up and guarding itself). `tls_valid` is `True` when the certificate verified against the system CA store, `False` when verification failed (probe then retries unverified so `status_code` still reflects app health), `None` for plain HTTP. Helpers `probe_domain(domain, tls, via, timeout=5)`, `parse_status_line(data: bytes) -> int|None`, `check_tcp(port, timeout=3) -> bool`.
- Note: `via="localhost"` connects to 127.0.0.1:443/80 with SNI and Host set to the domain, so probes work before public DNS exists and never depend on the outside network. TLS verification stays ON by default; the unverified retry happens only after `SSLCertVerificationError`, and its result is always marked `tls_valid: False` so a bad cert is surfaced, never hidden. Remote-upstream vhosts (`remote: true`) are skipped in `upstreams`.

- [ ] **Step 1: Write the failing tests**

`tests/test_probe.py`:

```python
import socket
import threading

from collector.gatherers.probe import check_tcp, parse_status_line


def test_parse_status_line():
    assert parse_status_line(b"HTTP/1.1 200 OK\r\n") == 200
    assert parse_status_line(b"HTTP/1.0 502 Bad Gateway\r\n") == 502
    assert parse_status_line(b"HTTP/2 401\r\n") == 401
    assert parse_status_line(b"not http") is None
    assert parse_status_line(b"") is None
    assert parse_status_line(None) is None


def test_check_tcp_open_and_closed():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    accepter = threading.Thread(target=lambda: server.accept(), daemon=True)
    accepter.start()
    try:
        assert check_tcp(port) is True
    finally:
        server.close()
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    free_port = closed.getsockname()[1]
    closed.close()
    assert check_tcp(free_port) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_probe.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `collector/gatherers/probe.py`**

```python
import re
import socket
import ssl
import time

from collector.util import ok


def gather(vhosts, via="localhost"):
    domains, upstreams = {}, {}
    for v in vhosts:
        for d in v["domains"]:
            r = probe_domain(d, v["tls"], via)
            if v["tls"] and r["status_code"] is None:
                fallback = probe_domain(d, False, via)
                if fallback["status_code"] is not None:
                    r = fallback
            domains[d] = r
        port = v.get("upstream_port")
        if port and not v.get("remote") and port not in upstreams:
            upstreams[port] = check_tcp(port)
    return ok({"domains": domains, "upstreams": upstreams})


def probe_domain(domain, tls, via="localhost", timeout=5):
    host = "127.0.0.1" if via == "localhost" else domain
    start = time.monotonic()
    code, tls_valid = None, None
    try:
        code = _request(domain, host, tls, True, timeout)
        tls_valid = True if tls else None
    except ssl.SSLCertVerificationError:
        # Bad or mismatched cert: record it, but still learn whether the app answers.
        tls_valid = False
        try:
            code = _request(domain, host, tls, False, timeout)
        except OSError:
            pass
    except OSError:
        pass
    return {
        "scheme": "https" if tls else "http",
        "status_code": code,
        "latency_ms": int((time.monotonic() - start) * 1000),
        "ok": code is not None and code < 500,
        "tls_valid": tls_valid,
    }


def _request(domain, host, tls, verify, timeout):
    sock = socket.create_connection((host, 443 if tls else 80), timeout)
    try:
        if tls:
            ctx = ssl.create_default_context()
            if not verify:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            sock = ctx.wrap_socket(sock, server_hostname=domain)
        sock.settimeout(timeout)
        request = ("GET / HTTP/1.1\r\nHost: %s\r\nUser-Agent: vps-visibility\r\n"
                   "Connection: close\r\n\r\n" % domain)
        sock.sendall(request.encode())
        return parse_status_line(sock.recv(1024))
    finally:
        try:
            sock.close()
        except OSError:
            pass


def parse_status_line(data):
    m = re.match(rb"HTTP/[\d.]+\s+(\d{3})", data or b"")
    return int(m.group(1)) if m else None


def check_tcp(port, timeout=3):
    try:
        socket.create_connection(("127.0.0.1", port), timeout).close()
        return True
    except OSError:
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_probe.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add collector/gatherers/probe.py tests/test_probe.py
git commit -m "feat: domain and upstream prober"
```

---

### Task 8: Join module

**Files:**
- Create: `collector/join.py`
- Test: `tests/test_join.py`

**Interfaces:**
- Consumes: vhost dicts (Task 2), docker data (Task 4), pm2 procs (Task 5), listeners (Task 3), probe data (Task 7), cert info (Task 6).
- Produces: `build(vhosts, docker_data, pm2_procs, listeners, probe_data, cert_info, du_cache, overrides) -> {"apps": [app], "vhosts": [vhost_out], "warnings": [warning]}`. Pure function, no subprocess or filesystem access. `vhost_out` = `{domains, upstream_port, static_root, tls, app: str|None, status: "ok"|"dead"|"static"|"remote"}`. `warning` = `{kind, message}` with kinds `dead_vhost`, `exposed_port`, `tls_invalid`. `du_cache` maps directory -> bytes; `overrides` is the config `app_overrides` list with exact case-insensitive `match` on app name.

- [ ] **Step 1: Write the failing tests**

`tests/test_join.py`:

```python
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

OVERRIDES = [{"match": "game", "dir": "/root/game", "label": "Game Server"}]


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


def test_tls_invalid_warning():
    tls = [w for w in _build()["warnings"] if w["kind"] == "tls_invalid"]
    assert len(tls) == 1 and "cms.example.com" in tls[0]["message"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_join.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `collector/join.py`**

```python
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
            if c:
                app_key = container_key(c)
            elif listener and listener["pid"] in pm2_by_pid:
                app_key = "pm2:" + pm2_by_pid[listener["pid"]]["name"]
            elif listener:
                name = listener["process"] or "unknown"
                app_key = "process:" + name
                apps.setdefault(app_key, _new_app(name, "process", None))
            if probe_data.get("upstreams", {}).get(port) is False:
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

        if app_key and app_key in apps:
            app = apps[app_key]
            for d in v["domains"]:
                pr = probe_data.get("domains", {}).get(d, {})
                cert = cert_info.get(v.get("cert_path") or "", {})
                app["domains"].append({
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
            owner = port_to_container.get(l["port"])
            who = owner["name"] if owner else (l["process"] or "unknown")
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


def _new_app(name, runtime, directory):
    return {"name": name, "label": name, "runtime": runtime, "dir": directory,
            "domains": [], "mem_bytes": 0, "disk_bytes": None, "started_at": None,
            "containers": []}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_join.py -v`
Expected: 7 PASS

- [ ] **Step 5: Run the whole suite**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add collector/join.py tests/test_join.py
git commit -m "feat: join vhosts, containers and processes into apps"
```

---

### Task 9: History and du cache

**Files:**
- Create: `collector/history.py`
- Test: `tests/test_history.py`

**Interfaces:**
- Consumes: the `current` dict shape written by `collect.py` (needs `current["host"]` and `current["apps"]`); `run_command` signature for injection.
- Produces: `append_record(public_dir, current, now_ts)` (appends one JSONL line `{ts, mem_pct, disk: {mount: pct}, apps: {name: [mem_bytes, disk_bytes, ok01]}}` to `history/YYYY-MM-DD.jsonl`); `prune(public_dir, retention_days, now_ts)`; `refresh_du(apps, state, now_ts, runner) -> {dir: bytes}` which reuses `state["du_cache"]` unless `state["du_ts"]` is older than 3600 seconds, and mutates both keys when it rescans.

- [ ] **Step 1: Write the failing tests**

`tests/test_history.py`:

```python
import json
import time

from collector import history

CURRENT = {
    "host": {"mem": {"total_bytes": 100, "used_bytes": 40},
             "filesystems": [{"mount": "/", "total_bytes": 200, "used_bytes": 162, "pct": 81.0}]},
    "apps": [{"name": "shop", "mem_bytes": 705000000, "disk_bytes": 800000000,
              "domains": [{"domain": "app.example.com", "ok": True}]},
             {"name": "game", "mem_bytes": 1800000000, "disk_bytes": None, "domains": []}],
}


def test_append_record(tmp_path):
    (tmp_path / "history").mkdir()
    now = 1754300000
    history.append_record(str(tmp_path), CURRENT, now)
    history.append_record(str(tmp_path), CURRENT, now + 300)
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    lines = (tmp_path / "history" / (day + ".jsonl")).read_text().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["mem_pct"] == 40.0
    assert rec["disk"] == {"/": 81.0}
    assert rec["apps"]["shop"] == [705000000, 800000000, 1]
    assert rec["apps"]["game"] == [1800000000, 0, 1]


def test_prune_removes_old_files(tmp_path):
    hist = tmp_path / "history"
    hist.mkdir()
    (hist / "2020-01-01.jsonl").write_text("{}\n")
    now = 1754300000
    fresh = time.strftime("%Y-%m-%d", time.gmtime(now)) + ".jsonl"
    (hist / fresh).write_text("{}\n")
    history.prune(str(tmp_path), 14, now)
    assert not (hist / "2020-01-01.jsonl").exists()
    assert (hist / fresh).exists()


def test_refresh_du_scans_then_respects_hourly_gate(tmp_path):
    app = {"name": "shop", "dir": str(tmp_path)}
    calls = []

    def runner(cmd, timeout=120):
        calls.append(cmd)
        return 0, "12345\t%s\n" % tmp_path

    state = {}
    cache = history.refresh_du([app], state, 1000000, runner)
    assert cache == {str(tmp_path): 12345}
    assert state["du_ts"] == 1000000
    cache2 = history.refresh_du([app], state, 1000300, runner)
    assert cache2 == cache and len(calls) == 1
    history.refresh_du([app], state, 1000000 + 3600, runner)
    assert len(calls) == 2


def test_refresh_du_skips_missing_dirs(tmp_path):
    app = {"name": "x", "dir": str(tmp_path / "nope")}
    cache = history.refresh_du([app], {}, 1000000, lambda cmd, timeout=120: (0, "1\t/x\n"))
    assert cache == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_history.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `collector/history.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_history.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add collector/history.py tests/test_history.py
git commit -m "feat: history records and du cache"
```

---

### Task 10: Alerts

**Files:**
- Create: `collector/alerts.py`
- Test: `tests/test_alerts.py`

**Interfaces:**
- Consumes: `current` dict (needs `apps`, `host`, `certs`, `gatherers` keys) and config `thresholds`.
- Produces: `compute(prev, current, config, now_ts) -> (messages: [str], state: dict)` where `prev` is the state dict returned by the previous call (empty dict on first run). State shape: `{"domains": {domain: {"ok": bool, "fails": int}}, "apps": {name: {"started_at": str|None}}, "breaches": {key: bool}, "cert_sent": {path: ts}, "gerrs": {name: msg}}`. Also `send_telegram(token, chat_id, text, timeout=10) -> bool`.
- Alert rules: DOWN only after 2 consecutive failing runs; RECOVERED when a reported-down domain probes ok; RESTARTED when a container/pm2 app's `started_at` moves forward; GONE when a previously seen container/pm2 app vanishes; THRESHOLD once per upward crossing of disk/mem percent; CERT at most once per 3 days per cert while within `cert_warn_days`; COLLECTOR once when a gatherer newly reports `error`.

- [ ] **Step 1: Write the failing tests**

`tests/test_alerts.py`:

```python
from collector import alerts

CONFIG = {"thresholds": {"disk_pct": 90, "mem_pct": 90, "cert_warn_days": 14}}


def make_current(dom_ok=True, status=200, disk_pct=50.0, mem_used=50,
                 started="2026-08-04T18:00:05Z", certs=None, gatherers=None):
    return {
        "apps": [{"name": "shop", "runtime": "compose", "started_at": started,
                  "mem_bytes": 0, "disk_bytes": None, "containers": [], "dir": None,
                  "label": "shop",
                  "domains": [{"domain": "app.example.com", "scheme": "https",
                               "status_code": status, "ok": dom_ok,
                               "tls_valid": True, "cert_days_left": None}]}],
        "host": {"filesystems": [{"mount": "/", "pct": disk_pct}],
                 "mem": {"total_bytes": 100, "used_bytes": mem_used}},
        "certs": certs or {},
        "gatherers": gatherers or {"nginx": {"status": "ok"}},
    }


def test_first_failure_does_not_alert():
    msgs, state = alerts.compute({}, make_current(dom_ok=False, status=502), CONFIG, 1000)
    assert msgs == []
    assert state["domains"]["app.example.com"] == {"ok": True, "fails": 1}


def test_second_failure_alerts_down_once():
    _, state = alerts.compute({}, make_current(dom_ok=False, status=502), CONFIG, 1000)
    msgs, state = alerts.compute(state, make_current(dom_ok=False, status=502), CONFIG, 1300)
    assert any(m.startswith("DOWN") and "app.example.com" in m for m in msgs)
    msgs, _ = alerts.compute(state, make_current(dom_ok=False, status=502), CONFIG, 1600)
    assert msgs == []


def test_recovery_alerts_once():
    state = {"domains": {"app.example.com": {"ok": False, "fails": 5}}}
    msgs, state = alerts.compute(state, make_current(dom_ok=True), CONFIG, 2000)
    assert any(m.startswith("RECOVERED") for m in msgs)
    msgs, _ = alerts.compute(state, make_current(dom_ok=True), CONFIG, 2300)
    assert msgs == []


def test_restart_detected():
    _, state = alerts.compute({}, make_current(started="2026-08-04T18:00:05Z"), CONFIG, 1000)
    msgs, _ = alerts.compute(state, make_current(started="2026-08-05T09:00:00Z"), CONFIG, 1300)
    assert any(m.startswith("RESTARTED") and "shop" in m for m in msgs)


def test_gone_app_detected():
    state = {"apps": {"shop": {"started_at": "x"}, "old-app": {"started_at": "y"}}}
    msgs, new_state = alerts.compute(state, make_current(), CONFIG, 1000)
    assert any(m.startswith("GONE") and "old-app" in m for m in msgs)
    assert "old-app" not in new_state["apps"]


def test_threshold_fires_on_crossing_only():
    msgs, state = alerts.compute({}, make_current(disk_pct=92.0), CONFIG, 1000)
    assert any("Disk" in m for m in msgs)
    msgs, state = alerts.compute(state, make_current(disk_pct=93.0), CONFIG, 1300)
    assert msgs == []
    msgs, state = alerts.compute(state, make_current(disk_pct=85.0), CONFIG, 1600)
    assert msgs == []
    msgs, _ = alerts.compute(state, make_current(disk_pct=95.0), CONFIG, 1900)
    assert any("Disk" in m for m in msgs)


def test_cert_alert_gated_to_three_days():
    certs = {"/etc/letsencrypt/live/a/fullchain.pem": {"not_after": "x", "days_left": 10}}
    msgs, state = alerts.compute({}, make_current(certs=certs), CONFIG, 1000)
    assert any(m.startswith("CERT") for m in msgs)
    msgs, state = alerts.compute(state, make_current(certs=certs), CONFIG, 1000 + 86400)
    assert msgs == []
    msgs, _ = alerts.compute(state, make_current(certs=certs), CONFIG, 1000 + 4 * 86400)
    assert any(m.startswith("CERT") for m in msgs)


def test_gatherer_error_alerts_on_transition():
    bad = {"nginx": {"status": "error", "message": "boom"}}
    msgs, state = alerts.compute({}, make_current(gatherers=bad), CONFIG, 1000)
    assert any(m.startswith("COLLECTOR") for m in msgs)
    msgs, _ = alerts.compute(state, make_current(gatherers=bad), CONFIG, 1300)
    assert msgs == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_alerts.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `collector/alerts.py`**

```python
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
            if now_ts - state["cert_sent"].get(path, 0) >= 3 * 86400:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_alerts.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add collector/alerts.py tests/test_alerts.py
git commit -m "feat: alert computation and telegram sender"
```

---

### Task 11: Collector entry point and config

**Files:**
- Create: `collector/collect.py`, `config.example.json`
- Test: `tests/test_collect.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `load_config(path) -> dict` (user JSON deep-merged over `DEFAULTS`, one level for nested dicts) and `main() -> int` (0 on success; 1 only for unreadable config). Writes `<data_dir>/public/current.json`, `<data_dir>/public/history/*.jsonl`, `<data_dir>/state.json`. `current.json` top-level keys: `schema_version, generated_at, interval_seconds, host, apps, vhosts, certs, warnings, gatherers, telegram_error` (gatherer entries stripped of `data`; `telegram_error` carries the previous run's send failure, if any). The dashboard (Task 12) reads exactly this shape.

- [ ] **Step 1: Write the failing tests**

`tests/test_collect.py`:

```python
import json

from collector import collect


def test_load_config_merges_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"dashboard_domain": "vps.example.com",
                             "thresholds": {"disk_pct": 80}}))
    cfg = collect.load_config(str(p))
    assert cfg["dashboard_domain"] == "vps.example.com"
    assert cfg["thresholds"]["disk_pct"] == 80
    assert cfg["thresholds"]["mem_pct"] == 90
    assert cfg["retention_days"] == 14
    assert cfg["probe_via"] == "localhost"


def test_load_config_missing_file_raises(tmp_path):
    try:
        collect.load_config(str(tmp_path / "nope.json"))
        assert False, "expected OSError"
    except OSError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_collect.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement `collector/collect.py`**

```python
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


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/etc/vps-visibility/config.json"
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
    if msgs and telegram.get("bot_token") and telegram.get("chat_id"):
        sent = alerts.send_telegram(telegram["bot_token"], telegram["chat_id"], "\n".join(msgs))
        state["telegram_error"] = None if sent else "send failed at %s" % now
    state["alert"] = alert_state
    atomic_write_json(state_path, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Create `config.example.json`**

```json
{
  "schema_version": 1,
  "dashboard_domain": "vps.example.com",
  "data_dir": "/var/lib/vps-visibility",
  "retention_days": 14,
  "probe_via": "localhost",
  "public_ip": null,
  "filesystems": ["/"],
  "thresholds": {"disk_pct": 90, "mem_pct": 90, "cert_warn_days": 14},
  "telegram": {"bot_token": null, "chat_id": null},
  "app_overrides": [
    {"match": "myapp", "dir": "/opt/myapp", "label": "My App"}
  ]
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS (the two new tests plus every earlier suite)

- [ ] **Step 6: Smoke-run the collector locally**

Run (macOS dev machine: nginx/ss/pm2 absent is expected and must not crash):

```bash
mkdir -p /tmp/vv-smoke
printf '{"data_dir": "/tmp/vv-smoke"}' > /tmp/vv-smoke/config.json
python3 collector/collect.py /tmp/vv-smoke/config.json
python3 -c "import json; d = json.load(open('/tmp/vv-smoke/public/current.json')); print(sorted(d), d['gatherers'])"
```

Expected: exit 0; `current.json` exists with all ten top-level keys; `nginx`/`ports` gatherers report `absent` or `error` without crashing the run.

- [ ] **Step 7: Commit**

```bash
git add collector/collect.py config.example.json tests/test_collect.py
git commit -m "feat: collector entry point and config loading"
```

---

### Task 12: Dashboard page and sample data

**Files:**
- Create: `dashboard/index.html`, `sample-data/current.json`

**Interfaces:**
- Consumes: `current.json` shape from Task 11 via relative path `data/current.json`, plus `data/history/YYYY-MM-DD.jsonl` (last 7 UTC days, 404s tolerated).
- Produces: the complete UI. No framework, no build, no external assets. Light/dark from the same tokens under both `prefers-color-scheme` and a `data-theme` override. Sparklines are single-series 2px lines in the accent slot with hover tooltips; status colors (good/warning/serious/critical) always pair a colored dot with a text label, never color alone.

- [ ] **Step 1: Create `sample-data/current.json`** (fictional box used for dev rendering and README screenshots)

```json
{
  "schema_version": 1,
  "generated_at": "2026-08-05T09:00:00+00:00",
  "interval_seconds": 300,
  "host": {
    "hostname": "vps-1",
    "public_ip": "203.0.113.10",
    "uptime_seconds": 5443200,
    "load": [0.42, 0.51, 0.48],
    "mem": {"total_bytes": 16777216000, "used_bytes": 6442450944},
    "filesystems": [{"mount": "/", "total_bytes": 206158430208, "used_bytes": 166429982720, "pct": 80.7}]
  },
  "apps": [
    {"name": "shop", "label": "shop", "runtime": "compose", "dir": "/root/shop",
     "domains": [
       {"domain": "app.example.com", "scheme": "https", "status_code": 200, "ok": true, "tls_valid": true, "cert_days_left": 88},
       {"domain": "www.app.example.com", "scheme": "https", "status_code": 200, "ok": true, "tls_valid": true, "cert_days_left": 88}],
     "mem_bytes": 705000000, "disk_bytes": 800000000, "started_at": "2026-08-04T18:00:05.000000000Z",
     "containers": [
       {"name": "shop-web-1", "state": "running", "health": null},
       {"name": "shop-backend-1", "state": "running", "health": "healthy"}]},
    {"name": "cms", "label": "cms", "runtime": "pm2", "dir": "/var/www/cms",
     "domains": [{"domain": "cms.example.com", "scheme": "https", "status_code": 401, "ok": true, "tls_valid": false, "cert_days_left": 12}],
     "mem_bytes": 190000000, "disk_bytes": 350000000, "started_at": "2025-08-04T09:33:20+00:00", "containers": []},
    {"name": "game", "label": "Game Server", "runtime": "container", "dir": "/root/game",
     "domains": [], "mem_bytes": 1800000000, "disk_bytes": null,
     "started_at": "2026-06-15T08:00:00.000000000Z",
     "containers": [{"name": "game", "state": "running", "health": null}]},
    {"name": "/var/www/docs", "label": "/var/www/docs", "runtime": "static", "dir": "/var/www/docs",
     "domains": [{"domain": "docs.example.com", "scheme": "http", "status_code": 200, "ok": true, "tls_valid": null, "cert_days_left": null}],
     "mem_bytes": 0, "disk_bytes": 120000000, "started_at": null, "containers": []}
  ],
  "vhosts": [
    {"domains": ["app.example.com", "www.app.example.com"], "upstream_port": 3000, "static_root": null, "tls": true, "app": "shop", "status": "ok"},
    {"domains": ["cms.example.com"], "upstream_port": 8055, "static_root": null, "tls": true, "app": "cms", "status": "ok"},
    {"domains": ["docs.example.com"], "upstream_port": null, "static_root": "/var/www/docs", "tls": false, "app": "/var/www/docs", "status": "static"},
    {"domains": ["monitoring.example.com"], "upstream_port": 8080, "static_root": null, "tls": true, "app": null, "status": "dead"}
  ],
  "certs": {"/etc/letsencrypt/live/app.example.com/fullchain.pem": {"not_after": "2026-11-01T00:00:00+00:00", "days_left": 88}},
  "warnings": [
    {"kind": "dead_vhost", "message": "monitoring.example.com points at 127.0.0.1:8080 but nothing is listening there"},
    {"kind": "exposed_port", "message": "port 65410 (game) is bound to 0.0.0.0 and bypasses nginx and TLS"},
    {"kind": "tls_invalid", "message": "cms.example.com serves a certificate that fails verification"},
    {"kind": "cert_expiring", "message": "/etc/letsencrypt/live/cms.example.com/fullchain.pem expires in 12 days"}
  ],
  "gatherers": {
    "nginx": {"status": "ok"}, "docker": {"status": "ok"}, "pm2": {"status": "ok"},
    "ports": {"status": "ok"}, "host": {"status": "ok"}, "certs": {"status": "ok"}, "probe": {"status": "ok"}
  },
  "telegram_error": null
}
```

- [ ] **Step 2: Write `dashboard/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>vps-visibility</title>
<style>
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e;
  --muted: #898781; --grid: #e1e0d9; --border: rgba(11,11,11,0.10);
  --accent: #2a78d6;
  --good: #0ca30c; --warning: #fab219; --serious: #ec835a; --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
    --accent: #3987e5;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
  --muted: #898781; --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
  --accent: #3987e5;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--page); color: var(--ink);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
}
header { display: flex; align-items: baseline; gap: 12px; padding: 18px 20px 6px; }
h1 { font-size: 18px; margin: 0; }
main { padding: 0 20px 40px; max-width: 1180px; margin: 0 auto; }
.muted { color: var(--muted); }
.small { font-size: 12px; }
.num { font-variant-numeric: tabular-nums; }
section { margin-top: 22px; }
section > h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--ink-2); margin: 0 0 10px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.tile { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; }
.tile .v { font-size: 19px; font-weight: 600; }
.tile .c { margin-top: 2px; }
.meter { height: 4px; border-radius: 2px; background: var(--grid); margin-top: 8px; overflow: hidden; }
.meter i { display: block; height: 100%; background: var(--accent); }
.meter.hot i { background: var(--critical); }
.warnings { display: flex; flex-direction: column; gap: 6px; }
.warning { background: var(--surface); border: 1px solid var(--border); border-left: 3px solid var(--warning); border-radius: 8px; padding: 8px 12px; }
.warning.critical { border-left-color: var(--critical); }
.warning.serious { border-left-color: var(--serious); }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 12px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
.card header { display: flex; align-items: center; gap: 8px; padding: 0; margin-bottom: 8px; }
.card h3 { margin: 0; font-size: 15px; flex: 1; overflow-wrap: anywhere; }
.badge { font-size: 11px; border: 1px solid var(--border); border-radius: 999px; padding: 1px 8px; color: var(--ink-2); white-space: nowrap; }
.domain { display: flex; align-items: center; gap: 8px; padding: 3px 0; flex-wrap: wrap; }
.domain a { color: var(--ink); text-decoration: none; overflow-wrap: anywhere; }
.domain a:hover { text-decoration: underline; }
.chip { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--border); border-radius: 999px; padding: 0 8px; font-size: 12px; color: var(--ink-2); white-space: nowrap; }
.dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.stats { display: flex; gap: 16px; margin-top: 10px; flex-wrap: wrap; }
.stat .v { font-weight: 600; }
.stat .c { margin-left: 4px; }
.containers { margin-top: 8px; }
.containers div { display: flex; align-items: center; gap: 6px; padding: 1px 0; }
.sparks { display: flex; gap: 20px; margin-top: 12px; }
.spark svg { display: block; }
table { width: 100%; border-collapse: collapse; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
th, td { text-align: left; padding: 8px 12px; border-top: 1px solid var(--grid); overflow-wrap: anywhere; }
thead th { border-top: none; color: var(--ink-2); font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }
.tablewrap { overflow-x: auto; }
#tooltip { position: fixed; pointer-events: none; background: var(--ink); color: var(--page); padding: 3px 8px; border-radius: 6px; font-size: 12px; z-index: 10; }
</style>
</head>
<body>
<header>
  <h1>vps-visibility</h1>
  <div id="updated" class="muted small"></div>
</header>
<main id="root"><p class="muted">Loading&hellip;</p></main>
<div id="tooltip" hidden></div>
<noscript><p style="padding:20px">This dashboard needs JavaScript to render data/current.json.</p></noscript>
<script>
"use strict";
const SVG_NS = "http://www.w3.org/2000/svg";
const tooltip = document.getElementById("tooltip");

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}
function fmtBytes(bytes) {
  if (bytes == null) return "n/a";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let value = bytes, i = 0;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
  return (i ? value.toFixed(1) : value) + " " + units[i];
}
function fmtDuration(seconds) {
  if (seconds == null) return "n/a";
  const d = Math.floor(seconds / 86400);
  if (d) return d + "d " + Math.floor((seconds % 86400) / 3600) + "h";
  const h = Math.floor(seconds / 3600);
  if (h) return h + "h " + Math.floor((seconds % 3600) / 60) + "m";
  return Math.max(1, Math.floor(seconds / 60)) + "m";
}
function fmtAgo(iso) {
  if (!iso) return "n/a";
  const seconds = (Date.now() - Date.parse(iso)) / 1000;
  return isFinite(seconds) ? fmtDuration(seconds) : "n/a";
}
function chip(color, label) {
  const c = el("span", "chip", "");
  const dot = el("span", "dot");
  dot.style.background = "var(--" + color + ")";
  c.append(dot, document.createTextNode(label));
  return c;
}
function showTip(event, text) {
  tooltip.textContent = text;
  tooltip.hidden = false;
  tooltip.style.left = (event.clientX + 12) + "px";
  tooltip.style.top = (event.clientY - 24) + "px";
}
function hideTip() { tooltip.hidden = true; }

function sparkline(caption, values, labels, format) {
  const wrap = el("div", "spark");
  wrap.append(el("div", "muted small", caption));
  const points = values.filter(v => v != null);
  if (points.length < 2) {
    wrap.append(el("div", "muted small", "no history yet"));
    return wrap;
  }
  const width = 150, height = 34, pad = 3;
  const min = Math.min(...points), max = Math.max(...points);
  const span = (max - min) || 1;
  const xy = values.map((v, i) => [
    pad + i * (width - 2 * pad) / (values.length - 1),
    v == null ? null : height - pad - (v - min) * (height - 2 * pad) / span,
  ]);
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("width", width);
  svg.setAttribute("height", height);
  const base = document.createElementNS(SVG_NS, "line");
  base.setAttribute("x1", pad); base.setAttribute("x2", width - pad);
  base.setAttribute("y1", height - pad); base.setAttribute("y2", height - pad);
  base.setAttribute("stroke", "var(--grid)");
  svg.append(base);
  const poly = document.createElementNS(SVG_NS, "polyline");
  poly.setAttribute("points", xy.filter(p => p[1] != null).map(p => p.join(",")).join(" "));
  poly.setAttribute("fill", "none");
  poly.setAttribute("stroke", "var(--accent)");
  poly.setAttribute("stroke-width", "2");
  poly.setAttribute("stroke-linejoin", "round");
  svg.append(poly);
  const last = xy.filter(p => p[1] != null).pop();
  const end = document.createElementNS(SVG_NS, "circle");
  end.setAttribute("cx", last[0]); end.setAttribute("cy", last[1]);
  end.setAttribute("r", "2.5"); end.setAttribute("fill", "var(--accent)");
  svg.append(end);
  svg.addEventListener("mousemove", (event) => {
    const x = event.offsetX;
    let best = 0;
    xy.forEach((p, i) => { if (Math.abs(p[0] - x) < Math.abs(xy[best][0] - x)) best = i; });
    if (values[best] != null) showTip(event, format(values[best]) + " · " + labels[best]);
  });
  svg.addEventListener("mouseleave", hideTip);
  wrap.append(svg);
  return wrap;
}

const WARNING_SEVERITY = {
  dead_vhost: "critical", gatherer_error: "critical", exposed_port: "serious",
  tls_invalid: "serious", cert_expiring: "warning", disk: "warning",
  mem: "warning", stale: "warning", telegram: "warning",
};
const WARNING_ICON = { critical: "✕", serious: "▲", warning: "▲" };

function domainRow(d) {
  const row = el("div", "domain");
  const link = el("a", null, d.domain);
  link.href = (d.scheme || "https") + "://" + d.domain;
  link.rel = "noopener";
  row.append(link);
  if (d.ok === true) row.append(chip("good", String(d.status_code)));
  else if (d.ok === false) row.append(chip("critical", d.status_code ? String(d.status_code) : "down"));
  if (d.tls_valid === false) row.append(chip("serious", "bad TLS"));
  if (d.cert_days_left != null) {
    row.append(chip(d.cert_days_left <= 14 ? "warning" : "good", "cert " + d.cert_days_left + "d"));
  }
  return row;
}

function appCard(app, series) {
  const card = el("article", "card");
  const head = el("header");
  head.append(el("h3", null, app.label));
  head.append(el("span", "badge", app.runtime));
  card.append(head);
  app.domains.forEach(d => card.append(domainRow(d)));
  if (!app.domains.length) card.append(el("div", "muted small", "no vhost"));

  const stats = el("div", "stats");
  [["mem", fmtBytes(app.mem_bytes)], ["disk", fmtBytes(app.disk_bytes)],
   ["up", app.started_at ? fmtAgo(app.started_at) : "n/a"]].forEach(([label, value]) => {
    const s = el("span", "stat");
    s.append(el("span", "v num", value), el("span", "c muted small", label));
    stats.append(s);
  });
  card.append(stats);

  if (app.containers.length) {
    const list = el("div", "containers small");
    app.containers.forEach(c => {
      const line = el("div");
      const okState = c.state === "running" && (c.health == null || c.health === "healthy");
      line.append(chip(okState ? "good" : "critical", c.state + (c.health ? " · " + c.health : "")));
      line.append(el("span", "muted", c.name));
      list.append(line);
    });
    card.append(list);
  }

  const sparks = el("div", "sparks");
  sparks.append(sparkline("memory", series.mem, series.labels, fmtBytes));
  sparks.append(sparkline("disk", series.disk, series.labels, fmtBytes));
  card.append(sparks);
  return card;
}

function hostTiles(host, generatedAt, intervalSeconds) {
  const tiles = el("div", "tiles");
  function tile(value, caption, meterPct) {
    const t = el("div", "tile");
    t.append(el("div", "v num", value), el("div", "c muted small", caption));
    if (meterPct != null) {
      const meter = el("div", "meter" + (meterPct >= 90 ? " hot" : ""));
      const fill = el("i");
      fill.style.width = Math.min(100, meterPct) + "%";
      meter.append(fill);
      t.append(meter);
    }
    tiles.append(t);
  }
  tile(host.hostname || "n/a", host.public_ip || "no public ip");
  tile(fmtDuration(host.uptime_seconds), "uptime");
  tile((host.load || []).join(" / "), "load 1 / 5 / 15");
  const mem = host.mem || {};
  const memPct = mem.total_bytes ? Math.round(mem.used_bytes * 100 / mem.total_bytes) : null;
  tile(fmtBytes(mem.used_bytes) + " / " + fmtBytes(mem.total_bytes), "memory", memPct);
  (host.filesystems || []).forEach(fs => {
    tile(fmtBytes(fs.used_bytes) + " / " + fmtBytes(fs.total_bytes), "disk " + fs.mount, fs.pct);
  });
  return tiles;
}

function render(current, historyRecords) {
  const root = document.getElementById("root");
  root.textContent = "";
  const updated = document.getElementById("updated");
  updated.textContent = "updated " + fmtAgo(current.generated_at) + " ago";

  const warnings = current.warnings.slice();
  const ageSeconds = (Date.now() - Date.parse(current.generated_at)) / 1000;
  if (ageSeconds > 3 * (current.interval_seconds || 300)) {
    warnings.unshift({kind: "stale", message: "data is " + fmtDuration(ageSeconds) + " old; the collector may have stopped"});
  }
  if (current.telegram_error) {
    warnings.push({kind: "telegram", message: "telegram alert delivery failed: " + current.telegram_error});
  }

  const hostSection = el("section");
  hostSection.append(el("h2", null, "Host"));
  hostSection.append(hostTiles(current.host, current.generated_at, current.interval_seconds));
  root.append(hostSection);

  if (warnings.length) {
    const section = el("section");
    section.append(el("h2", null, "Warnings"));
    const list = el("div", "warnings");
    warnings.forEach(w => {
      const severity = WARNING_SEVERITY[w.kind] || "warning";
      const row = el("div", "warning " + severity);
      row.append(el("strong", null, WARNING_ICON[severity] + " " + w.kind.replace(/_/g, " ") + ": "));
      row.append(document.createTextNode(w.message));
      list.append(row);
    });
    section.append(list);
    root.append(section);
  }

  const series = buildSeries(historyRecords);
  const appsSection = el("section");
  appsSection.append(el("h2", null, "Apps"));
  const cards = el("div", "cards");
  current.apps.forEach(app => {
    cards.append(appCard(app, series[app.name] || {mem: [], disk: [], labels: []}));
  });
  appsSection.append(cards);
  root.append(appsSection);

  const vhostSection = el("section");
  vhostSection.append(el("h2", null, "Vhosts"));
  const wrap = el("div", "tablewrap");
  const table = el("table");
  const thead = el("thead");
  const headRow = el("tr");
  ["Domains", "TLS", "Upstream", "App", "Status"].forEach(h => headRow.append(el("th", null, h)));
  thead.append(headRow);
  table.append(thead);
  const tbody = el("tbody");
  current.vhosts.forEach(v => {
    const row = el("tr");
    row.append(el("td", null, v.domains.join(", ")));
    row.append(el("td", null, v.tls ? "https" : "http"));
    row.append(el("td", "num", v.upstream_port ? ":" + v.upstream_port : (v.static_root || "")));
    row.append(el("td", null, v.app || ""));
    const cell = el("td");
    const color = v.status === "ok" ? "good" : (v.status === "dead" ? "critical" : "good");
    cell.append(chip(color, v.status));
    row.append(cell);
    tbody.append(row);
  });
  table.append(tbody);
  wrap.append(table);
  vhostSection.append(wrap);
  root.append(vhostSection);
}

function buildSeries(records) {
  const byApp = {};
  const stride = Math.max(1, Math.ceil(records.length / 60));
  records.filter((_, i) => i % stride === 0 || i === records.length - 1).forEach(rec => {
    const label = new Date(rec.ts * 1000).toLocaleString(undefined, {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"});
    Object.keys(rec.apps || {}).forEach(name => {
      const entry = byApp[name] = byApp[name] || {mem: [], disk: [], labels: []};
      entry.mem.push(rec.apps[name][0]);
      entry.disk.push(rec.apps[name][1] || null);
      entry.labels.push(label);
    });
  });
  return byApp;
}

async function loadHistory() {
  const fetches = [];
  for (let i = 6; i >= 0; i--) {
    const day = new Date(Date.now() - i * 86400000).toISOString().slice(0, 10);
    fetches.push(fetch("data/history/" + day + ".jsonl")
      .then(r => r.ok ? r.text() : "")
      .catch(() => ""));
  }
  const texts = await Promise.all(fetches);
  return texts.join("\n").split("\n").filter(Boolean).map(line => {
    try { return JSON.parse(line); } catch (e) { return null; }
  }).filter(Boolean).sort((a, b) => a.ts - b.ts);
}

async function main() {
  let current;
  try {
    const response = await fetch("data/current.json", {cache: "no-store"});
    current = await response.json();
  } catch (e) {
    document.getElementById("root").textContent = "";
    document.getElementById("root").append(
      el("p", "muted", "Could not load data/current.json. Has the collector run yet?"));
    return;
  }
  render(current, await loadHistory());
}

main();
setInterval(main, 60000);
</script>
</body>
</html>
```

- [ ] **Step 3: Render-check with the sample data**

```bash
ln -s ../sample-data dashboard/data
cd dashboard && python3 -m http.server 8090
```

Open `http://localhost:8090` (browser or browser agent) and verify: host tiles with disk meter at ~81%, four warnings (plus an expected "stale" one, since the sample timestamp is fixed in the past), four app cards ("no history yet" in sparkline slots is correct because sample history does not exist), vhost table with the dead row marked, no JavaScript console errors, and a sensible dark-mode rendering (`document.documentElement.dataset.theme = "dark"` in the console to force it). Then stop the server; the `dashboard/data` symlink stays untracked (`.gitignore` covers it).

- [ ] **Step 4: Commit**

```bash
git add dashboard/index.html sample-data/current.json
git commit -m "feat: dashboard page with sample data"
```

---

### Task 13: Installer, uninstaller and nginx template

**Files:**
- Create: `nginx/vhost.conf.template`, `setup.sh`, `uninstall.sh`

**Interfaces:**
- Consumes: repo layout (`collector/collect.py`, `dashboard/`), config keys from Task 11.
- Produces: a one-command install. `setup.sh` is idempotent, must run as root, prompts for every value (or takes it from an env override so automation can drive it): `VV_DOMAIN`, `VV_AUTH_USER`, `VV_AUTH_PASS`, `VV_TG_TOKEN`, `VV_TG_CHAT`, `VV_DATA_DIR`, `VV_CERT_EMAIL`, `VV_SKIP_TLS`. It writes the config, htpasswd, nginx vhost, and cron entry, runs the collector once, prints the exact DNS A record to add (domain -> detected server IP), waits for DNS to resolve, then runs certbot itself.

- [ ] **Step 1: Create `nginx/vhost.conf.template`**

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name __DOMAIN__;

    root __REPO_DIR__/dashboard;
    index index.html;

    auth_basic "vps-visibility";
    auth_basic_user_file /etc/vps-visibility/htpasswd;

    location /data/ {
        alias __DATA_DIR__/public/;
        autoindex off;
    }
}
```

- [ ] **Step 2: Create `setup.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "setup.sh must run as root (it writes nginx, cron and /etc config)." >&2
    exit 1
fi
for binary in python3 nginx openssl; do
    command -v "$binary" >/dev/null || { echo "missing required binary: $binary" >&2; exit 1; }
done

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF_DIR=/etc/vps-visibility

prompt() {
    local var="$1" text="$2" secret="${3:-}"
    if [[ -z "${!var:-}" ]]; then
        if [[ -n "$secret" ]]; then
            read -rsp "$text" "$var"; echo
        else
            read -rp "$text" "$var"
        fi
    fi
}

prompt VV_DOMAIN "Dashboard domain (e.g. vps.example.com): "
prompt VV_AUTH_USER "Basic auth username: "
prompt VV_AUTH_PASS "Basic auth password: " secret
VV_TG_TOKEN="${VV_TG_TOKEN-}"
if [[ -z "$VV_TG_TOKEN" ]]; then
    read -rp "Telegram bot token (enter to skip alerts): " VV_TG_TOKEN
fi
VV_TG_CHAT="${VV_TG_CHAT-}"
if [[ -n "$VV_TG_TOKEN" && -z "$VV_TG_CHAT" ]]; then
    read -rp "Telegram chat id: " VV_TG_CHAT
fi
VV_DATA_DIR="${VV_DATA_DIR:-/var/lib/vps-visibility}"

mkdir -p "$CONF_DIR" "$VV_DATA_DIR/public/history"

if [[ ! -f "$CONF_DIR/config.json" ]]; then
    python3 - "$VV_DOMAIN" "$VV_DATA_DIR" "$VV_TG_TOKEN" "$VV_TG_CHAT" > "$CONF_DIR/config.json" <<'PY'
import json, sys
domain, data_dir, token, chat = sys.argv[1:5]
print(json.dumps({
    "schema_version": 1,
    "dashboard_domain": domain,
    "data_dir": data_dir,
    "retention_days": 14,
    "probe_via": "localhost",
    "public_ip": None,
    "filesystems": ["/"],
    "thresholds": {"disk_pct": 90, "mem_pct": 90, "cert_warn_days": 14},
    "telegram": {"bot_token": token or None, "chat_id": chat or None},
    "app_overrides": [],
}, indent=2))
PY
    chmod 600 "$CONF_DIR/config.json"
    echo "wrote $CONF_DIR/config.json"
else
    echo "$CONF_DIR/config.json already exists, leaving it untouched"
fi

printf '%s:%s\n' "$VV_AUTH_USER" "$(openssl passwd -apr1 "$VV_AUTH_PASS")" > "$CONF_DIR/htpasswd"
chmod 640 "$CONF_DIR/htpasswd"
chown root:www-data "$CONF_DIR/htpasswd" 2>/dev/null || true

VHOST=/etc/nginx/sites-enabled/vps-visibility.conf
if [[ ! -e "$VHOST" ]]; then
    sed -e "s|__DOMAIN__|$VV_DOMAIN|g" \
        -e "s|__REPO_DIR__|$REPO_DIR|g" \
        -e "s|__DATA_DIR__|$VV_DATA_DIR|g" \
        "$REPO_DIR/nginx/vhost.conf.template" > "$VHOST"
    nginx -t
    systemctl reload nginx
    echo "wrote $VHOST"
else
    echo "$VHOST already exists, leaving it untouched"
fi

printf '*/5 * * * * root python3 %s/collector/collect.py >> /var/log/vps-visibility.log 2>&1\n' \
    "$REPO_DIR" > /etc/cron.d/vps-visibility
chmod 644 /etc/cron.d/vps-visibility

echo "running the collector once..."
python3 "$REPO_DIR/collector/collect.py"

SERVER_IP=$(hostname -I | tr ' ' '\n' | grep -Ev '^$|^10\.|^192\.168\.|^127\.|^172\.|:' | head -1)
echo
echo "==> Add this DNS record at your DNS provider now:"
echo "    A    $VV_DOMAIN    $SERVER_IP"
echo

if [[ "${VV_SKIP_TLS:-}" == "1" ]]; then
    echo "VV_SKIP_TLS=1: skipping certbot. Later run: certbot --nginx -d $VV_DOMAIN"
else
    prompt VV_CERT_EMAIL "Email for Let's Encrypt expiry notices: "
    echo "waiting for $VV_DOMAIN to resolve to $SERVER_IP (checking every 15s, up to 10 minutes)..."
    RESOLVED=""
    for _ in $(seq 1 40); do
        RESOLVED=$(getent hosts "$VV_DOMAIN" | awk '{print $1}' | head -1 || true)
        [[ "$RESOLVED" == "$SERVER_IP" ]] && break
        sleep 15
    done
    if [[ "$RESOLVED" == "$SERVER_IP" ]] && command -v certbot >/dev/null; then
        certbot --nginx -d "$VV_DOMAIN" --non-interactive --agree-tos -m "$VV_CERT_EMAIL" \
            || echo "certbot failed; fix and rerun: certbot --nginx -d $VV_DOMAIN"
    else
        echo "DNS is not resolving to $SERVER_IP yet (got: ${RESOLVED:-nothing}) or certbot is missing."
        echo "Once DNS is live, run: certbot --nginx -d $VV_DOMAIN"
    fi
fi

echo
echo "Done. Dashboard: https://$VV_DOMAIN (or http:// until certbot has run)"
echo "Data dir: $VV_DATA_DIR   Config: $CONF_DIR/config.json"
```

- [ ] **Step 3: Create `uninstall.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "uninstall.sh must run as root." >&2
    exit 1
fi

rm -f /etc/cron.d/vps-visibility
rm -f /etc/nginx/sites-enabled/vps-visibility.conf
nginx -t && systemctl reload nginx
echo "Removed the cron entry and nginx vhost."
echo "Left in place: /etc/vps-visibility (config, htpasswd) and the data directory."
echo "Delete those two manually if you want a full removal."
```

- [ ] **Step 4: Syntax-check both scripts and mark executable**

```bash
bash -n setup.sh uninstall.sh
chmod +x setup.sh uninstall.sh
```

Expected: no output from `bash -n` (clean parse). If shellcheck is installed, run `shellcheck setup.sh uninstall.sh` and fix any error-level findings.

- [ ] **Step 5: Commit**

```bash
git add nginx/vhost.conf.template setup.sh uninstall.sh
git commit -m "feat: installer, uninstaller and nginx template"
```

---

### Task 14: README

**Files:**
- Modify: `README.md` (replace the stub)

**Interfaces:**
- Consumes: everything; documents the install flow from Task 13 and config from Task 11.

- [ ] **Step 1: Write the full `README.md`**

```markdown
# vps-visibility

One dashboard for a hand-rolled VPS. It reads your nginx config, Docker and
PM2, joins them, and answers at a glance what SSH archaeology answers today:

- which apps are live, behind which domains, and whether HTTPS actually works
- which vhosts are dead (proxying to a port nothing listens on)
- which ports are exposed to the internet, bypassing nginx and TLS
- how much memory and disk each app uses, and its trend over the last weeks
- how old each deployment is, when each TLS cert expires
- Telegram messages when a domain goes down, recovers, a container disappears
  or restarts, disk or memory crosses a threshold, or a cert nears expiry

![dashboard](docs/screenshot.png)

Zero runtime dependencies: a Python 3 (3.8+) standard-library collector on a
cron, one static HTML page served by the nginx you already run, JSON files in
between. No agents, no database, no Node, no pip installs.

## Install

On the VPS, as root:

    git clone https://github.com/gauravkrp/vps-visibility /opt/vps-visibility
    cd /opt/vps-visibility
    sudo bash setup.sh

The installer asks for a dashboard domain, basic auth credentials, and an
optional Telegram bot token. It then writes `/etc/vps-visibility/config.json`,
an nginx vhost, and a cron entry (every 5 minutes), runs the collector once,
prints the exact DNS A record to add, waits for DNS, and runs certbot for TLS.

Prompts can be pre-answered with env vars for unattended installs:
`VV_DOMAIN`, `VV_AUTH_USER`, `VV_AUTH_PASS`, `VV_TG_TOKEN`, `VV_TG_CHAT`,
`VV_DATA_DIR`, `VV_CERT_EMAIL`, `VV_SKIP_TLS=1`.

Telegram setup: message @BotFather, `/newbot`, copy the token; then message
your new bot once and open `https://api.telegram.org/bot<token>/getUpdates`
to read your chat id.

## How it works

A cron job runs `collector/collect.py` every 5 minutes:

1. Parse `/etc/nginx/sites-enabled/` for server blocks (domains, upstreams,
   cert paths). Certbot-managed files with multiple blocks are handled.
2. Ask Docker (`ps`, `inspect`, `stats`), PM2 (`jlist`) and the kernel
   (`ss -tlnp`, `/proc`) what is actually running.
3. Join: domain -> upstream port -> container or PID -> app. Vhosts pointing
   at silent ports become dead-vhost warnings; public listeners that bypass
   nginx become exposed-port warnings.
4. Probe every domain over HTTPS from localhost (SNI + Host header, cert
   verification on) and TCP-check every upstream.
5. Write `current.json` and a slim history line, prune history past the
   retention window, diff against the previous run, and send Telegram alerts
   on transitions only (down after 2 consecutive failures, recovery, restarts,
   disappearances, threshold crossings, expiring certs).

The dashboard is one static page reading those JSON files, served by your
nginx behind basic auth and TLS. If the collector dies, the page says so
("data is N old"), because staleness is computed client-side.

## Configuration

`/etc/vps-visibility/config.json` (mode 0600). Defaults shown; every key
optional except where the installer fills it:

| Key | Default | Meaning |
|---|---|---|
| `dashboard_domain` | none | Domain the dashboard is served on |
| `data_dir` | `/var/lib/vps-visibility` | Where JSON state and history live |
| `retention_days` | `14` | History files older than this are deleted |
| `probe_via` | `localhost` | `localhost` probes 127.0.0.1 with SNI; `public` goes through DNS |
| `public_ip` | auto-detected | Shown on the dashboard |
| `filesystems` | `["/"]` | Mounts to report and threshold-check |
| `thresholds.disk_pct` | `90` | Alert when a filesystem crosses this |
| `thresholds.mem_pct` | `90` | Alert when host memory crosses this |
| `thresholds.cert_warn_days` | `14` | Warn when a cert is this close to expiry |
| `telegram.bot_token` | none | Leave null to disable alerts |
| `telegram.chat_id` | none | Your chat with the bot |
| `app_overrides` | `[]` | `{match, dir, label}`; `match` is the app name, exact, case-insensitive |

## Security notes, honestly

- The collector runs as root via cron. It needs the Docker socket, nginx
  config, and `du` into app directories. Reduced-privilege alternative: run it
  as a user in the `docker` group and accept missing disk numbers for
  root-owned directories plus no `ss` process names.
- The dashboard and its JSON reveal internal ports and paths, so everything
  sits behind basic auth; run certbot so that auth never crosses the wire in
  plaintext.
- Secrets (Telegram token, htpasswd) live only on the VPS in `/etc/vps-visibility`,
  mode 0600/0640. Nothing secret is ever written into this repo.
- `setup.sh` is short on purpose. Read it before you run it as root.

## Limits (by design)

nginx only (Apache/Caddy/Traefik vhosts are not parsed; their apps still
appear via Docker/PM2 as "no vhost"). One server per install. Light history,
not a metrics platform: if you outgrow it, run Netdata or Beszel alongside.
No restart buttons: the page is static and read-only.

## Uninstall

    sudo bash /opt/vps-visibility/uninstall.sh

Removes the cron entry and vhost; leaves config and data for you to delete.

## Development

    python3 -m pytest tests/ -v          # pytest is the only dev dependency
    ln -s ../sample-data dashboard/data  # then: cd dashboard && python3 -m http.server 8090

MIT licensed. Issues and PRs welcome.
```

- [ ] **Step 2: Check rendering and commit**

Run: `grep -c '^## ' README.md` (expect 8 section headings) and view the file once for broken markdown.

```bash
git add README.md
git commit -m "docs: full README"
```

---

### Task 15: Publish to GitHub and battle-test on the reference VPS

This task dogfoods the released tool end to end: public repo, stranger-style install, real DNS, real certbot, real alert. Steps marked **(user)** need Gaurav; everything else is automated.

**Files:**
- Create (after verification): `docs/screenshot.png`, README screenshot reference already points at it.

- [ ] **Step 1: Push the public repo**

```bash
gh repo create vps-visibility --public --source=. --description "One dashboard for a hand-rolled VPS: nginx vhosts joined to Docker/PM2 apps, with health, resources and Telegram alerts" --push
git remote -v
```

Expected: repo visible at `github.com/<owner>/vps-visibility`, `main` pushed. If the README clone URL owner differs, fix the README and amend.

- [ ] **Step 2: Install on the VPS exactly like a stranger**

```bash
ssh root@203.0.113.10 "git clone https://github.com/<owner>/vps-visibility /opt/vps-visibility"
ssh -t root@203.0.113.10 "cd /opt/vps-visibility && VV_DOMAIN=vps.example.com VV_AUTH_USER=gaurav bash setup.sh"
```

The password prompt, Telegram token, and cert email are answered interactively (or pre-set via `VV_AUTH_PASS`, `VV_TG_TOKEN`, `VV_TG_CHAT`, `VV_CERT_EMAIL`). setup.sh prints the A record (`vps.example.com -> <server ip>`) and waits.

- [ ] **Step 3 (user): Add the DNS A record and the Telegram bot**

Gaurav adds the printed A record at his DNS provider, and creates the bot via @BotFather (token + chat id) if not done during Step 2. setup.sh finishes certbot on its own once DNS resolves.

- [ ] **Step 4: Verify acceptance criteria**

- `https://vps.example.com` prompts for basic auth, then renders.
- All apps on the box appear (byome prod and staging stacks, deshimoo, spendtracker, the edugyanam PM2 apps, the standalone game container), each mapped to its domains.
- The two dead vhosts (signoz, otel) show as dead-vhost warnings and dead rows in the vhost table.
- Publicly bound ports that bypass nginx (3200, 65410) show as exposed-port warnings.
- Disk warning appears if `/` is at or above the threshold.
- `curl -su user:pass https://vps.example.com/data/current.json | python3 -m json.tool | head` returns valid JSON; unauthenticated curl returns 401.
- After an hour, sparklines have points (verify on a second visit).

- [ ] **Step 5: Alert drill (confirm target with user first)**

With Gaurav's ok, stop a low-stakes container long enough for two collector runs, then bring it back:

```bash
ssh root@203.0.113.10 "docker stop myapp-backend-1"
# wait ~11 minutes (two cron runs at 5-minute cadence)
ssh root@203.0.113.10 "docker start myapp-backend-1"
```

Expected: one Telegram DOWN message for the spendtracker domain (plus GONE/RESTARTED for the container), then a RECOVERED message after restart. No repeats in between.

- [ ] **Step 6: Screenshot and close out**

Capture the live dashboard (browser agent, viewport 1280x900, light mode), save as `docs/screenshot.png`, verify the README image renders on GitHub.

```bash
git add docs/screenshot.png
git commit -m "docs: add dashboard screenshot"
git push
```

---

## Execution notes

- Tasks 1 through 11 are pure TDD on the dev machine; nothing touches the VPS until Task 15.
- Task 12's render check needs a browser (the browser agent works; no login involved).
- Task 15 has two user gates (DNS record, Telegram bot) and one confirmation gate (which container to bounce for the alert drill). Do not bounce anything without an explicit ok.
- The VPS SSH key setup is documented in the operator's local environment, not in this repo; nothing in the repo may reference real credentials, IPs of other people, or tokens.



