import json
import logging
import sqlite3

from fastapi import Depends
from fastapi.testclient import TestClient

from medusa import __version__
from medusa.core.errors import NotFoundError
from medusa.core.logging import JsonFormatter
from medusa.db.connection import get_db
from medusa.main import create_app

from factories import insert_raw_document


# ---------------------------------------------------------------- health
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "app": "MEDUSA-X", "version": __version__, "environment": "test",
                       "max_upload_bytes": 5_000_000}
    assert r.headers["X-Request-ID"]


def test_startup_creates_database(client, settings):
    assert settings.db_path.exists()


def test_ready(client):
    r = client.get("/api/health/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert r.json()["database"]["schema_version"] == r.json()["database"]["expected_version"]


def test_ready_reports_broken_database(client, settings):
    conn = sqlite3.connect(settings.db_path)
    conn.execute("DROP TABLE claims")
    conn.commit()
    conn.close()
    r = client.get("/api/health/ready")
    assert r.status_code == 503 and r.json()["status"] == "unavailable"
    assert "claims" in r.json()["database"]["error"]


# ---------------------------------------------------------------- request id
def test_request_id_echoed_when_valid(client):
    assert client.get("/api/health", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"] == "abc-123"


def test_request_id_replaced_when_unsafe(client):
    rid = client.get("/api/health", headers={"X-Request-ID": "bad id\n<script>"}).headers["X-Request-ID"]
    assert rid != "bad id\n<script>" and len(rid) == 16


# ---------------------------------------------------------------- error envelope
def _app_with_test_routes(settings):
    app = create_app(settings)

    @app.get("/_test/missing")
    def missing():
        raise NotFoundError("Claim CLM-1 not found", details={"claim_id": "CLM-1"})

    @app.get("/_test/crash")
    def crash():
        raise RuntimeError("secret internal detail")

    @app.get("/_test/items/{n}")
    def item(n: int):
        return {"n": n}

    @app.post("/_test/docs")
    def add_doc(fail: bool = False, conn=Depends(get_db)):
        insert_raw_document(conn, "DOC-T", "P")
        if fail:
            raise RuntimeError("after insert")
        return {"ok": True}

    @app.get("/_test/docs")
    def count_docs(conn=Depends(get_db)):
        return {"count": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]}

    return app


def _assert_envelope(r, status, code):
    assert r.status_code == status
    body = r.json()["error"]
    assert body["code"] == code and body["message"] and body["request_id"] == r.headers["X-Request-ID"]
    return body


def test_app_error_envelope(settings):
    with TestClient(_app_with_test_routes(settings)) as c:
        body = _assert_envelope(c.get("/_test/missing"), 404, "not_found")
        assert body["details"] == {"claim_id": "CLM-1"}


def test_unhandled_error_is_500_without_internals(settings, caplog):
    with TestClient(_app_with_test_routes(settings)) as c:
        caplog.set_level(logging.ERROR)
        r = c.get("/_test/crash", headers={"X-Request-ID": "trace-me"})
        body = _assert_envelope(r, 500, "internal_error")
        assert "secret" not in r.text and body["request_id"] == "trace-me"
        rec = next(x for x in caplog.records if x.levelno == logging.ERROR)
        assert rec.exc_info and rec.request_id == "trace-me"  # stack trace is in the log, not the response


def test_validation_error_envelope(settings):
    with TestClient(_app_with_test_routes(settings)) as c:
        body = _assert_envelope(c.get("/_test/items/abc"), 422, "validation_error")
        assert body["details"][0]["loc"] == ["path", "n"] and "input" not in body["details"][0]


def test_http_errors_use_envelope(client):
    _assert_envelope(client.get("/no-such-route"), 404, "not_found")
    _assert_envelope(client.post("/api/health"), 405, "method_not_allowed")


def test_db_dependency_commits_and_rolls_back(settings):
    with TestClient(_app_with_test_routes(settings)) as c:
        assert c.post("/_test/docs", params={"fail": True}).status_code == 500
        assert c.get("/_test/docs").json() == {"count": 0}
        assert c.post("/_test/docs").status_code == 200
        assert c.get("/_test/docs").json() == {"count": 1}


# ---------------------------------------------------------------- docs toggle
def test_docs_disabled_in_production(settings):
    prod = settings.model_copy(update={"environment": "production"})
    with TestClient(create_app(prod)) as c:
        assert c.get("/api/docs").status_code == 404 and c.get("/api/openapi.json").status_code == 404
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/docs").status_code == 200


# ---------------------------------------------------------------- logging
def test_request_is_logged_with_request_id(client, caplog):
    caplog.set_level(logging.INFO, logger="medusa.http")
    client.get("/api/health", headers={"X-Request-ID": "log-check"})
    rec = next(r for r in caplog.records if r.name == "medusa.http" and "/api/health" in r.getMessage())
    assert rec.request_id == "log-check" and rec.status_code == 200 and rec.duration_ms >= 0


def test_json_formatter():
    rec = logging.LogRecord("medusa.http", logging.INFO, __file__, 1, "GET %s", ("/api/health",), None)
    rec.request_id, rec.status_code = "r1", 200
    out = json.loads(JsonFormatter().format(rec))
    assert out["message"] == "GET /api/health" and out["request_id"] == "r1" and out["status_code"] == 200


def test_log_file_handler(settings, tmp_path):
    s = settings.model_copy(update={"log_file": tmp_path / "logs" / "m.log", "log_format": "json"})
    with TestClient(create_app(s)) as c:
        c.get("/api/health", headers={"X-Request-ID": "file-check"})
    for h in logging.getLogger().handlers:
        h.flush()
    lines = [json.loads(x) for x in (tmp_path / "logs" / "m.log").read_text().splitlines()]
    assert any(x.get("request_id") == "file-check" and x.get("path") == "/api/health" for x in lines)
