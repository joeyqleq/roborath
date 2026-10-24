"""Output contract for a human-readable, non-spamming Twitch chat assistant."""
from __future__ import annotations
import json
import re
from textwrap import shorten

# Conservative UTF-8 budget allows IRC command prefixes, reply tags and emoji.
MAX_IRC_BYTES = 420
URL = re.compile(r"https?://[^\s<>\])}]+", re.IGNORECASE)
COMMAND_PREFIX = re.compile(r"^\s*\x01")

def utf8_clip(text: str, budget: int = MAX_IRC_BYTES) -> str:
    """Clip by bytes, not characters; don't split Unicode multibyte sequences."""
    if budget < 4: raise ValueError("budget too small")
    text = str(text).strip()
    if len(text.encode("utf-8")) <= budget: return text
    raw = text.encode("utf-8")[: budget - len("...".encode())]
    return raw.decode("utf-8", "ignore").rstrip(" .,:;") + "..."

def humanize(text: str) -> str:
    """Remove Markdown/JSON scaffolding; preserve uncertainty and source text."""
    text = str(text or "").strip()
    if not text: return "no answer available yet"
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
        for original,short in (("you are","ur"),("you're","ur"),("your","ur"),
                  ("you","u"),(" to "," 2 "),(" too "," 2 "),("because","bc"),
                  ("probably","prob"),("approximately","~"),("according to","per")):
            text = re.sub(re.escape(original),short,text, flags=re.I)
    return utf8_clip(text,budget)

def without_raw_links(text: str, replacement: str = "[source link unavailable]") -> str:
    """Never expose long raw URLs in Twitch chat when shortener is unavailable."""
    return URL.sub(replacement, str(text))

def messages(text: str, capability: str, budget: int = MAX_IRC_BYTES) -> list[str]:
    """Facts/security: one message; research: at most 2, prefer one."""
    if capability not in ("fact","research","security","help"):
        raise ValueError("unknown response capability")
    clean = without_raw_links(humanize(text))
    if capability != "research":
        return [compress_for_chat(clean,budget)]
    if len(clean.encode("utf-8")) <= budget:
        return [clean]
    first = compress_for_chat(clean[:budget],budget)
    tail = clean[len(clean[:budget]):].strip()
    if not tail:
        return [first]
    return [first, compress_for_chat(tail,budget)]
