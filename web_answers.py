"""Render only source URLs actually returned by Groq's browser tool."""

import re
from types import SimpleNamespace
from urllib.parse import urlsplit

SUPPORTED_WEB_MODELS = {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}


def safe_url(value):
    if not isinstance(value, str) or any(c.isspace() or c in '<>"' for c in value):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        return None
    return value


def web_answer(response):
    message = response.choices[0].message
    tools = (getattr(message, "model_extra", None) or {}).get("executed_tools", []) or []
    titles = {}
    for tool in tools:
        for result in (tool.get("search_results") or {}).get("results", []):
            if safe_url(result.get("url")):
                titles[result["url"]] = result.get("title") or urlsplit(result["url"]).hostname
    sources, by_index = {}, {}
    for tool in tools:
        if tool.get("name") not in {"browser.open", "browser.find"}:
            continue
        match = re.search(r"^L\d+:\s*URL:\s*(https?://\S+)", tool.get("output", ""), re.M)
        url = safe_url(match.group(1)) if match else None
        if url:
            title = re.sub(r"[\[\]<>`*_]", "", titles.get(url) or urlsplit(url).hostname)[:120]
            sources[url] = title
            by_index[str(tool.get("index"))] = url
    if not sources or not (message.content or "").strip():
        return None
    def citation(match):
        url = by_index.get(match.group(1))
        return f"[{sources[url]}](<{url}>)" if url else ""
    # Discard invented model links; the source list below comes from tool output.
    raw = re.sub(r"\[([^\]]+)\]\(([^)]*)\)", lambda m: m.group(0) if m.group(2).strip("<>") in sources else m.group(1), message.content)
    raw = re.sub(r"https?://[^\s<>\"']+", lambda m: m.group(0) if m.group(0).rstrip(".,;)") in sources else "[référence non vérifiée]", raw)
    text = re.sub(r"[【〖](\d+)†[^】〗]*[】〗]", citation, raw)
    text += "\n\n**Sources consultées**\n" + "\n".join(
        f"- [{title}](<{url}>)" for url, title in list(sources.items())[:8]
    )
    return text


class CompletedWebStream:
    def __init__(self, text, finish_reason):
        self.text = text
        self.finish_reason = finish_reason

    def __iter__(self):
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=self.text), finish_reason=self.finish_reason)])

    def close(self):
        pass
