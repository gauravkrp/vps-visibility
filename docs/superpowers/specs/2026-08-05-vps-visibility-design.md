# vps-visibility: design

Date: 2026-08-05
Status: approved

## Summary

An open-source visibility dashboard and alerter for hand-rolled VPSes. It answers, from one page and without SSH: which apps are live behind which nginx vhosts, what domain routes to what container or process, how much memory and disk each app uses, how old each deployment is, whether HTTPS works, and when certs expire. When something breaks, it sends a Telegram message.

Monitoring tools are process-centric; a VPS owner's mental model is domain-centric. The nginx config is the only place the two meet. This tool's core value is that join: domain to upstream port to container or PID to app to resources.

Zero runtime dependencies: a Python 3 stdlib collector on cron, one static HTML dashboard served by the nginx already on the box, JSON files in between. MIT licensed, public repo.

## Goals

- One glanceable page per VPS showing every app: domains, HTTP/HTTPS health, cert expiry, runtime (Docker Compose project, PM2 process, or bare process), memory, disk, uptime/age.
- Surface problems the owner otherwise finds by accident: vhosts pointing at dead upstreams, ports published publicly that bypass nginx and TLS, disk or memory creep, expiring certs, a collector that stopped running.
- Telegram alerts on state transitions only (down, recovered, threshold crossed), never repeated spam.
- Installable by a stranger on any Debian/Ubuntu-family VPS with nginx: git clone, run `setup.sh`, done. No pip installs, no Node, no build step.
- Degrade gracefully: a box without PM2 or without Docker shows those sections as "not present", not as errors.

## Non-goals

- No actions (restart buttons, deploys). The dashboard is a static page by design.
- No multi-server aggregation. One instance per box.
- No time-series database or full metrics platform. Light history only. Users who outgrow it should install Netdata or Beszel alongside.
- nginx only for vhost parsing. Apache, Caddy, and Traefik are out of scope; apps not matched to a vhost still appear via Docker/PM2 discovery, marked "no vhost".
- No Windows support.

## Decisions and rationale

| Decision | Choice | Why |
|---|---|---|
| Where it runs | Cron collector on the VPS + static page served by host nginx | Glanceable from any device without SSH; no new always-on service |
| History | Current state + slim history records, default 14 days retention | Enables trend sparklines (disk creep, memory growth) without becoming a TSDB |
| Alerting | Yes, from the collector run | The cron already computes health; diffing against the previous run is cheap |
| Alert channel | Telegram bot | One HTTPS call from stdlib, free, instant on phone |
| Stack | Python 3.8+ stdlib collector, vanilla HTML/JS/CSS dashboard | Present on effectively every target VPS; auditable before running as root; widest contributor pool |
| Config format | JSON | stdlib-parseable on Python 3.8 (TOML support would need 3.11) |
| License | MIT | Maximum reuse |

## Architecture

```
cron (*/5) as root
  └─ collector/collect.py
       ├─ gatherers (isolated, each may fail alone)
       │    ├─ nginx.py      parse /etc/nginx/sites-enabled/*
       │    ├─ docker.py     docker ps / stats / inspect
       │    ├─ pm2.py        pm2 jlist (if pm2 exists)
       │    ├─ ports.py      ss -tlnp
       │    ├─ host.py       memory, load, df, uptime, public IP
       │    ├─ certs.py      openssl x509 on cert paths nginx references
       │    └─ probe.py      HTTP(S) check per domain + TCP check per upstream port
       ├─ join.py            domain -> upstream port -> container/PID -> app
       ├─ history.py         append slim record, prune, hourly du for per-app disk
       ├─ alerts.py          diff vs previous state, send Telegram on transitions
       └─ writes /var/lib/vps-visibility/{current.json, state.json, history/YYYY-MM-DD.jsonl}

host nginx vhost (from template, basic auth + TLS)
  ├─ /            -> dashboard/index.html (static)
  └─ /data/       -> /var/lib/vps-visibility/ (current.json + history)

browser: index.html fetches /data/current.json + recent history, renders client-side
```

## Components

### Collector (`collector/`)

Python package, stdlib only, entry point `collect.py`. Every subprocess call and HTTP request has a timeout (default 10s; du gets 120s). Each gatherer returns `{status: ok|absent|error, data|message}`; a gatherer failure is recorded and never aborts the run.

**nginx.py** parses every file in `sites-enabled/` (following the directory, not includes) for `server` blocks: `server_name`, `listen` (to classify 80/443/ssl), `proxy_pass` (upstream host:port), `root` (static sites), `ssl_certificate` path. Handles certbot-managed files where one file holds multiple server blocks and rewritten listen directives. Output: list of vhosts with domains, upstream port or static root, tls flag, cert path.

**docker.py** shells out to `docker ps` (all containers incl. stopped), `docker stats --no-stream`, and one `docker inspect` batch for: name, compose project and working_dir labels, image, created/started timestamps, health status, published ports (host ip:port -> container port), memory usage. Groups containers by compose project.

**pm2.py** runs `pm2 jlist` when pm2 is on PATH; extracts name, pid, ports are resolved via ports.py, memory, uptime, restart count, cwd.

**ports.py** parses `ss -tlnp`: listen address, port, pid, process name. Distinguishes loopback-bound from publicly-bound (0.0.0.0 / [::]) listeners.

**host.py** reads `/proc/meminfo`, `/proc/loadavg`, `df -P` for configured filesystems (default `/`), uptime, and the machine's public IP (config override, else best effort via `hostname -I` first global address).

**certs.py** runs `openssl x509 -enddate -noout -in <path>` for each distinct cert path nginx references; outputs days-to-expiry per domain.

**probe.py** performs, for each vhost domain: an HTTPS GET (then HTTP if HTTPS fails) with a short timeout, recording status code and latency, sent to localhost with a Host header (config flag `probe_via`: `localhost` default, or `public` to go through DNS); and a TCP connect to the upstream port so a dead upstream is identified even when nginx serves a cached 502 page.

**join.py** builds the app list. An "app" is: a Docker Compose project, a standalone container, a PM2 process, or a bare process. Matching: vhost upstream port -> Docker published port, else -> ss pid -> pm2 process (by pid) else bare process. Unmatched vhosts become "dead vhost" warnings. Unmatched publicly-bound listeners become "exposed port, bypasses nginx" warnings. Apps without any vhost are listed with domain "none".

Per-app disk: `du -s` on each app's directory (compose working_dir label, pm2 cwd, or config override), run at most hourly (cached in state.json between runs) because du is expensive.

### Output files (in `/var/lib/vps-visibility/`, configurable)

- `current.json`: schema_version, generated_at, host summary, apps[], vhosts[], warnings[], gatherer statuses. Complete picture for the dashboard.
- `history/YYYY-MM-DD.jsonl`: one slim line per run: timestamp, host mem/disk, per-app {name, mem_bytes, disk_bytes, health}. Files older than `retention_days` (default 14) are deleted each run.
- `state.json`: previous run's health per entity (for alert diffing), last alert timestamps, cached du results. Internal, not served.

### Alerter (`alerts.py`)

Runs at the end of each collect. Compares current vs state.json and sends one Telegram message per transition:

- Domain health: ok -> failing (after 2 consecutive failing runs, to avoid flapping) and failing -> ok (recovery notice).
- Container or PM2 process disappeared, or restart detected (started-at moved backwards / restart count increased).
- Disk usage crossed threshold upward (default 90%).
- Host memory crossed threshold upward (default 90%).
- Cert expiring within 14 days (one reminder per cert per 3 days, not per run).
- Collector self-check: if the previous run recorded a gatherer error that persists, include it once.

Telegram send: `https://api.telegram.org/bot<token>/sendMessage` via urllib, 10s timeout; failures are logged to state and shown on the dashboard, never raised.

### Dashboard (`dashboard/index.html`)

One file, vanilla JS and CSS, no build step, mobile-friendly, light/dark via prefers-color-scheme. Renders:

1. Host bar: hostname, public IP, uptime, load, memory used/total, disk used/total per filesystem, "last updated N min ago" (turns into a warning above 3x the cron interval).
2. Warnings strip: dead vhosts, exposed ports, stale data, gatherer errors, expiring certs, threshold breaches.
3. App cards: name, runtime badge (compose/container/pm2/process/static), domains with per-domain HTTPS status chip and cert days left, memory, disk, age (started-at), container list for compose projects (name, state, health), and two sparklines (memory, disk) drawn as inline SVG from the last 7 days of history.
4. Vhost table: every domain -> upstream -> app, including the dead ones.

The page fetches `/data/current.json` plus the last 7 daily history files (404s tolerated). No framework, no external assets: works offline behind auth, no CDN calls.

### Installer (`setup.sh`)

Bash, idempotent, must be run as root on the VPS. Steps:

1. Prompt for: dashboard domain, basic auth user/password, Telegram bot token + chat ID (optional, enter to skip alerting), thresholds (defaults offered), data dir (default `/var/lib/vps-visibility`).
2. Write `/etc/vps-visibility/config.json` (mode 0600).
3. Copy/symlink the repo to `/opt/vps-visibility` (documented layout), create data dir.
4. Generate htpasswd file via `openssl passwd -apr1` (no apache2-utils dependency).
5. Render `nginx/vhost.conf.template` with the domain and paths, write to `sites-enabled/vps-visibility.conf` only if absent, `nginx -t`, reload.
6. Install cron entry `*/5 * * * * root python3 /opt/vps-visibility/collector/collect.py` via `/etc/cron.d/vps-visibility`.
7. Run the collector once, print the dashboard URL and the certbot command to finish TLS (`certbot --nginx -d <domain>`).

`uninstall.sh` reverses 3-6 and leaves data. `config.example.json` in the repo documents every key with comments in the README (JSON has no comments).

### Config (`/etc/vps-visibility/config.json`)

```json
{
  "schema_version": 1,
  "dashboard_domain": "vps.example.com",
  "data_dir": "/var/lib/vps-visibility",
  "retention_days": 14,
  "probe_via": "localhost",
  "public_ip": null,
  "filesystems": ["/"],
  "thresholds": { "disk_pct": 90, "mem_pct": 90, "cert_warn_days": 14 },
  "telegram": { "bot_token": null, "chat_id": null },
  "app_overrides": [
    { "match": "gameserver", "dir": "/root/gameserver", "label": "OpenClaw" }
  ]
}
```

`app_overrides.match` is compared (exact, case-insensitive) against the app's derived name: the compose project name, standalone container name, or PM2 process name. An override can set the disk-scan directory and a display label.

## Error handling

- Gatherer isolation as above; `current.json` always gets written, with per-gatherer status.
- Missing tools (pm2, docker) report `absent`, which the dashboard renders as informational, not as an error.
- The collector never exits nonzero for data problems; only for unreadable config or unwritable data dir (so cron mail stays meaningful).
- Staleness is self-announcing: the page computes it from `generated_at`, and the alerter cannot alert about a dead collector, so the README recommends an external "collector heartbeat" check for the paranoid (explicitly out of scope to build).

## Security

- Dashboard and `/data/` live behind basic auth over TLS; `current.json` reveals internal ports and paths, so it is never served unauthenticated.
- Secrets (Telegram token, htpasswd) exist only on the VPS, mode 0600, outside the repo. `.gitignore` covers `config.json` and any local data.
- Collector runs as root via cron: required for the Docker socket, nginx config read, and per-app du into arbitrary dirs. README states this plainly and documents a reduced-privilege alternative (user in `docker` group, world-readable app dirs, no du into root-owned paths).
- setup.sh is short and readable on purpose; users are told to read it before running.

## Testing

- Unit tests (pytest, dev-only dependency) for the two pieces with real logic: `nginx.py` parsing and `join.py` matching. Fixtures include a certbot-managed multi-block config modeled on a real production server (multiple server blocks per file, rewritten listen directives, duplicated server_names across 80/443 blocks) and edge cases: static-root vhost, vhost with dead upstream, app with no vhost, publicly-bound port.
- Gatherers accept injected command output so parsers are testable without a live box; the subprocess layer stays thin and untested.
- Dashboard: rendered manually against a committed `sample-data/current.json` (also useful for README screenshots); no JS test framework in v1.
- Acceptance (reference instance): after install on the author's VPS, the dashboard at the configured domain shows 6 apps and 10 domains, flags 2 known dead vhosts and 2 publicly exposed ports, sparklines populate within an hour, and stopping a test container produces a Telegram alert plus a recovery message on restart.

## Repo layout

```
vps-visibility/
├── collector/
│   ├── collect.py          # entry point, orchestration
│   ├── gatherers/          # nginx.py, docker.py, pm2.py, ports.py, host.py, certs.py, probe.py
│   ├── join.py
│   ├── history.py
│   └── alerts.py
├── dashboard/index.html
├── nginx/vhost.conf.template
├── setup.sh
├── uninstall.sh
├── config.example.json
├── sample-data/current.json
├── tests/                  # test_nginx.py, test_join.py, fixtures/
├── docs/
├── README.md
└── LICENSE
```

## Rollout of the reference instance

1. Build and test locally against fixtures.
2. DNS A record for the dashboard subdomain to the VPS IP (owner action).
3. `git clone` to the VPS, run `setup.sh`, then certbot.
4. Owner creates the Telegram bot via @BotFather and supplies token + chat ID.
5. Verify acceptance criteria above; screenshot for the README.

## Future ideas (explicitly not in v1)

Multi-server rollup page, Caddy/Traefik parsers, systemd unit discovery, uptime SLA stats from history, Prometheus endpoint, restart actions behind authenticated POST.
