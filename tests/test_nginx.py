import os

from collector.gatherers import nginx

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "sites-enabled")


def _by_domain(vhosts, domain):
    return next(v for v in vhosts if domain in v["domains"])


def test_gather_parses_fixture_dir():
    result = nginx.gather(FIXTURES)
    assert result["status"] == "ok"
    assert len(result["data"]) == 3


def test_certbot_blocks_merge_into_one_vhost():
    v = _by_domain(nginx.gather(FIXTURES)["data"], "app.example.com")
    assert v["domains"] == ["app.example.com", "www.app.example.com"]
    assert v["upstream_port"] == 3000
    assert v["upstream_host"] == "127.0.0.1"
    assert v["tls"] is True
    assert v["cert_path"] == "/etc/letsencrypt/live/app.example.com/fullchain.pem"
    assert v["remote"] is False


def test_dead_upstream_vhost_still_parses():
    v = _by_domain(nginx.gather(FIXTURES)["data"], "dead.example.com")
    assert v["upstream_port"] == 8080
    assert v["tls"] is True


def test_static_root_vhost():
    v = _by_domain(nginx.gather(FIXTURES)["data"], "docs.example.com")
    assert v["upstream_port"] is None
    assert v["static_root"] == "/var/www/docs"
    assert v["tls"] is False


def test_remote_upstream_flagged():
    blocks = nginx.parse_server_blocks(
        "server { server_name r.example.com; listen 80;"
        " location / { proxy_pass http://10.0.0.9:9000; } }"
    )
    v = nginx.merge_blocks(blocks)[0]
    assert v["remote"] is True and v["upstream_port"] == 9000


def test_missing_dir_reports_absent():
    assert nginx.gather("/nonexistent/path")["status"] == "absent"
