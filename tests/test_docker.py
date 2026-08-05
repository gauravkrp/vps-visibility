import os

from collector.gatherers import docker

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fake_runner(cmd, timeout=10):
    if cmd[:2] == ["docker", "ps"]:
        return 0, "aaa\nbbb\nccc\n"
    if cmd[:2] == ["docker", "inspect"]:
        with open(os.path.join(FIXTURES, "docker_inspect.json")) as f:
            return 0, f.read()
    if cmd[:2] == ["docker", "stats"]:
        return 0, ("shop-web-1\t5.4MiB / 15.62GiB\n"
                   "shop-backend-1\t741MiB / 15.62GiB\n"
                   "game\t1.702GiB / 15.62GiB\n")
    raise AssertionError("unexpected command %s" % cmd)


def test_gather_builds_containers_and_projects():
    data = docker.gather(fake_runner)["data"]
    assert len(data["containers"]) == 3
    assert data["projects"] == {"shop": {"working_dir": "/root/shop"}}


def test_container_fields():
    containers = docker.gather(fake_runner)["data"]["containers"]
    web = next(c for c in containers if c["name"] == "shop-web-1")
    assert web["published_ports"] == [{"host_ip": "127.0.0.1", "host_port": 3000,
                                       "container_port": "80/tcp"}]
    assert web["mem_bytes"] == int(5.4 * 1024**2)
    assert web["health"] is None
    backend = next(c for c in containers if c["name"] == "shop-backend-1")
    assert backend["health"] == "healthy"
    assert backend["published_ports"] == []


def test_docker_missing_reports_absent():
    assert docker.gather(lambda cmd, timeout=10: (-1, ""))["status"] == "absent"


def test_no_containers():
    def runner(cmd, timeout=10):
        return 0, ""
    assert docker.gather(runner)["data"] == {"containers": [], "projects": {}}
