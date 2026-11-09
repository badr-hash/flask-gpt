import json
import sqlite3

from app import create_app
from conftest import events, send
from storage import get_db


def chat_headers(csrf, conversation_id):
    return {**csrf, "X-Conversation-ID": conversation_id}


def new_chat(client, csrf):
    response = client.post("/api/conversations", headers=csrf)
    assert response.status_code == 201
    return response.json


def test_new_chats_preserve_existing_messages_and_titles(client, csrf):
    events(send(client, csrf, "Ma première question"))
    first = client.get("/api/conversation").json
    second = new_chat(client, csrf)
    assert second["conversation_id"] != first["conversation_id"]
    assert second["messages"] == []
    assert len(second["conversations"]) == 2
    assert next(c for c in second["conversations"] if c["id"] == first["conversation_id"])["title"] == "Ma première question"
    first_headers = chat_headers(csrf, first["conversation_id"])
    old = client.get("/api/conversation", headers=first_headers).json
    assert old["messages"] == first["messages"]


def test_selection_restores_messages_specialty_and_ratings(client, csrf):
    first = client.get("/api/conversation").json["conversation_id"]
    client.patch("/api/conversation", json={"specialty": "python"}, headers=csrf)
    answer_id = events(send(client, csrf, "Python"))[-1]["message_id"]
    client.put(f"/api/messages/{answer_id}/rating", json={"score": 1, "comment": "Utile"}, headers=csrf)
    second = new_chat(client, csrf)
    client.patch("/api/conversation", json={"specialty": "writing"}, headers=csrf)
    events(send(client, csrf, "Rédaction"))
    selected = client.post(f"/api/conversations/{first}/select", headers=csrf)
    assert selected.status_code == 200
    assert selected.json["specialty"] == "python"
    assert selected.json["messages"][1]["score"] == 1
    assert selected.json["messages"][1]["comment"] == "Utile"
    assert client.get("/api/conversation").json["conversation_id"] == first
    other = client.get("/api/conversation", headers=chat_headers(csrf, second["conversation_id"])).json
    assert other["specialty"] == "writing" and other["messages"][0]["content"] == "Rédaction"


def test_list_is_ordered_by_latest_exchange(client, csrf):
    first = client.get("/api/conversation").json["conversation_id"]
    events(send(client, csrf, "Première"))
    second = new_chat(client, csrf)["conversation_id"]
    events(send(client, csrf, "Deuxième"))
    events(send(client, chat_headers(csrf, first), "Retour à la première"))
    history = client.get("/api/conversations").json["conversations"]
    assert [c["id"] for c in history] == [first, second]
    assert history[0]["exchange_count"] == 2 and history[1]["exchange_count"] == 1


def test_delete_inactive_chat_keeps_current_and_cascades_children(app, client, csrf):
    first = client.get("/api/conversation").json["conversation_id"]
    answer = events(send(client, csrf, "À supprimer"))[-1]["message_id"]
    client.put(f"/api/messages/{answer}/rating", json={"score": -1}, headers=csrf)
    second = new_chat(client, csrf)["conversation_id"]
    events(send(client, csrf, "À garder"))
    response = client.delete(f"/api/conversations/{first}", headers=chat_headers(csrf, second))
    assert response.status_code == 200
    assert response.json["conversation_id"] == second
    assert response.json["messages"][0]["content"] == "À garder"
    assert [c["id"] for c in response.json["conversations"]] == [second]
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (first,)).fetchone()[0] == 0
        assert get_db().execute("SELECT COUNT(*) FROM ratings WHERE message_id = ?", (answer,)).fetchone()[0] == 0


def test_delete_active_selects_remaining_chat_and_last_delete_opens_empty(client, csrf):
    first = client.get("/api/conversation").json["conversation_id"]
    events(send(client, csrf, "Conversation conservée"))
    second = new_chat(client, csrf)["conversation_id"]
    result = client.delete(f"/api/conversations/{second}", headers=chat_headers(csrf, second)).json
    assert result["conversation_id"] == first
    assert result["messages"][0]["content"] == "Conversation conservée"
    result = client.delete(f"/api/conversations/{first}", headers=chat_headers(csrf, first)).json
    assert result["conversation_id"] not in {first, second}
    assert result["messages"] == [] and len(result["conversations"]) == 1
    assert client.get("/api/conversation").json["conversation_id"] == result["conversation_id"]


def test_clearing_messages_does_not_delete_other_conversations(client, csrf):
    first = client.get("/api/conversation").json["conversation_id"]
    events(send(client, csrf, "Conservé"))
    second = new_chat(client, csrf)["conversation_id"]
    events(send(client, csrf, "Effacé"))
    client.delete("/api/conversation", headers=chat_headers(csrf, second))
    assert len(client.get("/api/conversations").json["conversations"]) == 2
    assert len(client.get("/api/conversation", headers=chat_headers(csrf, first)).json["messages"]) == 2


def test_other_sessions_cannot_list_select_delete_or_send_to_chats(app, client, csrf):
    first = client.get("/api/conversation").json["conversation_id"]
    events(send(client, csrf, "Conversation privée"))
    other = app.test_client()
    data = other.get("/api/conversation").json
    headers = {"X-CSRF-Token": data["csrf_token"], "X-Conversation-ID": first}
    assert first not in [c["id"] for c in data["conversations"]]
    assert other.get("/api/conversation", headers=headers).status_code == 404
    assert other.post(f"/api/conversations/{first}/select", headers=headers).status_code == 404
    assert other.delete(f"/api/conversations/{first}", headers=headers).status_code == 404
    assert other.post("/api/chat", json={"message": "Inject"}, headers=headers).status_code == 404
    assert other.get("/api/conversation/export?conversation_id=" + first).status_code == 404
    assert len(client.get("/api/conversation").json["messages"]) == 2


def test_tabs_pin_chat_export_and_ratings_to_the_viewed_conversation(client, csrf):
    first = client.get("/api/conversation").json["conversation_id"]
    first_headers = chat_headers(csrf, first)
    answer = events(send(client, first_headers, "Premier onglet"))[-1]["message_id"]
    second = new_chat(client, csrf)["conversation_id"]
    events(send(client, csrf, "Deuxième onglet"))
    events(send(client, first_headers, "Toujours le premier"))
    assert len(client.get("/api/conversation", headers=first_headers).json["messages"]) == 4
    assert client.get("/api/conversation").json["conversation_id"] == second
    assert client.put(f"/api/messages/{answer}/rating", json={"score": 1}, headers=first_headers).status_code == 200
    exported = client.get("/api/conversation/export?format=json&conversation_id=" + first).json
    assert len(exported["messages"]) == 4
    assert all("Deuxième onglet" not in m["content"] for m in exported["messages"])


def test_delete_during_stream_cannot_restore_deleted_chat(app, client, csrf):
    first = client.get("/api/conversation").json["conversation_id"]
    other = app.test_client()
    other.set_cookie("session", client.get_cookie("session").value)
    response = send(client, chat_headers(csrf, first), buffered=False)
    next(response.response)
    assert other.delete(f"/api/conversations/{first}", headers=chat_headers(csrf, first)).status_code == 200
    remaining = [json.loads(chunk) for chunk in response.response]
    assert remaining[-1]["code"] == "cancelled"
    response.close()
    assert first not in [c["id"] for c in other.get("/api/conversations").json["conversations"]]


def test_switch_during_stream_cancels_the_previous_generation(app, client, csrf):
    first = client.get("/api/conversation").json["conversation_id"]
    second = new_chat(client, csrf)["conversation_id"]
    client.post(f"/api/conversations/{first}/select", headers=csrf)
    other = app.test_client()
    other.set_cookie("session", client.get_cookie("session").value)
    response = send(client, chat_headers(csrf, first), buffered=False)
    next(response.response)
    assert other.post(f"/api/conversations/{second}/select", headers=chat_headers(csrf, first)).status_code == 200
    remaining = [json.loads(chunk) for chunk in response.response]
    assert remaining[-1]["code"] == "cancelled"
    response.close()
    assert other.get("/api/conversation", headers=chat_headers(csrf, first)).json["messages"] == []


def test_new_chat_while_streaming_cancels_old_turn(app, client, csrf):
    first = client.get("/api/conversation").json["conversation_id"]
    other = app.test_client()
    other.set_cookie("session", client.get_cookie("session").value)
    response = send(client, chat_headers(csrf, first), buffered=False)
    next(response.response)
    new_chat(other, chat_headers(csrf, first))
    remaining = [json.loads(chunk) for chunk in response.response]
    assert remaining[-1]["code"] == "cancelled"
    response.close()


def test_title_is_bounded_and_uses_first_question(client, csrf):
    events(send(client, csrf, "<script>alert(1)</script>\n" + "A" * 100))
    title = client.get("/api/conversations").json["conversations"][0]["title"]
    assert len(title) <= 60 and "\n" not in title
    events(send(client, csrf, "Ne remplace pas le titre"))
    assert client.get("/api/conversations").json["conversations"][0]["title"] == title


def test_legacy_database_migration_preserves_ids_messages_files_and_ratings(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE conversations(id TEXT PRIMARY KEY, owner TEXT NOT NULL UNIQUE,
                specialty TEXT NOT NULL DEFAULT 'general', revision INTEGER NOT NULL DEFAULT 0,
                generation TEXT, generation_started REAL, created_at TEXT NOT NULL);
            CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL, content TEXT NOT NULL, attachment_name TEXT,
                attachment_text TEXT, created_at TEXT NOT NULL);
            CREATE TABLE ratings(message_id INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
                score INTEGER, comment TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
            INSERT INTO conversations(id, owner, specialty, created_at)
                VALUES ('existing', 'existing-owner', 'python', '2026-10-27T12:00:00+00:00');
            INSERT INTO messages VALUES(1, 'existing', 'user', 'Mon document', 'notes.txt',
                'Texte extrait original', '2026-10-27T12:00:00+00:00');
            INSERT INTO messages VALUES(2, 'existing', 'assistant', 'Un résumé', NULL,
                NULL, '2026-10-27T12:00:01+00:00');
            INSERT INTO ratings VALUES(2, 1, 'Très utile', '2026-10-27T12:00:02+00:00');
        """)
    app = create_app({"TESTING": True, "DATABASE": str(path), "SECRET_KEY": "migration-test", "GROQ_API_KEY": ""})
    client = app.test_client()
    with client.session_transaction() as session:
        session["owner"] = "existing-owner"
        session["csrf"] = "migration-csrf"
    data = client.get("/api/conversation").json
    assert data["conversation_id"] == "existing" and data["specialty"] == "python"
    assert [m["id"] for m in data["messages"]] == [1, 2]
    assert data["messages"][1]["comment"] == "Très utile"
    assert path.with_suffix(".before-history.sqlite3").exists()
    with app.app_context():
        assert get_db().execute("SELECT attachment_text FROM messages WHERE id = 1").fetchone()[0] == "Texte extrait original"
        assert get_db().execute("PRAGMA foreign_key_check").fetchall() == []
    second = new_chat(client, {"X-CSRF-Token": "migration-csrf"})
    assert len(second["conversations"]) == 2
    # Restarting the app must neither repeat the migration nor change the selected chat.
    restarted = create_app({"TESTING": True, "DATABASE": str(path), "SECRET_KEY": "migration-test", "GROQ_API_KEY": ""})
    other = restarted.test_client()
    other.set_cookie("session", client.get_cookie("session").value)
    assert other.get("/api/conversation").json["conversation_id"] == second["conversation_id"]
