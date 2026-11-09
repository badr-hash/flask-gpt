"""FlaskGPT: a persistent, streaming Groq chat application."""

import hmac
import json
import os
import secrets
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, session, stream_with_context
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from chat_service import ChatError, SPECIALTIES, build_context, open_stream, provider_error
from answer_quality import ANSWER_LEVELS, FEEDBACK_REASONS, PROMPT_VERSION
from web_answers import SUPPORTED_WEB_MODELS
from document_reader import DocumentError, MAX_FILE_BYTES, extract_document
from storage import (cancel_turn, claim_turn, clear_conversation, close_db, conversation_for, conversations_for,
                     create_conversation, delete_conversation, get_db, init_db, messages_for,
                     release_turn, save_turn, select_conversation, timestamp)


def create_app(test_config=None):
    load_dotenv(Path(__file__).with_name(".env"))
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY"),
        DATABASE=os.getenv("DATABASE_PATH") or str(Path(app.instance_path) / "chat.sqlite3"),
        GROQ_API_KEY=os.getenv("GROQ_API_KEY", ""),
        GROQ_MODEL=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        MAX_CONTENT_LENGTH=MAX_FILE_BYTES + 128 * 1024,
        MAX_FORM_MEMORY_SIZE=64 * 1024,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    if not app.config["SECRET_KEY"]:
        secret_path = Path(app.instance_path) / ".session-secret"
        try:
            fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w", encoding="ascii") as stream:
                stream.write(secrets.token_hex(32))
        app.config["SECRET_KEY"] = secret_path.read_text(encoding="ascii").strip()

    app.teardown_appcontext(close_db)
    init_db(app)

    @app.before_request
    def identify_browser():
        if request.endpoint == "static":
            return
        if "owner" not in session:
            session["owner"] = uuid4().hex
            session["csrf"] = secrets.token_urlsafe(32)
            session.permanent = True
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied = request.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(supplied, session.get("csrf", "")):
                return jsonify(error="Session expirée. Actualisez la page et réessayez.", code="csrf"), 403

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        return response

    def current_conversation():
        conversation_id = request.headers.get("X-Conversation-ID") or request.args.get("conversation_id")
        conversation = conversation_for(session["owner"], conversation_id)
        if conversation is None:
            raise ChatError("Cette conversation n'existe plus. Choisissez-en une dans l'historique.", 404, "not_found")
        return conversation

    def conversation_payload(conversation):
        return dict(
            conversation_id=conversation["id"],
            conversations=conversations_for(session["owner"]),
            messages=messages_for(conversation["id"]), specialty=conversation["specialty"],
            answer_level=conversation["answer_level"],
            answer_levels=[{"id": key, "label": value[0]} for key, value in ANSWER_LEVELS.items()],
            feedback_reasons=FEEDBACK_REASONS, prompt_version=PROMPT_VERSION,
            web_search_available=app.config["GROQ_MODEL"] in SUPPORTED_WEB_MODELS,
            specialties=[{"id": key, "label": value[0]} for key, value in SPECIALTIES.items()],
            csrf_token=session["csrf"],
            configured=bool(app.config["GROQ_API_KEY"] or app.config.get("AI_CLIENT_FACTORY")),
            model=app.config["GROQ_MODEL"],
        )

    @app.get("/")
    def home():
        return render_template("index.html")

    @app.get("/api/conversation")
    def get_conversation():
        return jsonify(conversation_payload(current_conversation()))

    @app.get("/api/conversations")
    def list_conversations():
        conversation = current_conversation()
        return jsonify(conversations=conversations_for(session["owner"]), active_id=conversation["id"])

    @app.post("/api/conversations")
    def new_conversation():
        previous = current_conversation()
        conversation = create_conversation(session["owner"], previous["specialty"], previous["answer_level"])
        select_conversation(session["owner"], conversation["id"], previous["id"])
        return jsonify(conversation_payload(conversation)), 201

    @app.post("/api/conversations/<conversation_id>/select")
    def choose_conversation(conversation_id):
        previous_id = request.headers.get("X-Conversation-ID")
        conversation = select_conversation(session["owner"], conversation_id, previous_id)
        if conversation is None:
            raise ChatError("Conversation introuvable.", 404, "not_found")
        return jsonify(conversation_payload(conversation))

    @app.delete("/api/conversations/<conversation_id>")
    def remove_conversation(conversation_id):
        if not delete_conversation(session["owner"], conversation_id):
            raise ChatError("Conversation introuvable.", 404, "not_found")
        previous_id = request.headers.get("X-Conversation-ID")
        remaining = conversation_for(session["owner"], previous_id) if previous_id != conversation_id and previous_id else None
        return jsonify(conversation_payload(remaining or conversation_for(session["owner"])))

    def json_object():
        if not request.is_json:
            raise ChatError("Le format JSON est requis.", 415, "invalid_json")
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ChatError("Le JSON doit être un objet valide.", 400, "invalid_json")
        return data

    @app.patch("/api/conversation")
    def update_specialty():
        data = json_object()
        conversation = current_conversation()
        specialty = data.get("specialty", conversation["specialty"])
        answer_level = data.get("answer_level", conversation["answer_level"])
        if not (set(data) & {"specialty", "answer_level"}):
            raise ChatError("Choisissez une spécialité ou un niveau d'explication.", 400, "invalid_settings")
        if not isinstance(specialty, str) or specialty not in SPECIALTIES:
            raise ChatError("Choisissez une spécialité valide.", 400, "invalid_specialty")
        if not isinstance(answer_level, str) or answer_level not in ANSWER_LEVELS:
            raise ChatError("Choisissez un niveau d'explication valide.", 400, "invalid_answer_level")
        if conversation["generation"]:
            raise ChatError("Attendez la fin de la réponse avant de changer de spécialité.", 409, "busy")
        db = get_db()
        with db:
            db.execute("UPDATE conversations SET specialty = ?, answer_level = ? WHERE id = ?",
                       (specialty, answer_level, conversation["id"]))
        return jsonify(specialty=specialty, answer_level=answer_level)

    @app.delete("/api/conversation")
    def clear_current_conversation():
        clear_conversation(current_conversation()["id"])
        return jsonify(ok=True)

    @app.post("/api/conversation/cancel")
    def cancel_current_turn():
        cancel_turn(current_conversation()["id"])
        return jsonify(ok=True)

    @app.post("/prompt")
    @app.post("/api/chat")
    def chat():
        filename = source = None
        web_search = False
        if request.mimetype == "multipart/form-data":
            if len(request.files) != 1 or "file" not in request.files:
                raise ChatError("Joignez un seul fichier à résumer.", 400, "invalid_upload")
            filename, source = extract_document(request.files["file"])
            question = request.form.get("message", "").strip() or (
                "Résume ce document en français : idées principales, points clés et conclusion."
            )
        else:
            data = json_object()
            question = data.get("message")
            web_search = data.get("web_search", False)
            if type(web_search) is not bool:
                raise ChatError("L'option de recherche Web doit être vraie ou fausse.", 400, "invalid_web_search")
        if not isinstance(question, str) or not question.strip():
            raise ChatError("Écrivez un message ou joignez un fichier à résumer.", 400, "empty_message")
        question = question.strip()
        if len(question) > 8000:
            raise ChatError("Le message dépasse 8 000 caractères.", 400, "message_too_long")
        conversation = current_conversation()
        conversation_id = conversation["id"]
        token = claim_turn(conversation_id)
        if not token:
            raise ChatError("Une réponse est déjà en cours dans cette conversation.", 409, "busy")
        try:
            history = messages_for(conversation_id, include_source=True)
            context = build_context(history, conversation["specialty"], question, filename, source,
                                    answer_level=conversation["answer_level"], web_access=web_search)
            upstream, client = open_stream(context, web_search=web_search)
        except Exception:
            release_turn(conversation_id, token)
            raise

        def event(kind, **values):
            return json.dumps({"type": kind, **values}, ensure_ascii=False) + "\n"

        @stream_with_context
        def generate():
            answer = ""
            started = time.monotonic()
            try:
                yield event("start")
                for chunk in upstream:
                    if time.monotonic() - started > 150:
                        raise ChatError("La réponse a dépassé le délai autorisé. Réessayez avec une demande plus courte.", 504, "timeout")
                    if not chunk.choices:
                        continue
                    if getattr(chunk.choices[0], "finish_reason", None) == "length":
                        raise ChatError("La réponse a atteint sa limite de longueur. Demandez une réponse plus courte ou divisez la question.", 502, "truncated_response")
                    text = chunk.choices[0].delta.content or ""
                    if text:
                        answer += text
                        if len(answer) > 80_000:
                            raise ChatError("La réponse est trop longue. Demandez une réponse plus courte.")
                        yield event("delta", text=text)
                if not answer.strip():
                    raise ChatError("Le modèle n'a retourné aucun texte. Réessayez avec une demande plus courte.", 502, "empty_response")
                message_id = save_turn(conversation_id, token, question, answer, filename, source)
                if message_id is None:
                    raise ChatError("Cette conversation a été effacée. La réponse a été annulée.", 409, "cancelled")
                yield event("done", message_id=message_id)
            except GeneratorExit:
                raise
            except Exception as error:
                safe = error if isinstance(error, ChatError) else provider_error(error)
                app.logger.warning("Chat stream failed: %s", safe.code)
                yield event("error", error=str(safe), code=safe.code)
            finally:
                try:
                    upstream.close()
                except Exception:
                    pass
                if client:
                    client.close()
                release_turn(conversation_id, token)

        return Response(generate(), content_type="application/x-ndjson; charset=utf-8",
                        headers={"X-Accel-Buffering": "no"})

    @app.put("/api/messages/<int:message_id>/rating")
    def rate_message(message_id):
        data = json_object()
        score = data.get("score")
        comment = data.get("comment", "")
        reasons = data.get("reasons", [])
        if score is not None and (type(score) is not int or score not in {-1, 1}):
            raise ChatError("L'évaluation doit être positive ou négative.", 400, "invalid_rating")
        if not isinstance(comment, str) or len(comment) > 1000:
            raise ChatError("Le commentaire doit contenir au maximum 1 000 caractères.", 400, "invalid_rating")
        if (not isinstance(reasons, list) or len(reasons) > len(FEEDBACK_REASONS)
                or any(not isinstance(reason, str) or reason not in FEEDBACK_REASONS for reason in reasons)
                or len(set(reasons)) != len(reasons) or (score == 1 and reasons)):
            raise ChatError("Choisissez des motifs d'amélioration valides.", 400, "invalid_rating")
        if reasons:
            score = -1
        conversation = current_conversation()
        db = get_db()
        message = db.execute(
            "SELECT id FROM messages WHERE id = ? AND conversation_id = ? AND role = 'assistant'",
            (message_id, conversation["id"]),
        ).fetchone()
        if not message:
            raise ChatError("Réponse introuvable dans votre conversation.", 404, "not_found")
        comment = comment.strip()
        with db:
            if score is None and not comment and not reasons:
                db.execute("DELETE FROM ratings WHERE message_id = ?", (message_id,))
            else:
                db.execute(
                    "INSERT INTO ratings(message_id, score, comment, reasons, updated_at) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(message_id) DO UPDATE SET score = excluded.score, "
                    "comment = excluded.comment, reasons = excluded.reasons, updated_at = excluded.updated_at",
                    (message_id, score, comment, json.dumps(reasons), timestamp()),
                )
        return jsonify(score=score, comment=comment, reasons=reasons)

    @app.get("/api/conversation/export")
    def export_conversation():
        format_name = request.args.get("format", "md")
        if format_name not in {"txt", "md", "json"}:
            raise ChatError("Formats disponibles : TXT, Markdown et JSON.", 400, "invalid_format")
        conversation = current_conversation()
        messages = messages_for(conversation["id"])
        label = SPECIALTIES[conversation["specialty"]][0]
        if format_name == "json":
            content = json.dumps({"format_version": 1, "exported_at": timestamp(),
                                  "specialty": label, "answer_level": conversation["answer_level"],
                                  "messages": messages}, ensure_ascii=False, indent=2)
            mimetype = "application/json"
        else:
            prefix = "# " if format_name == "md" else ""
            lines = [f"{prefix}FlaskGPT", f"Spécialité : {label}",
                     f"Niveau : {ANSWER_LEVELS[conversation['answer_level']][0]}", f"Export : {timestamp()}", ""]
            for message in messages:
                role = "Vous" if message["role"] == "user" else "FlaskGPT"
                lines.extend([f"{'## ' if format_name == 'md' else ''}{role}", message["content"]])
                if message["attachment_name"]:
                    lines.append("Fichier joint : " + message["attachment_name"])
                if message["score"] is not None:
                    lines.append("Évaluation : " + ("Utile" if message["score"] == 1 else "À améliorer"))
                if message["comment"]:
                    lines.append("Commentaire : " + message["comment"])
                if message["reasons"]:
                    lines.append("Motifs : " + ", ".join(FEEDBACK_REASONS[reason] for reason in message["reasons"]))
                lines.append("")
            content = "\n".join(lines)
            mimetype = "text/markdown" if format_name == "md" else "text/plain"
        return Response(content, content_type=mimetype + "; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="flaskgpt-conversation.{format_name}"',
        })

    @app.errorhandler(ChatError)
    def chat_error(error):
        return jsonify(error=str(error), code=error.code), error.status

    @app.errorhandler(DocumentError)
    def document_error(error):
        return jsonify(error=str(error), code="invalid_document"), 400

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_error):
        return jsonify(error="Le fichier dépasse la limite de 5 Mo.", code="file_too_large"), 413

    @app.errorhandler(Exception)
    def unexpected_error(error):
        if isinstance(error, HTTPException):
            return jsonify(error=error.description, code="http_error"), error.code
        app.logger.error("Application error: %s", type(error).__name__)
        return jsonify(error="Une erreur du serveur est survenue. Réessayez.", code="server_error"), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
