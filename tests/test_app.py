import io
import json

import pytest
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app import create_app
from chat_service import SPECIALTIES, build_context
from storage import claim_turn, conversation_for, get_db, release_turn
from conftest import events, send


def test_page_and_local_assets(client):
    page = client.get("/")
    assert page.status_code == 200
    assert b'lang="fr"' in page.data
    for path in ("/static/js/script.js", "/static/css/style.css", "/static/vendor/markdown-it.min.js",
                 "/static/vendor/purify.min.js", "/static/favicon.svg"):
        assert client.get(path).status_code == 200
    assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]


def test_complete_stream_persists_markdown_and_utf8(client, csrf, provider):
    response = send(client, csrf)
    result = events(response)
    assert response.status_code == 200
    assert result[0]["type"] == "start" and result[-1]["type"] == "done"
    messages = client.get("/api/conversation").json["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert "**utile**" in messages[1]["content"] and "été" in messages[1]["content"]
    assert provider.streams[0].closed
    assert "attachment_text" not in messages[0]


def test_followup_uses_saved_roles_and_raw_content(client, csrf, provider):
    events(send(client, csrf, "Question 1"))
    events(send(client, csrf, "Question 2"))
    messages = provider.calls[-1]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert "**utile**" in messages[2]["content"]
    assert messages[-1]["content"] == "Question 2"


@pytest.mark.parametrize("value", [None, "", "  ", 123, [], {}, True, "x" * 8001],
                         ids=["null", "empty", "whitespace", "number", "array", "object", "boolean", "too_long"])
def test_invalid_messages(client, csrf, value):
    assert send(client, csrf, value).status_code == 400


def test_json_validation_and_csrf(client, csrf):
    assert client.post("/api/chat", data="abc", headers=csrf).status_code == 415
    assert client.post("/api/chat", data="{", content_type="application/json", headers=csrf).status_code == 400
    assert client.post("/api/chat", json=["hello"], headers=csrf).status_code == 400
    assert client.post("/api/chat", json={"message": "hello"}).status_code == 403
    assert client.delete("/api/conversation", headers={"X-CSRF-Token": "wrong"}).status_code == 403


def test_missing_key_keeps_app_usable(app, client, csrf):
    app.config["AI_CLIENT_FACTORY"] = None
    response = send(client, csrf)
    assert response.status_code == 503 and response.json["code"] == "missing_key"
    assert client.get("/").status_code == 200
    assert client.get("/api/conversation").json["configured"] is False
    assert client.get("/api/conversation/export").status_code == 200


@pytest.mark.parametrize("mode,status,code", [("auth", 401, "invalid_key"), ("limit", 429, "rate_limit"),
                                             ("timeout", 504, "timeout"), ("connection", 503, "connection_error")])
def test_provider_errors_and_retry(client, csrf, provider, mode, status, code):
    provider.mode = mode
    response = send(client, csrf)
    assert response.status_code == status and response.json["code"] == code
    assert b"secret-must-not-leak" not in response.data
    assert client.get("/api/conversation").json["messages"] == []
    provider.mode = "ok"
    assert events(send(client, csrf))[-1]["type"] == "done"
    assert len(provider.calls[-1]["messages"]) == 2


@pytest.mark.parametrize("mode", ["broken", "empty"])
def test_stream_failure_never_poison_history(client, csrf, provider, mode):
    provider.mode = mode
    response = send(client, csrf)
    assert events(response)[-1]["type"] == "error"
    assert client.get("/api/conversation").json["messages"] == []
    provider.mode = "ok"
    assert events(send(client, csrf, "Nouvelle question"))[-1]["type"] == "done"
    assert [m["role"] for m in provider.calls[-1]["messages"]] == ["system", "user"]


@pytest.mark.parametrize("specialty", list(SPECIALTIES))
def test_specialty_affects_prompt_and_is_persisted(client, csrf, provider, specialty):
    assert client.patch("/api/conversation", json={"specialty": specialty}, headers=csrf).status_code == 200
    events(send(client, csrf))
    assert SPECIALTIES[specialty][1] in provider.calls[-1]["messages"][0]["content"]
    assert client.get("/api/conversation").json["specialty"] == specialty


@pytest.mark.parametrize("value", ["unknown", [], {}, None, "'; DROP TABLE messages; --"])
def test_invalid_specialty(client, csrf, value):
    assert client.patch("/api/conversation", json={"specialty": value}, headers=csrf).status_code == 400


def test_ratings_comments_and_clear(client, csrf, app):
    events(send(client, csrf))
    messages = client.get("/api/conversation").json["messages"]
    user_id, answer_id = [m["id"] for m in messages]
    assert client.put(f"/api/messages/{user_id}/rating", json={"score": 1}, headers=csrf).status_code == 404
    url = f"/api/messages/{answer_id}/rating"
    assert client.put(url, json={"score": 1, "comment": "Très clair"}, headers=csrf).status_code == 200
    saved = client.get("/api/conversation").json["messages"][1]
    assert (saved["score"], saved["comment"]) == (1, "Très clair")
    client.put(url, json={"score": -1, "comment": "À détailler"}, headers=csrf)
    exported = client.get("/api/conversation/export?format=json").json
    assert exported["messages"][1]["score"] == -1
    assert client.delete("/api/conversation", headers=csrf).status_code == 200
    assert client.get("/api/conversation").json["messages"] == []
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM ratings").fetchone()[0] == 0
        assert get_db().execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert client.put(url, json={"score": 1}, headers=csrf).status_code == 404


def test_rating_can_be_removed(client, csrf):
    answer_id = events(send(client, csrf))[-1]["message_id"]
    url = f"/api/messages/{answer_id}/rating"
    client.put(url, json={"score": 1}, headers=csrf)
    client.put(url, json={"score": None, "comment": ""}, headers=csrf)
    assert client.get("/api/conversation").json["messages"][1]["score"] is None


@pytest.mark.parametrize("payload", [{"score": 5}, {"score": True}, {"score": "1"}, {"score": []},
                                    {"score": 1, "comment": "x" * 1001}, {"comment": 42}])
def test_rating_validation(client, csrf, payload):
    answer_id = events(send(client, csrf))[-1]["message_id"]
    assert client.put(f"/api/messages/{answer_id}/rating", json=payload, headers=csrf).status_code == 400


@pytest.mark.parametrize("format_name,mimetype", [("json", "application/json"), ("txt", "text/plain"), ("md", "text/markdown")])
def test_exports(client, csrf, format_name, mimetype):
    events(send(client, csrf, "Mon été"))
    response = client.get("/api/conversation/export?format=" + format_name)
    assert response.status_code == 200
    assert response.mimetype == mimetype
    assert "attachment;" in response.headers["Content-Disposition"]
    assert "Mon été" in response.data.decode("utf-8")
    assert "**utile**" in response.data.decode("utf-8")
    assert "csrf" not in response.data.decode("utf-8")
    assert client.get("/api/conversation/export?format=exe").status_code == 400


def test_browser_isolation(app, client, csrf):
    answer_id = events(send(client, csrf, "Private message"))[-1]["message_id"]
    other = app.test_client()
    bootstrap = other.get("/api/conversation").json
    assert bootstrap["messages"] == []
    other_csrf = {"X-CSRF-Token": bootstrap["csrf_token"]}
    assert other.put(f"/api/messages/{answer_id}/rating", json={"score": 1}, headers=other_csrf).status_code == 404
    other.delete("/api/conversation", headers=other_csrf)
    assert len(client.get("/api/conversation").json["messages"]) == 2
    assert b"Private message" not in other.get("/api/conversation/export").data


def test_persistence_after_app_restart(app, client, csrf):
    events(send(client, csrf, "Encore là"))
    cookie = client.get_cookie("session")
    restarted = create_app({**app.config, "TESTING": True})
    new_client = restarted.test_client()
    new_client.set_cookie("session", cookie.value)
    assert new_client.get("/api/conversation").json["messages"][0]["content"] == "Encore là"


def test_concurrent_turn_rejected_and_clear_unlocks(app, client, csrf):
    with client.session_transaction() as cookie:
        owner = cookie["owner"]
    with app.app_context():
        conversation = conversation_for(owner)
        token = claim_turn(conversation["id"])
        assert token
    assert send(client, csrf).status_code == 409
    assert client.patch("/api/conversation", json={"specialty": "python"}, headers=csrf).status_code == 409
    client.delete("/api/conversation", headers=csrf)
    assert events(send(client, csrf))[-1]["type"] == "done"


def test_clear_during_stream_cannot_restore_messages(app, client, csrf):
    cookie = client.get_cookie("session")
    other_tab = app.test_client()
    other_tab.set_cookie("session", cookie.value)
    response = send(client, csrf, buffered=False)
    assert next(response.response).decode().strip() == '{"type": "start"}'
    assert other_tab.delete("/api/conversation", headers=csrf).status_code == 200
    remaining = [json.loads(chunk) for chunk in response.response]
    assert remaining[-1]["type"] == "error" and remaining[-1]["code"] == "cancelled"
    response.close()
    assert other_tab.get("/api/conversation").json["messages"] == []


def test_abandoned_stream_closes_provider_and_releases_lease(app, client, csrf, provider):
    response = send(client, csrf, buffered=False)
    next(response.response)
    response.close()
    assert provider.streams[-1].closed
    assert events(send(client, csrf))[-1]["type"] == "done"


@pytest.mark.parametrize("name,content", [("cours.txt", "Idée principale : simplicité.".encode()),
                                          ("notes.md", b"# Ideas\nReadable notes"),
                                          ("data.csv", b"name,value\na,1\nb,2"),
                                          ("windows.txt", "Un résumé français".encode("cp1252"))])
def test_text_upload_and_followup(client, csrf, provider, name, content):
    response = client.post("/api/chat", data={"file": (io.BytesIO(content), name)}, headers=csrf)
    assert events(response)[-1]["type"] == "done"
    sent = provider.calls[-1]["messages"][-1]["content"]
    assert "<document_a_analyser>" in sent and name in sent
    history = client.get("/api/conversation").json["messages"]
    assert history[0]["attachment_name"] == name
    events(send(client, csrf, "Donne plus de détails sur le document"))
    assert "<document_a_analyser>" in provider.calls[-1]["messages"][1]["content"]


def test_docx_upload(client, csrf, provider):
    data = io.BytesIO()
    document = Document()
    document.add_paragraph("Un cours sur SQLite.")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "Une table utile."
    document.save(data)
    data.seek(0)
    response = client.post("/api/chat", data={"file": (data, "cours.docx"), "message": "Résume en 2 phrases"}, headers=csrf)
    assert events(response)[-1]["type"] == "done"
    assert "Une table utile" in provider.calls[-1]["messages"][-1]["content"]


def pdf_bytes(text=None, pages=1, encrypted=False):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=300, height=300)
        if text:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 20 200 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("password")
    data = io.BytesIO()
    writer.write(data)
    data.seek(0)
    return data


def test_pdf_upload(client, csrf, provider):
    response = client.post("/api/chat", data={"file": (pdf_bytes("Useful text in a PDF"), "cours.pdf")}, headers=csrf)
    assert events(response)[-1]["type"] == "done"
    assert "Useful text in a PDF" in provider.calls[-1]["messages"][-1]["content"]


@pytest.mark.parametrize("name,data", [("bad.exe", b"abc"), ("empty.txt", b""), ("bad.pdf", b"not a pdf"),
                                      ("bad.docx", b"not a docx"), ("binary.txt", b"abc\x00"),
                                      ("long.txt", b"a" * 40_001)],
                         ids=["unsupported", "empty", "broken_pdf", "broken_docx", "binary", "too_long"])
def test_invalid_uploads(client, csrf, name, data):
    response = client.post("/api/chat", data={"file": (io.BytesIO(data), name)}, headers=csrf)
    assert response.status_code == 400 and response.json["code"] == "invalid_document"


@pytest.mark.parametrize("kind", ["scanned", "encrypted", "too_many_pages"])
def test_unreadable_pdfs(client, csrf, kind):
    data = pdf_bytes(encrypted=kind == "encrypted", pages=51 if kind == "too_many_pages" else 1)
    assert client.post("/api/chat", data={"file": (data, "cours.pdf")}, headers=csrf).status_code == 400


def test_upload_limit(client, csrf):
    response = client.post("/api/chat", data={"file": (io.BytesIO(b"a" * (6 * 1024 * 1024)), "big.txt")}, headers=csrf)
    assert response.status_code == 413 and response.json["code"] == "file_too_large"


def test_filename_is_safe_and_upload_not_saved_to_disk(client, csrf):
    response = client.post("/api/chat", data={"file": (io.BytesIO(b"Some notes"), "../../other/file.txt")}, headers=csrf)
    assert events(response)[-1]["type"] == "done"
    assert client.get("/api/conversation").json["messages"][0]["attachment_name"] == "file.txt"


def test_context_budget_preserves_complete_turns():
    history = []
    for i in range(20):
        history.extend([{"role": "user", "content": str(i) + "a" * 5000}, {"role": "assistant", "content": "b" * 5000}])
    context = build_context(history, "general", "Next")
    assert sum(len(m["content"]) for m in context) <= 56_000
    assert context[1]["role"] == "user" and context[-1]["content"] == "Next"
    assert all(context[i]["role"] == ("user" if i % 2 else "assistant") for i in range(1, len(context)))
