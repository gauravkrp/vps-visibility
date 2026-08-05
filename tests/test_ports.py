from collector.gatherers.ports import gather, parse_ss

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


def test_gather_returns_ok_on_success():
    result = gather(runner=lambda cmd: (0, SS))
    assert result == {"status": "ok", "data": parse_ss(SS)}


def test_gather_returns_error_on_failure():
    result = gather(runner=lambda cmd: (1, ""))
    assert result["status"] == "error"
