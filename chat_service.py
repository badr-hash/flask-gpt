"""Provider configuration, bounded conversation context, and safe errors."""

import re

from flask import current_app
from answer_quality import system_prompt
from document_reader import label_excerpts
from web_answers import CompletedWebStream, SUPPORTED_WEB_MODELS, web_answer
from openai import (
    APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError,
    BadRequestError, OpenAI, PermissionDeniedError, RateLimitError,
)

SPECIALTIES = {
    "general": ("Assistant général", "Tu es un assistant polyvalent, clair et rigoureux."),
    "python": ("Programmation Python", "Tu es un pédagogue expert en Python. Propose du code fiable, explique-le et signale les cas limites."),
    "web": ("Développement web", "Tu es expert en HTML, CSS, JavaScript et Flask. Privilégie les solutions accessibles et maintenables."),
    "data": ("Analyse de données", "Tu aides à analyser les données, les statistiques et les tableaux. Distingue les faits des hypothèses."),
    "math": ("Mathématiques", "Tu es un professeur de mathématiques. Explique les étapes et vérifie les résultats."),
    "writing": ("Rédaction & langues", "Tu aides à rédiger, corriger et traduire, en respectant le ton et le sens du texte."),
}


class ChatError(Exception):
    def __init__(self, message, status=502, code="provider_error"):
        super().__init__(message)
        self.status = status
        self.code = code


def provider_error(error):
    if isinstance(error, AuthenticationError):
        return ChatError("Clé API Groq invalide ou expirée. Corrigez GROQ_API_KEY dans .env, puis redémarrez le serveur.", 401, "invalid_key")
    if isinstance(error, PermissionDeniedError):
        return ChatError("Cette clé n'a pas accès au modèle. Vérifiez les autorisations de votre compte Groq.", 403, "permission_denied")
    if isinstance(error, RateLimitError):
        return ChatError("Limite Groq atteinte. Patientez un moment, puis réessayez.", 429, "rate_limit")
    if isinstance(error, APITimeoutError):
        return ChatError("Le service a mis trop de temps à répondre. Réessayez.", 504, "timeout")
    if isinstance(error, APIConnectionError):
        return ChatError("Connexion à Groq impossible. Vérifiez la connexion Internet du serveur.", 503, "connection_error")
    if isinstance(error, BadRequestError):
        return ChatError("Groq a refusé la demande. Raccourcissez la conversation ou vérifiez GROQ_MODEL.", 422, "invalid_request")
    if isinstance(error, APIStatusError):
        return ChatError("Le service Groq est momentanément indisponible. Réessayez plus tard.", 502, "provider_unavailable")
    return ChatError("La réponse a été interrompue. Votre conversation enregistrée reste disponible. Réessayez.")


def open_stream(messages, web_search=False):
    if web_search and current_app.config["GROQ_MODEL"] not in SUPPORTED_WEB_MODELS:
        raise ChatError("Le modèle configuré ne prend pas en charge la recherche Web.", 400, "unsupported_web_model")
    factory = current_app.config.get("AI_CLIENT_FACTORY")
    if factory:
        client = factory()
    else:
        key = (current_app.config.get("GROQ_API_KEY") or "").strip()
        if not key or key in {"your-groq-api-key", "your_groq_api_key", "gsk_your_key_here"}:
            raise ChatError("Ajoutez votre clé Groq dans le fichier .env (GROQ_API_KEY), puis redémarrez le serveur.", 503, "missing_key")
        client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1",
                        timeout=60.0, max_retries=0)
    try:
        options = dict(model=current_app.config["GROQ_MODEL"], messages=messages,
                       stream=not web_search, max_completion_tokens=4096, temperature=0.2)
        if web_search:
            options.update(tools=[{"type": "browser_search"}], tool_choice="required", reasoning_effort="low")
        stream = client.chat.completions.create(**options)
        if web_search:
            text = web_answer(stream)
            if not text:
                raise ChatError("La recherche n'a pas fourni de sources consultables. Réessayez ; aucune réponse non sourcée n'a été enregistrée.", 502, "missing_web_sources")
            stream = CompletedWebStream(text, stream.choices[0].finish_reason)
    except Exception as error:
        if not factory:
            client.close()
        if isinstance(error, ChatError):
            raise
        raise provider_error(error) from error
    return stream, client if not factory else None


def user_content(message, filename=None, source=None):
    if not source:
        return message
    if not re.search(r"^\[(?:Page|Extrait) \d+\]", source, re.M):
        # Legacy text has no recoverable PDF pagination; use passage labels.
        source = label_excerpts(source)
    return (
        f"{message}\n\nDocument joint : {filename}\n"
        "<document_a_analyser>\n" + source + "\n</document_a_analyser>"
    )


def build_context(history, specialty, question, filename=None, source=None, answer_level="intermediate", web_access=False):
    if web_access:
        history, filename, source = [], None, None
    system = system_prompt(SPECIALTIES[specialty][1], answer_level, web_access=web_access)
    current = {"role": "user", "content": user_content(question, filename, source)}
    budget = 56_000 - len(system) - len(current["content"])
    # Take whole user/assistant pairs; never start model context with an assistant.
    recent = []
    for i in range(len(history) - 2, -1, -2):
        pair = history[i:i + 2]
        if [m["role"] for m in pair] != ["user", "assistant"]:
            continue
        content = [
            {"role": m["role"], "content": user_content(
                m["content"], m.get("attachment_name"), m.get("attachment_text")
            ) if m["role"] == "user" else m["content"]}
            for m in pair
        ]
        size = sum(len(m["content"]) for m in content)
        if size > budget:
            break
        recent[0:0] = content
        budget -= size
    return [{"role": "system", "content": system}, *recent, current]
