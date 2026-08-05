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
