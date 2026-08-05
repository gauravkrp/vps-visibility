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
