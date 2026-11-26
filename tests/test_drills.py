"""Phase 10 failure drills: each failure must produce a clear message and the app must recover."""
import http.server
import json
import socket
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from medusa import __version__
from medusa.analysis.llm.provider import build_provider
from medusa.analysis.pipeline import AnalysisService
from medusa.main import create_app, port_problem

P = "SYN-0001"


@pytest.fixture()
def tolerant(settings):
    """A client that returns 5xx responses instead of raising, like a real browser sees them."""
    with TestClient(create_app(settings), raise_server_exceptions=False) as c:
        yield c


def _demo(c):
    c.post(f"/api/patients/{P}/demo/load")
    return c.post(f"/api/patients/{P}/analysis")


# ------------------------------------------------------------------ LLM
def test_drill_no_llm_key(settings):
    s = settings.model_copy(update={"llm_provider": "anthropic", "llm_model": "claude-x", "llm_api_key": None})
    with TestClient(create_app(s)) as c:
        run = _demo(c).json()
        assert run["status"] == "completed" and run["llm_status"] == "misconfigured" and run["extractor"] == "rules"
        cfg = c.get(f"/api/patients/{P}/overview").json()["llm"]
        assert cfg["status"] == "misconfigured" and "MEDUSA_LLM_API_KEY" in cfg["reason"]
        assert c.get(f"/api/patients/{P}/overview").json()["claims"]["total"] == 51


@pytest.mark.parametrize("reply, code", [
    (httpx.Response(200, json={"choices": [{"message": {"content": "Sure! Here are the claims: the patient is fine."}}]}), "malformed_output"),
    (httpx.Response(200, json={"choices": [{"message": {"content": '{"claims": "lots"}'}}]}), "malformed_output"),
    (httpx.Response(200, text="<html>captive portal</html>"), "malformed_output"),
    (httpx.Response(401, text="bad key"), "auth"),
])
def test_drill_llm_returns_garbage(settings, reply, code):
    s = settings.model_copy(update={"llm_provider": "openai_compatible", "llm_model": "m", "llm_max_retries": 0})
    app = create_app(s)
    transport = httpx.MockTransport(lambda req: reply)
    app.state.analysis = AnalysisService(s, provider_factory=lambda cfg: build_provider(cfg, transport=transport))
    with TestClient(app) as c:
        run = _demo(c).json()
    assert run["status"] == "completed" and run["extractor"] == "rules" and run["llm_status"] == "failed"
    assert run["llm_error"].startswith(f"{code}:") and run["stats"]["claims_by_method"] == {"rule": 51, "llm": 0}


# ------------------------------------------------------------------ database
@pytest.mark.parametrize("how", ["deleted", "replaced with an empty file"])
def test_drill_database_lost_mid_session(settings, tolerant, how):
    _demo(tolerant)
    for f in settings.db_path.parent.glob(settings.db_path.name + "*"):
        f.unlink()
    if how != "deleted":
        settings.db_path.write_bytes(b"")
    ready = tolerant.get("/api/health/ready").json()
    assert ready["status"] == "unavailable"
    r = tolerant.get(f"/api/patients/{P}/overview")
    assert r.status_code == 503 and r.json()["error"]["code"] == "database_recreated"
    assert "load the demo bundle again" in r.json()["error"]["message"]
    # recovered: empty but working, and the demo can be loaded and analysed again
    assert tolerant.get("/api/health/ready").json()["status"] == "ready"
    assert tolerant.get(f"/api/patients/{P}/overview").json()["documents"]["total"] == 0
    assert _demo(tolerant).json()["stats"]["claims_total"] == 51


# ------------------------------------------------------------------ uploads
def test_drill_upload_over_5_mb(settings, tolerant):
    _demo(tolerant)
    big = b"DOCUMENT TYPE: Note\n" + b"x" * (settings.max_upload_bytes + 500_000)
    r = tolerant.post(f"/api/patients/{P}/documents", files={"file": ("big.txt", big)})
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"
    assert "5,000,000 byte limit" in r.json()["error"]["message"]
    assert len(tolerant.get(f"/api/patients/{P}/documents").json()) == 7  # nothing stored
    assert tolerant.get(f"/api/patients/{P}/overview").json()["analysis"]["is_current"] is True


def test_drill_upload_over_5_mb_real_server_reads_the_body_before_the_413(settings):
    """On a real socket the server must read the oversized body before answering. Answering straight after the
    headers and closing makes a proxy (Vite in development) hit a reset while still forwarding the body, so the
    browser randomly shows "backend unreachable" (502) instead of the 413. Seen live in Phase 10; this checks the
    cause deterministically: no reply may arrive while the body is still being sent."""
    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            threading.Event().wait(0.05)
        size = settings.max_upload_bytes + 1_000_000
        with socket.create_connection(("127.0.0.1", port), timeout=10) as conn:
            conn.sendall(f"POST /api/patients/{P}/documents HTTP/1.1\r\nHost: x\r\nContent-Type: text/plain\r\n"
                         f"Content-Length: {size}\r\n\r\n".encode())
            conn.sendall(b"x" * 100_000)  # part of the body only
            conn.settimeout(1.0)
            with pytest.raises(socket.timeout):
                conn.recv(1)  # still waiting for the rest of the body, so no reply yet
            conn.settimeout(10)
            conn.sendall(b"x" * (size - 100_000))
            reply = b""
            while b"\r\n\r\n" not in reply or b"payload_too_large" not in reply:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                reply += chunk
        assert reply.startswith(b"HTTP/1.1 413") and b"5,000,000 byte limit" in reply
        assert httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=5).json()["max_upload_bytes"] == \
            settings.max_upload_bytes
    finally:
        server.should_exit = True
        thread.join(timeout=10)


# ------------------------------------------------------------------ port in use
def test_drill_port_free_and_taken_by_another_program():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert port_problem("127.0.0.1", port) is None
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", port))
        busy.listen()
        msg = port_problem("127.0.0.1", port, timeout=0.3)
    assert f"Port {port} on 127.0.0.1 is already in use by another program." in msg
    assert "taskkill /F /T /PID" in msg and "MEDUSA_API_PORT" in msg


def test_drill_port_taken_by_another_medusa_backend():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps({"status": "ok", "app": "MEDUSA-X", "version": __version__}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        msg = port_problem("127.0.0.1", server.server_address[1])
    finally:
        server.shutdown()
    assert f"another MEDUSA-X backend, version {__version__} (this same version" in msg
