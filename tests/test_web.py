"""Phase 11 single-process demo: the backend serves the built UI without changing any /api behaviour."""
import pytest
from fastapi.testclient import TestClient

from medusa import main as main_module
from medusa.main import create_app
from medusa.web import dist_problem

INDEX = "<!doctype html><title>MEDUSA-X</title><div id=root></div>"


@pytest.fixture()
def dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text(INDEX)
    (d / "assets" / "index-abc123.js").write_text("console.log('ui')")
    (d / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("outside the build")
    return d


@pytest.fixture()
def demo(settings, dist):
    s = settings.model_copy(update={"serve_frontend": True, "frontend_dist": dist})
    with TestClient(create_app(s)) as c:
        yield c


def test_ui_is_not_served_by_default(client):
    r = client.get("/")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_root_and_deep_links_return_the_app_shell(demo):
    for path in ("/", "/workspace/overview", "/workspace/review?x=1"):
        r = demo.get(path)
        assert r.status_code == 200 and r.text == INDEX, path
        assert r.headers["cache-control"] == "no-cache"
    assert demo.head("/workspace/timeline").status_code == 200


def test_assets_are_served_with_long_cache(demo):
    r = demo.get("/assets/index-abc123.js")
    assert r.status_code == 200 and "console.log" in r.text
    assert "immutable" in r.headers["cache-control"]
    assert demo.get("/favicon.svg").headers["cache-control"] == "no-cache"


def test_api_behaviour_is_unchanged(demo):
    assert demo.get("/api/health").json()["app"] == "MEDUSA-X"
    r = demo.get("/api/no-such-endpoint")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert demo.get("/api").status_code == 404 and "error" in demo.get("/api").json()
    r = demo.post("/api/health")  # wrong method on a real endpoint stays 405, not the UI
    assert r.status_code == 405 and r.json()["error"]["code"] == "method_not_allowed"
    assert demo.post("/workspace/overview").status_code in (404, 405)  # only GET/HEAD get the shell


def test_missing_file_is_a_real_404_and_nothing_outside_the_build_is_served(demo):
    r = demo.get("/missing.png")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    for path in ("/../secret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt"):
        r = demo.get(path)
        assert "outside the build" not in r.text, path


def test_dist_problem_explains_how_to_build(tmp_path, dist):
    assert dist_problem(dist) is None
    msg = dist_problem(tmp_path / "nothing")
    assert "npm run build" in msg and "Demo: single process" in msg


def test_run_refuses_to_start_without_a_build(settings, tmp_path, monkeypatch, capsys):
    s = settings.model_copy(update={"serve_frontend": True, "frontend_dist": tmp_path / "nothing"})
    monkeypatch.setattr(main_module, "get_settings", lambda: s)
    monkeypatch.setattr(main_module, "port_problem", lambda *a, **k: None)
    monkeypatch.setattr(main_module.uvicorn, "run", lambda *a, **k: pytest.fail("must not start"))
    with pytest.raises(SystemExit) as exc:
        main_module.run()
    assert exc.value.code == 1
    assert "frontend build was not found" in capsys.readouterr().out


def test_run_prints_the_single_url(settings, dist, monkeypatch, capsys):
    s = settings.model_copy(update={"serve_frontend": True, "frontend_dist": dist})
    started = {}
    monkeypatch.setattr(main_module, "get_settings", lambda: s)
    monkeypatch.setattr(main_module, "port_problem", lambda *a, **k: None)
    monkeypatch.setattr(main_module.uvicorn, "run", lambda *a, **k: started.update(k))
    main_module.run()
    assert started["port"] == s.api_port
    assert f"http://127.0.0.1:{s.api_port}" in capsys.readouterr().out
