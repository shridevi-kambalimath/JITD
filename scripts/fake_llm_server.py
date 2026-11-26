"""Fake OpenAI-compatible LLM server for the "LLM returns garbage" QA drill (docs/QA.md, drill 2).

Standard library only. Listens on 127.0.0.1 and answers every POST with a reply that MEDUSA-X must reject:

    python scripts\\fake_llm_server.py            prose with no JSON at all (default)
    python scripts\\fake_llm_server.py bad-json   a truncated JSON object
    python scripts\\fake_llm_server.py wrong-quote valid JSON whose quote is not in the source text

Point the backend at it in .env, then restart the backend:

    MEDUSA_LLM_PROVIDER=openai_compatible
    MEDUSA_LLM_MODEL=garbage-model
    MEDUSA_LLM_BASE_URL=http://127.0.0.1:9911/v1
    MEDUSA_LLM_MAX_RETRIES=0

Stop with Ctrl+C. This is a test fixture, not an LLM: it stores nothing, and only looks at the request to copy the
first passage id into the wrong-quote reply.
"""
import http.server
import json
import re
import sys

PORT = 9911
REPLIES = {
    "prose": "Sure! The patient seems fine overall.",
    "bad-json": '{"claims": [{"claim_type": "medication", "entity": "warf',
    # valid JSON citing a real passage id, but quoting words that are not in it: every claim must be rejected
    "wrong-quote": '{"claims": [{"passage_id": "%s", "category": "medication", "entity": "aspirin", '
                   '"quote": "aspirin 900 mg every hour", "assertion": "present"}]}',
}


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "prose"
    if mode not in REPLIES:
        sys.exit(f"Unknown mode {mode!r}. Choose one of: {', '.join(REPLIES)}")
    template = REPLIES[mode]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            request = self.rfile.read(int(self.headers.get("content-length", 0))).decode("utf-8", "replace")
            content = template
            if "%s" in template:
                found = re.search(r"\[([^\]\s]+)\] \(", request.replace('\\"', '"'))
                content = template % (found.group(1) if found else "unknown")
            body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    print(f"Fake LLM ({mode}) on http://127.0.0.1:{PORT}/v1  (Ctrl+C to stop)")
    try:
        http.server.HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
