import io
from types import SimpleNamespace

import pytest

from conftest import events, send
from storage import claim_turn, conversation_for
from web_answers import safe_url, web_answer


def test_web_search_requires_tool_and_uses_current_question_only(client, csrf, provider):
    events(send(client, csrf, "PRIVATE_HISTORY"))
    response = client.post("/api/chat", data={"file": (io.BytesIO(b"PRIVATE_FILE"), "private.txt")}, headers=csrf)
    events(response)
    response = client.post("/api/chat", json={"message": "A public factual question", "web_search": True}, headers=csrf)
    assert events(response)[-1]["type"] == "done"
    call = provider.calls[-1]
    assert call["tools"] == [{"type": "browser_search"}] and call["tool_choice"] == "required"
    assert call["stream"] is False and call["reasoning_effort"] == "low"
    assert len(call["messages"]) == 2
    assert all("PRIVATE_" not in message["content"] for message in call["messages"])
    assert "https://example.com/reference" in client.get("/api/conversation").json["messages"][-1]["content"]


def test_regular_messages_do_not_search(client, csrf, provider):
    events(send(client, csrf))
    assert provider.calls[-1]["stream"] is True
    assert "tools" not in provider.calls[-1]


@pytest.mark.parametrize("value", ["true", 1, None, [], {}])
def test_web_option_is_boolean(client, csrf, value):
    assert client.post("/api/chat", json={"message": "Test", "web_search": value}, headers=csrf).status_code == 400


def test_search_without_source_evidence_is_not_saved(client, csrf, provider):
    provider.chat.completions.create = lambda **kwargs: SimpleNamespace(choices=[
        SimpleNamespace(message=SimpleNamespace(content="A claim without a source", model_extra={}), finish_reason="stop")
    ])
    response = client.post("/api/chat", json={"message": "A public question", "web_search": True}, headers=csrf)
    assert response.status_code == 502 and response.json["code"] == "missing_web_sources"
    assert client.get("/api/conversation").json["messages"] == []


def test_unsupported_model_does_not_offer_search(app, client, csrf):
    app.config["GROQ_MODEL"] = "another-model"
    assert not client.get("/api/conversation").json["web_search_available"]
    response = client.post("/api/chat", json={"message": "Test", "web_search": True}, headers=csrf)
    assert response.status_code == 400


def test_cancel_releases_active_generation(app, client, csrf):
    with client.session_transaction() as session:
        owner = session["owner"]
    with app.app_context():
        assert claim_turn(conversation_for(owner)["id"])
    assert client.post("/api/conversation/cancel", headers=csrf).status_code == 200
    assert events(send(client, csrf))[-1]["type"] == "done"


def test_web_source_links_are_from_opened_pages():
    message = SimpleNamespace(content="A fact【4†L1-L2】. [Invented](https://fake.invalid) Another https://fake2.invalid", model_extra={"executed_tools": [
        {"index": 0, "name": "browser.search", "search_results": {"results": [{"url": "https://example.org/page", "title": "Real reference"}]}},
        {"index": 4, "name": "browser.open", "output": "L0: URL: https://example.org/page\nL1: Evidence."}
    ]})
    result = web_answer(SimpleNamespace(choices=[SimpleNamespace(message=message)]))
    assert "[Real reference](<https://example.org/page>)" in result
    assert "Sources consultées" in result and "【" not in result and "fake.invalid" not in result and "fake2.invalid" not in result
    assert safe_url("javascript:alert(1)") is None
    assert safe_url("https://[") is None
