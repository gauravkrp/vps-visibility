import json
import urllib.error
from unittest.mock import patch

from collector import alerts

CONFIG = {"thresholds": {"disk_pct": 90, "mem_pct": 90, "cert_warn_days": 14}}


DEAD_VHOST_MSG = "monitoring.example.com points at 127.0.0.1:8080 but nothing is listening there"
EXPOSED_PORT_MSG = "port 5432 is listening on 0.0.0.0"


def make_current(dom_ok=True, status=200, disk_pct=50.0, mem_used=50,
                 started="2026-08-04T18:00:05Z", certs=None, gatherers=None,
                 warnings=None):
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
        "warnings": warnings or [],
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
    state = {"app_starts": {"compose": {"shop": "x", "old-app": "y"}}}
    msgs, new_state = alerts.compute(state, make_current(), CONFIG, 1000)
    assert any(m.startswith("GONE") and "old-app" in m for m in msgs)
    assert "old-app" not in new_state["app_starts"]["compose"]


def with_pm2_namesake(current, started):
    """The same app name under pm2 as well, e.g. a CMS and the site it feeds."""
    pm2 = dict(current["apps"][0], runtime="pm2", started_at=started, domains=[])
    current["apps"].append(pm2)
    return current


def test_same_name_in_two_runtimes_is_not_a_restart():
    def snapshot():
        return with_pm2_namesake(make_current(started="2026-11-23T06:49:31Z"),
                                 "2026-11-13T06:46:19Z")

    _, state = alerts.compute({}, snapshot(), CONFIG, 1000)
    msgs, state = alerts.compute(state, snapshot(), CONFIG, 1300)
    assert msgs == []
    msgs, _ = alerts.compute(state, snapshot(), CONFIG, 1600)
    assert msgs == []


def test_restart_names_the_runtime_when_names_collide():
    _, state = alerts.compute(
        {}, with_pm2_namesake(make_current(), "2026-11-13T06:46:19Z"), CONFIG, 1000)
    msgs, _ = alerts.compute(
        state, with_pm2_namesake(make_current(), "2026-11-23T09:00:00Z"), CONFIG, 1300)
    assert msgs == ["RESTARTED: shop (pm2, started 2026-11-23T09:00:00Z)"]


def test_state_keyed_by_name_alone_is_ignored_not_reported_gone():
    state = {"apps": {"shop": {"started_at": "2026-08-04T18:00:05Z"}}}
    msgs, new_state = alerts.compute(state, make_current(), CONFIG, 1000)
    assert msgs == []
    assert new_state["app_starts"] == {"compose": {"shop": "2026-08-04T18:00:05Z"}}


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


def test_dead_vhost_warning_alerts_once():
    warns = [{"kind": "dead_vhost", "message": DEAD_VHOST_MSG}]
    msgs, state = alerts.compute({}, make_current(warnings=warns), CONFIG, 1000)
    assert any(m.startswith("DEAD_VHOST:") and DEAD_VHOST_MSG in m for m in msgs)
    msgs, _ = alerts.compute(state, make_current(warnings=warns), CONFIG, 1300)
    assert msgs == []


def test_dead_vhost_warning_clearing_alerts_resolved():
    warns = [{"kind": "dead_vhost", "message": DEAD_VHOST_MSG}]
    _, state = alerts.compute({}, make_current(warnings=warns), CONFIG, 1000)
    msgs, state = alerts.compute(state, make_current(), CONFIG, 1300)
    assert any(m.startswith("RESOLVED (DEAD_VHOST):") and DEAD_VHOST_MSG in m for m in msgs)
    msgs, _ = alerts.compute(state, make_current(), CONFIG, 1600)
    assert msgs == []


def test_exposed_port_warning_alerts_on_onset():
    warns = [{"kind": "exposed_port", "message": EXPOSED_PORT_MSG}]
    msgs, _ = alerts.compute({}, make_current(warnings=warns), CONFIG, 1000)
    assert any(m.startswith("EXPOSED_PORT:") and EXPOSED_PORT_MSG in m for m in msgs)


def test_untracked_warning_kinds_are_ignored():
    warns = [{"kind": "gatherer_error", "message": "nginx gatherer failed"},
             {"kind": "cert_expiring", "message": "cert expires in 3 days"}]
    msgs, state = alerts.compute({}, make_current(warnings=warns), CONFIG, 1000)
    assert msgs == []
    assert state["warnings"] == {}


def test_send_telegram_success():
    with patch("collector.alerts.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value.getcode.return_value = 200
        result = alerts.send_telegram("BOTTOKEN", "555", "server is down")
    assert result is True
    req = mock_urlopen.call_args[0][0]
    assert "BOTTOKEN" in req.full_url
    body = json.loads(req.data.decode())
    assert body == {"chat_id": "555", "text": "server is down"}


def test_send_telegram_failure_returns_false():
    with patch("collector.alerts.urllib.request.urlopen",
               side_effect=urllib.error.URLError("boom")):
        result = alerts.send_telegram("BOTTOKEN", "555", "server is down")
    assert result is False
