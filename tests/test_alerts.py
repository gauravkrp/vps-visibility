import json
import urllib.error
from unittest.mock import patch

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
