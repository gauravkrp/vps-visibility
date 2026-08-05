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
