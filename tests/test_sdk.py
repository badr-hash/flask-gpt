"""Exercise the actual SDK's HTTP and SSE parsing without spending API credits."""

import json

import httpx
import pytest
from openai import OpenAI

from conftest import events, send


def test_real_sdk_streaming(app, client, csrf):
    calls = []

    def transport(request):
        calls.append(json.loads(request.content))
        chunks = []
        for text in ("Un résumé ", "français, avec des accents : été."):
            chunk = {"id": "test", "object": "chat.completion.chunk", "created": 1,
                     "model": "openai/gpt-oss-20b", "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]}
            chunks.append("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n")
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=("".join(chunks) + "data: [DONE]\n\n").encode())

    sdk = OpenAI(api_key="test-only", base_url="https://local-test.invalid/v1", max_retries=0,
                 http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    app.config["AI_CLIENT_FACTORY"] = lambda: sdk
    try:
        assert events(send(client, csrf))[-1]["type"] == "done"
        assert calls[0]["stream"] is True and calls[0]["model"] == app.config["GROQ_MODEL"]
        assert "été" in client.get("/api/conversation").json["messages"][1]["content"]
    finally:
        sdk.close()


@pytest.mark.parametrize("status,code", [(401, "invalid_key"), (429, "rate_limit")])
def test_real_sdk_errors(app, client, csrf, status, code):
    sdk = OpenAI(api_key="test-only", base_url="https://local-test.invalid/v1", max_retries=0,
                 http_client=httpx.Client(transport=httpx.MockTransport(
                     lambda request: httpx.Response(status, json={"error": {"message": "do-not-display-provider-details"}})
                 )))
    app.config["AI_CLIENT_FACTORY"] = lambda: sdk
    try:
        response = send(client, csrf)
        assert response.status_code == status and response.json["code"] == code
        assert b"do-not-display-provider-details" not in response.data
    finally:
        sdk.close()
