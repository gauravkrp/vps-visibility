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


def test_daemon_banner_lines_starting_with_bracket_are_skipped():
    out = (
        "[PM2] Spawning PM2 daemon with pm2_home=/root/.pm2\n"
        "[PM2] PM2 Successfully daemonized\n"
        + JLIST
    )
    result = pm2.gather(lambda cmd, timeout=30: (0, out))
    assert result["status"] == "ok"
    assert result["data"] == [{
        "name": "cms", "pid": 2222, "status": "online", "mem_bytes": 190000000,
        "restarts": 3, "started_at": "2025-08-04T09:33:20+00:00", "cwd": "/var/www/cms",
    }]


def test_pm2_missing_reports_absent():
    assert pm2.gather(lambda cmd, timeout=30: (-1, ""))["status"] == "absent"


def test_no_json_reports_error():
    assert pm2.gather(lambda cmd, timeout=30: (0, "garbage"))["status"] == "error"
