"""Isolated browser-test server. This fixture never contacts an AI service."""

import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from conftest import FakeProvider, StubStream
from waitress import serve


class SlowStream(StubStream):
    def __iter__(self):
        for _ in range(50):
            time.sleep(0.12)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Réponse en cours… "))])


class BrowserProvider(FakeProvider):
    def create(self, **kwargs):
        message = kwargs["messages"][-1]["content"]
        self.mode = "auth" if message.startswith("test-http-error") else (
            "broken" if message.startswith("test-stream-error") else "ok"
        )
        if message.startswith("test-slow-response"):
            return SlowStream()
        return super().create(**kwargs)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="flaskgpt-browser-") as temp:
        provider = BrowserProvider()
        app = create_app({"TESTING": True, "SECRET_KEY": "browser-test-only",
                          "DATABASE": str(Path(temp) / "ui.sqlite3"),
                          "GROQ_API_KEY": "", "AI_CLIENT_FACTORY": lambda: provider})
        print("Browser test fixture: http://127.0.0.1:5011", flush=True)
        serve(app, host="127.0.0.1", port=5011, threads=8)
