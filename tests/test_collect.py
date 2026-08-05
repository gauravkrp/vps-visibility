import json

import pytest

from collector import collect
from collector.util import absent, error, ok


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
    with pytest.raises(OSError):
        collect.load_config(str(tmp_path / "nope.json"))


def test_main_writes_current_json_with_expected_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(collect.nginx, "gather", lambda: ok([]))
    monkeypatch.setattr(collect.docker, "gather", lambda: absent("no docker"))
    monkeypatch.setattr(collect.pm2, "gather", lambda: absent("pm2 not installed"))
    monkeypatch.setattr(collect.ports, "gather", lambda: error("ss failed"))
    monkeypatch.setattr(collect.host, "gather", lambda cfg: error("host stats failed"))
    monkeypatch.setattr(collect.certs, "gather", lambda paths, now: ok({}))
    monkeypatch.setattr(collect.probe, "gather", lambda vhosts, via: ok({"domains": {}, "upstreams": {}}))

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"data_dir": str(tmp_path)}))

    assert collect.main([str(config_path)]) == 0

    current_path = tmp_path / "public" / "current.json"
    assert current_path.exists()
    current = json.loads(current_path.read_text())
    assert set(current.keys()) == {
        "schema_version", "generated_at", "interval_seconds", "host", "apps",
        "vhosts", "certs", "warnings", "gatherers", "telegram_error",
    }


def test_main_missing_config_returns_1():
    assert collect.main(["/nonexistent/path/config.json"]) == 1
