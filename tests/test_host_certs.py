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


def test_host_gather_returns_ok_with_filesystems_and_public_ip():
    def runner(cmd, timeout=10):
        if cmd[0] == "df":
            return 0, DF
        if cmd == ["hostname", "-I"]:
            return 0, "203.0.113.5\n"
        return 1, ""

    result = host.gather({"filesystems": ["/"]}, runner=runner)
    assert result["status"] == "ok"
    assert result["data"]["filesystems"] == host.parse_df(DF)
    assert result["data"]["public_ip"] == "203.0.113.5"
