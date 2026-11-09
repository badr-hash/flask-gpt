import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError

from app import create_app


class StubStream:
    def __init__(self, mode="ok"):
        self.mode = mode
        self.closed = False

    def __iter__(self):
        if self.mode == "empty":
            yield SimpleNamespace(choices=[])
            return
        for text in ("Bonjour ! ", "Voici une réponse **utile**.\n\n", "```python\nprint('été')\n```"):
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])
            if self.mode == "broken":
                raise APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))

    def close(self):
        self.closed = True


class FakeProvider:
    def __init__(self):
        self.mode = "ok"
        self.calls = []
        self.streams = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        req = httpx.Request("POST", "https://example.invalid")
        if self.mode in {"auth", "limit", "timeout", "connection"}:
            error = {
                "auth": lambda: AuthenticationError("secret-must-not-leak", response=httpx.Response(401, request=req), body=None),
                "limit": lambda: RateLimitError("quota", response=httpx.Response(429, request=req), body=None),
                "timeout": lambda: APITimeoutError(request=req),
                "connection": lambda: APIConnectionError(request=req),
            }[self.mode]()
            raise error
        if kwargs.get("tools"):
            message = SimpleNamespace(content="Une réponse sourcée【1†L2-L3】.", model_extra={"executed_tools": [
                {"index": 1, "name": "browser.open", "output": "L0:\nL1: URL: https://example.com/reference\nL2: A public source."}
            ]})
            return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])
        stream = StubStream(self.mode)
        self.streams.append(stream)
        return stream


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def app(tmp_path, provider):
    return create_app({"TESTING": True, "SECRET_KEY": "test-only-secret", "DATABASE": str(tmp_path / "test.sqlite3"),
                       "GROQ_API_KEY": "", "AI_CLIENT_FACTORY": lambda: provider})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def csrf(client):
    return {"X-CSRF-Token": client.get("/api/conversation").json["csrf_token"]}


def send(client, csrf, message="Bonjour", **kwargs):
    return client.post("/api/chat", json={"message": message}, headers=csrf, **kwargs)


def events(response):
    return [json.loads(line) for line in response.data.decode("utf-8").splitlines()]
