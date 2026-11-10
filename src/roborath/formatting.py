"""Output contract for a human-readable, non-spamming Twitch chat assistant."""
from __future__ import annotations
import json
import html
import re
import unicodedata

# Conservative UTF-8 budget allows IRC command prefixes, reply tags and emoji.
MAX_IRC_BYTES = 420
URL = re.compile(r"https?://[^\s<>\])}]+", re.IGNORECASE)
COMMAND_PREFIX = re.compile(r"^\s*\x01")
_CONTROL_TAG = re.compile(
    r"</?\s*(?:think|analysis|tool_call|function_call|tool_calls|assistant|system|developer)\b|"
    r"<\|\s*/?\s*(?:think|analysis|tool_call|function_call|tool_calls|assistant|system|developer)\s*\|>",
    re.IGNORECASE,
)


class UnsafeModelOutput(ValueError):
    """The upstream response is not safe to expose as a public answer."""


def validate_final_output(value) -> str:
    """Accept only plain assistant text, rejecting protocol/tool artifacts.

    Ordinary JSON is allowed and can be humanized below. Objects that represent
    tool calls (or tool-role messages) are rejected instead of flattened into chat.
    """
    if not isinstance(value, str):
        raise UnsafeModelOutput("assistant final content must be plain text")
    text = value.strip()
    if not text:
        raise UnsafeModelOutput("empty assistant final content")
    protocol_view = html.unescape(unicodedata.normalize("NFKC", text))
    protocol_view = "".join(c for c in protocol_view if unicodedata.category(c) != "Cf")
    if _CONTROL_TAG.search(protocol_view):
        raise UnsafeModelOutput("model returned an internal control marker")
    candidate = protocol_view
    fenced = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", protocol_view, flags=re.I | re.S)
    if fenced:
        candidate = fenced.group(1).strip()
    if candidate[:1] in "{[":
        try:
            payload = json.loads(candidate)
        except (ValueError, TypeError):
            payload = None
        def contains_tool_schema(item):
            if isinstance(item, dict):
                if ({"name", "arguments"} <= item.keys() or {"tool", "arguments"} <= item.keys()
                        or str(item.get("role", "")).casefold() == "tool"):
                    return True
                if "tool_calls" in item or "function_call" in item:
                    return True
                return any(contains_tool_schema(value) for value in item.values())
            if isinstance(item, list):
                return any(contains_tool_schema(value) for value in item)
            return False
        if contains_tool_schema(payload):
            raise UnsafeModelOutput("model returned a tool invocation")
        if payload is None and re.search(
                r"\{\s*[\"']?name[\"']?\s*:\s*[^,}]+,\s*[\"']?arguments[\"']?\s*:|"
                r"\{\s*[\"']?arguments[\"']?\s*:\s*[^,}]+,\s*[\"']?name[\"']?\s*:",
                candidate, re.I):
            raise UnsafeModelOutput("malformed structured tool invocation")
    if re.search(r"\b(?:tool[_\s]call|function[_\s]call)\b", protocol_view, re.I) and re.search(
            r"\b(?:arguments|search_tools)\b", protocol_view, re.I):
        raise UnsafeModelOutput("model returned tool-call syntax")
    return text

def utf8_clip(text: str, budget: int = MAX_IRC_BYTES) -> str:
    """Clip by bytes, not characters; don't split Unicode multibyte sequences."""
    if budget < 4: raise ValueError("budget too small")
    text = str(text).strip()
    if len(text.encode("utf-8")) <= budget: return text
    raw = text.encode("utf-8")[: budget - len("...".encode())]
    return raw.decode("utf-8", "ignore").rstrip(" .,:;") + "..."

def humanize(text: str) -> str:
    """Remove Markdown/JSON scaffolding; preserve uncertainty and source text."""
    if not isinstance(text, str) or not text.strip():
        return "no answer available yet"
    text = validate_final_output(text)
    if text[:1] in ('{','['):
        try:
            data = json.loads(text)
            if isinstance(data,dict):
                fields = [data.get(k) for k in ("summary","answer","verdict","reason")]
                text = ". ".join(str(x) for x in fields if x)
                if not text: text = "result is available in the private report"
            elif isinstance(data,list):
                text = "; ".join(map(str,data[:3]))
        except (ValueError,TypeError): pass
    text = re.sub(r"```[a-z]*\n?|\n?```", "", text, flags=re.I)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"^\s*(?:[-*#]+|\d+\.)\s*", "", text, flags=re.M)
    text = re.sub(r"[\r\n\t ]+", " ", text).strip()
    return COMMAND_PREFIX.sub("", text)

def compress_for_chat(text: str, budget: int = MAX_IRC_BYTES) -> str:
    """Keep all replies single-line and bounded; source URL handling upstream."""
    text = humanize(text)
    if len(text.encode("utf-8")) > budget:
        # Clip only at word boundaries; informal replacements changed arbitrary
        # substrings (for example, "you" inside "young") and garbled answers.
        text = text.strip()
    return utf8_clip(text,budget)

def sentence_clip(text: str, budget: int = 365) -> str:
    """Prefer complete sentences over Twitch's confusing mid-word truncation."""
    clean = humanize(text)
    if len(clean.encode("utf-8")) <= budget:
        return clean
    links = URL.findall(clean)
    if links:
        # Preserve complete source URLs even when the prose must be shortened.
        suffix = " Sources: " + " ".join(links)
        if len(suffix.encode("utf-8")) >= budget:
            raise UnsafeModelOutput("source URLs exceed the response byte budget")
        body_budget = budget - len(suffix.encode("utf-8"))
        prose=URL.sub("",clean).strip()
        body = utf8_clip(prose, body_budget).removesuffix("...").rstrip()
        return body + suffix
    short = clean.encode("utf-8")[:budget].decode("utf-8", "ignore")
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", short)]
    if ends and ends[-1] > int(budget * .43):
        return short[:ends[-1]].strip()
    last = short.rfind(" ")
    if last > int(budget * .5):
        return short[:last].rstrip(" .,;:") + "..."
    return utf8_clip(clean, budget)


def without_raw_links(text: str, replacement: str = "[source link unavailable]") -> str:
    """Never expose long raw URLs in Twitch chat when shortener is unavailable."""
    clean = validate_final_output(text)
    def keep_short_link(match):
        url = match.group(0)
        try:
            from urllib.parse import urlsplit
            host = (urlsplit(url).hostname or "").casefold()
        except ValueError:
            host = ""
        # Preserve the short links generated by the configured citation
        # shortener; suppress arbitrary long source URLs that exceed chat limits.
        return url if host in {"is.gd", "bit.ly", "t.co", "tinyurl.com"} and len(url.encode("utf-8")) <= 64 else replacement
    return URL.sub(keep_short_link, clean)

def messages(text: str, capability: str, budget: int = MAX_IRC_BYTES) -> list[str]:
    """Facts/security: one message; research: at most 2, prefer one."""
    if capability not in ("fact","research","security","help"):
        raise ValueError("unknown response capability")
    clean = humanize(text)
    clean = without_raw_links(clean)
    links = URL.findall(clean)
    if capability != "research":
        if len(clean.encode("utf-8")) <= budget:
            return [clean]
        if links:
            suffix = " " + links[0]
            if len(suffix.encode("utf-8")) >= budget:
                raise UnsafeModelOutput("source URL exceeds the response byte budget")
            return [utf8_clip(clean[:clean.find(links[0])].strip(),
                              budget-len(suffix.encode("utf-8"))).removesuffix("...").rstrip()+suffix]
        return [compress_for_chat(clean,budget)]
    if len(clean.encode("utf-8")) <= budget:
        return [clean]
    if links:
        source_suffix = " ".join(links[:2])
        if len(("Sources: "+source_suffix).encode("utf-8")) > budget:
            raise UnsafeModelOutput("research source URLs exceed one Twitch message")
        prose = clean
        for link in links:
            prose = prose.replace(link, "").strip()
        max_body = budget-len((" Sources: " + source_suffix).encode("utf-8"))
        if max_body<24:
            return [utf8_clip(prose,budget),"Sources: "+source_suffix]
        body = utf8_clip(prose, max_body).removesuffix("...").rstrip()
        combined = (body + " Sources: " + source_suffix).strip()
        if len(combined.encode("utf-8")) <= budget:
            return [combined]
        first = utf8_clip(body, budget).removesuffix("...").rstrip()
        second = "Sources: " + source_suffix
        if len(second.encode("utf-8")) > budget:
            raise UnsafeModelOutput("research source URLs exceed one Twitch message")
        return [first, second]
    first = compress_for_chat(clean[:budget],budget)
    tail = clean[len(clean[:budget]):].strip()
    if not tail:
        return [first]
    return [first, compress_for_chat(tail,budget)]
