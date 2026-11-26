"""LLM provider and quote-verified extraction. No network: every HTTP call goes to httpx.MockTransport."""
import json

import httpx
import pytest

from medusa.analysis.dates import DateContext
from medusa.analysis.llm.extractor import LlmResponse, extract_with_llm, parse_response, verify_candidates
from medusa.analysis.llm.provider import (AnthropicProvider, LLMError, OpenAICompatibleProvider, build_provider,
                                          llm_configuration)
from medusa.analysis.rule_extractor import build_context, extract_claims
from medusa.analysis.segmentation import segment
from medusa.core.config import Settings

KEY = "sk-test-SECRET-0123456789"


def _settings(**kw):
    return Settings(_env_file=None, **kw)


def _provider(cls, handler, retries=2, key=KEY, sleeps=None):
    sleeps = sleeps if sleeps is not None else []
    return cls("test-model", key, "https://llm.example", 5.0, retries,
               transport=httpx.MockTransport(handler), sleep=sleeps.append)


def _anthropic_ok(text):
    return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})


def _openai_ok(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


# ------------------------------------------------------------------ configuration
@pytest.mark.parametrize("kw, expected", [
    ({}, "disabled"),
    ({"llm_provider": "anthropic", "llm_model": "m"}, "misconfigured"),          # no key
    ({"llm_provider": "anthropic", "llm_api_key": KEY}, "misconfigured"),       # no model
    ({"llm_provider": "anthropic", "llm_model": "m", "llm_api_key": KEY}, "configured"),
    ({"llm_provider": "openai_compatible", "llm_model": "m"}, "configured"),    # local servers need no key
    ({"llm_provider": "anthropic", "llm_model": "m", "llm_api_key": ""}, "misconfigured"),  # empty key = unset
])
def test_llm_configuration(monkeypatch, kw, expected):
    for k in list(__import__("os").environ):
        if k.startswith("MEDUSA_"):
            monkeypatch.delenv(k)
    s = _settings(**kw)
    assert llm_configuration(s)[0] == expected
    assert (build_provider(s) is not None) == (expected == "configured")


def test_build_provider_uses_default_endpoints_and_names(monkeypatch):
    a = build_provider(_settings(llm_provider="anthropic", llm_model="claude-x", llm_api_key=KEY))
    o = build_provider(_settings(llm_provider="openai_compatible", llm_model="llama3", llm_base_url="http://127.0.0.1:11434/v1/"))
    assert (a.base_url, a.name) == ("https://api.anthropic.com", "anthropic/claude-x")
    assert (o.base_url, o.name) == ("http://127.0.0.1:11434/v1", "openai_compatible/llama3")


def test_api_key_is_never_shown():
    s = _settings(llm_provider="anthropic", llm_model="m", llm_api_key=KEY)
    assert KEY not in repr(s) and KEY not in str(s.model_dump())


# ------------------------------------------------------------------ request shape
def test_anthropic_request_shape():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(url=str(req.url), headers=req.headers, body=json.loads(req.content))
        return _anthropic_ok('{"claims": []}')

    assert _provider(AnthropicProvider, handler).complete_json("SYS", "USER") == '{"claims": []}'
    assert seen["url"] == "https://llm.example/v1/messages"
    assert seen["headers"]["x-api-key"] == KEY and seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["body"]["model"] == "test-model" and seen["body"]["temperature"] == 0
    assert seen["body"]["system"] == "SYS" and seen["body"]["messages"] == [{"role": "user", "content": "USER"}]


def test_openai_compatible_request_shape_and_optional_key():
    seen = []

    def handler(req):
        seen.append((str(req.url), req.headers.get("authorization"), json.loads(req.content)))
        return _openai_ok('{"claims": []}')

    _provider(OpenAICompatibleProvider, handler).complete_json("SYS", "USER")
    _provider(OpenAICompatibleProvider, handler, key=None).complete_json("SYS", "USER")
    assert seen[0][0] == "https://llm.example/chat/completions"
    assert seen[0][1] == f"Bearer {KEY}" and seen[1][1] is None
    body = seen[0][2]
    assert body["response_format"] == {"type": "json_object"} and body["temperature"] == 0
    assert body["messages"][0] == {"role": "system", "content": "SYS"}


# ------------------------------------------------------------------ failures and retries
def test_rate_limit_is_retried_honouring_retry_after():
    calls, sleeps = [], []

    def handler(req):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "3"}) if len(calls) == 1 else _anthropic_ok("{}")

    assert _provider(AnthropicProvider, handler, sleeps=sleeps).complete_json("s", "u") == "{}"
    assert len(calls) == 2 and sleeps == [3.0]


def test_persistent_rate_limit_gives_up_after_max_retries():
    calls, sleeps = [], []

    def handler(req):
        calls.append(1)
        return httpx.Response(429)

    with pytest.raises(LLMError) as e:
        _provider(AnthropicProvider, handler, retries=2, sleeps=sleeps).complete_json("s", "u")
    assert e.value.code == "rate_limited" and len(calls) == 3 and sleeps == [1.0, 2.0]


def test_server_error_then_success():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else _openai_ok("{}")

    assert _provider(OpenAICompatibleProvider, handler).complete_json("s", "u") == "{}"
    assert len(calls) == 3


def test_timeout_and_connection_errors():
    def timeout(req):
        raise httpx.ReadTimeout("slow", request=req)

    def refused(req):
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(LLMError) as e:
        _provider(AnthropicProvider, timeout, retries=1).complete_json("s", "u")
    assert e.value.code == "timeout"
    with pytest.raises(LLMError) as e:
        _provider(OpenAICompatibleProvider, refused, retries=0).complete_json("s", "u")
    assert e.value.code == "unavailable"


@pytest.mark.parametrize("status, code", [(401, "auth"), (403, "auth"), (400, "bad_request"), (404, "bad_request")])
def test_client_errors_are_not_retried(status, code):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(status, text="nope")

    with pytest.raises(LLMError) as e:
        _provider(AnthropicProvider, handler).complete_json("s", "u")
    assert e.value.code == code and len(calls) == 1
    assert KEY not in str(e.value)


@pytest.mark.parametrize("response", [
    httpx.Response(200, json={"content": []}),
    httpx.Response(200, json={"unexpected": True}),
    httpx.Response(200, text="<html>proxy page</html>"),
])
def test_unusable_provider_responses_are_malformed_output(response):
    with pytest.raises(LLMError) as e:
        _provider(AnthropicProvider, lambda req: response).complete_json("s", "u")
    assert e.value.code == "malformed_output"


# ------------------------------------------------------------------ parsing
def test_parse_response_accepts_fenced_json_and_ignores_extra_fields():
    r = parse_response('Here you go:\n```json\n{"claims": [{"passage_id": "X", "category": "diagnosis", '
                       '"entity": "e", "quote": "q", "confidence": 0.9}]}\n```')
    assert len(r.claims) == 1 and r.claims[0].quote == "q"


@pytest.mark.parametrize("text", ["no json here", '{"claims": "many"}', '{"claims": [{"category": "x"}]}', "{broken"])
def test_parse_response_rejects_bad_output(text):
    with pytest.raises(LLMError) as e:
        parse_response(text)
    assert e.value.code == "malformed_output"


# ------------------------------------------------------------------ verification against the source
@pytest.fixture(scope="module")
def radiology(demo_documents):
    doc = next(d for d in demo_documents if d.document_type == "Radiology Report")
    passages = segment(doc.document_id, doc.text)
    rules = extract_claims(doc, passages, build_context(demo_documents)).claims
    return doc, passages, rules


def _pid(passages, contains):
    return next(p.passage_id for p in passages if contains in p.text)


def test_verification_keeps_only_verbatim_quotes(radiology):
    doc, passages, rules = radiology
    finding = _pid(passages, "focal consolidation")
    response = LlmResponse.model_validate({"claims": [
        {"passage_id": finding, "category": "diagnosis", "entity": "Focal  Consolidation", "quote": "focal consolidation",
         "assertion": "present"},
        {"passage_id": finding, "category": "diagnosis", "entity": "consolidation", "quote": "lobar consolidation seen"},
        {"passage_id": finding, "category": "diagnosis", "entity": "x", "quote": "No Focal Consolidation"},  # case differs
        {"passage_id": "DOC-NOPE:P001", "category": "diagnosis", "entity": "x", "quote": "focal consolidation"},
        {"passage_id": finding, "category": "prescription", "entity": "x", "quote": "focal consolidation"},
        {"passage_id": finding, "category": "diagnosis", "entity": "x", "quote": "   "},
    ]})
    out = verify_candidates(doc, passages, response, rules, DateContext(doc.document_date), "fake/m")
    assert [c.surface for c in out.accepted] == ["focal consolidation"]
    assert sorted(r["reason"] for r in out.rejected) == sorted(
        ["quote_not_in_passage", "quote_not_in_passage", "unknown_passage", "unknown_category", "empty_quote"])
    c = out.accepted[0]
    assert doc.text[c.source.entity_char_start:c.source.entity_char_end] == "focal consolidation"
    assert c.entity == "focal consolidation" and c.extraction_method == "llm:fake/m"
    # the server decides the assertion from the passage; the model's word is kept only for comparison
    assert c.attributes.assertion == "absent" and c.attributes.model_assertion == "present"


def test_candidate_found_by_rules_counts_as_agreement_not_a_second_claim(radiology):
    doc, passages, rules = radiology
    rule = next(c for c in rules if c.claim_type == "procedure")
    response = LlmResponse.model_validate({"claims": [
        {"passage_id": rule.source.passage_id, "category": "procedure", "entity": rule.entity, "quote": rule.surface}]})
    out = verify_candidates(doc, passages, response, rules, DateContext(doc.document_date), "fake/m")
    assert out.accepted == [] and out.agreed_with_rules == 1


def test_llm_claim_event_date_is_computed_from_the_passage(radiology):
    doc, passages, rules = radiology
    pid = _pid(passages, "Chest X-ray")
    response = LlmResponse.model_validate({"claims": [
        {"passage_id": pid, "category": "encounter", "entity": "chest radiograph", "quote": "performed on 2026-03-11"}]})
    out = verify_candidates(doc, passages, response, rules, DateContext(doc.document_date), "fake/m")
    ev = out.accepted[0].event_date
    assert (str(ev.value), ev.precision, ev.basis) == ("2026-03-11", "day", "explicit")


def test_rejections_are_bounded(radiology):
    doc, passages, rules = radiology
    pid = passages[-1].passage_id
    response = LlmResponse.model_validate({"claims": [
        {"passage_id": pid, "category": "diagnosis", "entity": "x", "quote": f"invented {i}"} for i in range(120)]})
    out = verify_candidates(doc, passages, response, rules, DateContext(doc.document_date), "fake/m")
    assert out.rejected_count == 120 and len(out.rejected) == 50


def test_extract_with_llm_end_to_end_through_a_mock_provider(radiology):
    doc, passages, rules = radiology
    pid = _pid(passages, "focal consolidation")
    seen = {}

    def handler(req):
        seen["prompt"] = json.loads(req.content)["messages"][0]["content"]
        return _anthropic_ok(json.dumps({"claims": [{"passage_id": pid, "category": "diagnosis",
                                                     "entity": "consolidation", "quote": "focal consolidation"}]}))

    out = extract_with_llm(_provider(AnthropicProvider, handler), doc, passages, rules, DateContext(doc.document_date))
    assert f"[{pid}]" in seen["prompt"] and len(out.accepted) == 1
    assert out.accepted[0].extraction_method == "llm:anthropic/test-model"


def test_check_command_reports_disabled(monkeypatch, capsys):
    from medusa.analysis.llm import check
    monkeypatch.setattr(check, "get_settings", lambda: _settings())
    assert check.main() == 2
    assert "disabled" in capsys.readouterr().out
