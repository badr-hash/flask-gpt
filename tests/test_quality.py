import io
import json
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from answer_quality import ANSWER_LEVELS, application_date, system_prompt
from chat_service import user_content
from conftest import events, send
from document_reader import label_excerpts
from evals.scoring import check_answer, python_average_correct
from test_app import pdf_bytes


@pytest.mark.parametrize("level", list(ANSWER_LEVELS))
def test_answer_level_changes_prompt_and_persists(client, csrf, provider, level):
    response = client.patch("/api/conversation", json={"answer_level": level}, headers=csrf)
    assert response.status_code == 200
    assert response.json["specialty"] == "general"
    events(send(client, csrf, "Explique une API"))
    prompt = provider.calls[-1]["messages"][0]["content"]
    assert ANSWER_LEVELS[level][1] in prompt
    assert client.get("/api/conversation").json["answer_level"] == level
    new = client.post("/api/conversations", headers=csrf).json
    assert new["answer_level"] == level


@pytest.mark.parametrize("level", ["expert", "", None, [], {}, True])
def test_answer_level_validation(client, csrf, level):
    assert client.patch("/api/conversation", json={"answer_level": level}, headers=csrf).status_code == 400


def test_each_chat_keeps_its_own_level(client, csrf):
    first = client.get("/api/conversation").json["conversation_id"]
    client.patch("/api/conversation", json={"answer_level": "beginner"}, headers=csrf)
    client.post("/api/conversations", headers=csrf)
    client.patch("/api/conversation", json={"answer_level": "advanced"}, headers=csrf)
    data = client.post(f"/api/conversations/{first}/select", headers=csrf).json
    assert data["answer_level"] == "beginner"


def test_current_date_is_trusted_context_not_taken_from_old_answers():
    prompt = system_prompt("Assistant", current_date="2026-10-27")
    assert "2026-10-27" in prompt and "Africa/Casablanca" in prompt
    assert "2024" not in prompt
    assert application_date() in system_prompt("Assistant")


def test_actionable_feedback_restored_and_exported(client, csrf):
    message_id = events(send(client, csrf))[-1]["message_id"]
    url = f"/api/messages/{message_id}/rating"
    response = client.put(url, json={"score": None, "reasons": ["incorrect", "too_vague"], "comment": "Le chiffre est inexact."}, headers=csrf)
    assert response.status_code == 200 and response.json["score"] == -1
    saved = client.get("/api/conversation").json["messages"][1]
    assert saved["reasons"] == ["incorrect", "too_vague"]
    assert client.get("/api/conversation/export?format=json").json["messages"][1]["reasons"] == saved["reasons"]
    assert "Informations incorrectes" in client.get("/api/conversation/export?format=md").text
    response = client.put(url, json={"score": 1, "reasons": []}, headers=csrf)
    assert response.status_code == 200 and response.json["reasons"] == []


@pytest.mark.parametrize("reasons", [None, "incorrect", {}, ["unknown"], [True], [["incorrect"]],
                                    ["incorrect", "incorrect"], ["incorrect"] * 6])
def test_invalid_feedback_reasons(client, csrf, reasons):
    message_id = events(send(client, csrf))[-1]["message_id"]
    assert client.put(f"/api/messages/{message_id}/rating", json={"score": -1, "reasons": reasons}, headers=csrf).status_code == 400


def test_positive_rating_with_negative_reasons_is_rejected(client, csrf):
    message_id = events(send(client, csrf))[-1]["message_id"]
    assert client.put(f"/api/messages/{message_id}/rating", json={"score": 1, "reasons": ["incorrect"]}, headers=csrf).status_code == 400


def test_pdf_page_labels_match_real_pages_and_followups(client, csrf, provider):
    writer = PdfWriter()
    writer.append(pdf_bytes("Budget: 12000 euros."))
    writer.append(pdf_bytes("Delivery: March 15, 2027."))
    data = io.BytesIO()
    writer.write(data)
    data.seek(0)
    response = client.post("/api/chat", data={"file": (data, "plan.pdf")}, headers=csrf)
    assert events(response)[-1]["type"] == "done"
    content = provider.calls[-1]["messages"][-1]["content"]
    assert "[Page 1]\nBudget: 12000 euros." in content
    assert "[Page 2]\nDelivery: March 15, 2027." in content
    events(send(client, csrf, "Quel est le budget ?"))
    assert "[Page 1]" in provider.calls[-1]["messages"][1]["content"]


def test_non_pdf_sources_have_passage_labels_not_fake_pages(client, csrf, provider):
    text = ("Les données sont stockées dans SQLite.\n" * 70).encode()
    response = client.post("/api/chat", data={"file": (io.BytesIO(text), "notes.txt")}, headers=csrf)
    assert events(response)[-1]["type"] == "done"
    content = provider.calls[-1]["messages"][-1]["content"]
    assert "[Extrait 1]" in content and "[Extrait 2]" in content
    assert "[Page " not in content
    assert content.count("Les données sont stockées dans SQLite.") == 70
    legacy = user_content("Quel budget ?", "ancien.pdf", "Le budget est de 12000 euros.")
    assert "[Extrait 1]" in legacy and "[Page " not in legacy


def test_truncated_stream_is_not_saved_as_a_complete_answer(client, csrf, provider):
    class TruncatedStream:
        def __iter__(self):
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Début…"), finish_reason=None)])
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason="length")])
        def close(self):
            pass
    provider.chat.completions.create = lambda **kwargs: TruncatedStream()
    result = events(send(client, csrf))
    assert result[-1]["type"] == "error" and result[-1]["code"] == "truncated_response"
    assert client.get("/api/conversation").json["messages"] == []


def test_scorer_checks_behavior_and_rejects_untrusted_code():
    assert python_average_correct("```python\ndef average(values):\n    return sum(values) / len(values) if values else None\n```")
    assert not python_average_correct("def average(values):\n    return sum(values) / len(values)")
    assert not python_average_correct("import os\ndef average(values):\n    os.system('echo forbidden')")
    assert not python_average_correct("def average(values):\n    while True: pass")
    assert not python_average_correct("def average(values):\n    return values.__class__")
    check = [{"kind": "regex", "pattern": "Rabat", "dimension": "accuracy", "label": "Correct"}]
    assert check_answer("Rabat", check)[0]["passed"]
    assert not check_answer("Rabat", check, complete=False)[0]["passed"]
    citation = [{"kind": "regex", "pattern": r"\[Page 2\]", "dimension": "completeness", "label": "Source"}]
    assert check_answer("Livraison le 15 mars [Page\u202f2]", citation)[0]["passed"]


def test_benchmark_dataset_is_valid():
    from pathlib import Path
    cases = json.loads((Path(__file__).resolve().parents[1] / "evals/cases.json").read_text(encoding="utf-8"))
    assert len(cases) >= 12 and len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        assert case["reference"] and case["checks"]
        check_answer("", case["checks"])
