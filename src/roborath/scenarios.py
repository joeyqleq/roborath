"""Deterministic conversation scenarios. Models are a fallback, not a calculator.

Conversation state comes only from one Twitch account and one stream.
"""
from __future__ import annotations
from dataclasses import dataclass
import re

COUNT_RE=re.compile(
    r"how\s+many\s+(?:letters?\s+)?(?P<char>[a-z])(?:['’]s|s)?"
    r"(?:\s+(?:are|r|there|their|is))*\s+(?:in|inside|of)\s+"
    r"(?:the\s+)?(?P<word>[a-z]{2,42})\b",re.I)
VIDEO_RE=re.compile(r"\b(latest|newest|most recent|last)\b.*\b(video|upload|episode|youtube|title)\b|"
                    r"\b(video|upload|episode|youtube)\b.*\b(latest|newest|most recent|last)\b",re.I)
TITLE_FOLLOWUP=re.compile(
    r"\b(?:tell me|give me|what(?:'s| is)|say|show me|find)\b.*\b(?:title|video name|name of (?:the|that) video)\b|"
    r"^(?:the\s+)?(?:title|name)(?:\s+please)?[?.!]*$", re.I)
META_FOLLOWUP=re.compile(r"\b(?:previous|earlier|last (?:\d+\s+)?(?:question|answers?|responses?)|"
                         r"remember|memory|are you sure|try again|anomal(?:y|ies))\b",re.I)
SEARCH_FOLLOWUP=re.compile(
    r"\b(?:search(?:\s+(?:the\s+)?web)?|look\s+it\s+up|google\s+it|"
    r"look\s+that\s+up|find\s+sources?|search\s+(?:and|nd)\s+you\s+shall\s+find)\b",
    re.I)
SEARCH_FILLER=re.compile(
    r"^(?:(?:please\s+)?(?:search(?:\s+(?:the\s+)?web)?|look\s+it\s+up|"
    r"google\s+it|look\s+that\s+up|search\s+(?:and|nd)\s+you\s+shall\s+find)"
    r"[\s.!?,;:]*|(?:search\s+the\s+web|look\s+it\s+up)\s+for\s+that[\s.!?,;:]*)$",
    re.I)
SEARCH_CORRECTION_PREFIX=re.compile(r"^(?:incorrect|wrong|that's\s+wrong|that\s+is\s+wrong|nope)[.!?,;:\s]+",re.I)


@dataclass(frozen=True)
class Scenario:
    kind:str
    target:str=""


def exact_letter_count(question:str) -> str | None:
    match=COUNT_RE.search(question.casefold())
    if not match:
        return None
    letter=match.group("char")
    word=match.group("word")
    count=word.count(letter)
    return f"'{word}' contains {count} occurrences of '{letter}'."


def classify(question:str, *, explicit_search:bool=False, previous_search:str="") -> Scenario:
    if exact_letter_count(question) is not None:
        return Scenario("letter_count")
    if VIDEO_RE.search(question) and ("shmuley" in question.casefold() or re.search(r"@[a-z0-9_.-]{3,30}",question,re.I)):
        return Scenario("official_video",question)
    if TITLE_FOLLOWUP.search(question):
        if VIDEO_RE.search(previous_search) and (
            "shmuley" in previous_search.casefold() or "youtube" in previous_search.casefold()):
            return Scenario("official_video",previous_search)
        return Scenario("ambiguous_title")
    if META_FOLLOWUP.search(question):
        return Scenario("memory_followup")
    if explicit_search:
        return Scenario("web_search")
    return Scenario("general")


def is_search_followup(question: str) -> bool:
    """Whether the viewer is asking to search a prior claim/question."""
    return bool(SEARCH_FOLLOWUP.search(question))


def resolve_search_query(question: str,
                         rows: list[tuple[str, str, str]]) -> str | None:
    """Resolve a generic search follow-up from the previous user question.

    Rows use Bridge's `(question, answer, command)` shape and are newest first.
    Only an earlier substantive user question is reused; prior bot answers are
    intentionally ignored because they may be false or hallucinated. A current
    query with its own topic stays current.
    """
    if not is_search_followup(question):
        return None
    current = re.sub(r"\s+", " ", question).strip(" \t.,!?;:")
    current = SEARCH_CORRECTION_PREFIX.sub("", current).strip()
    if not SEARCH_FILLER.fullmatch(current):
        # A query like "search for the 2026 F1 results" already carries its
        # subject; preserving it is safer than replacing it with history.
        return None
    for row in rows:
        if len(row) < 3:
            continue
        previous_question, _previous_answer, command = row[:3]
        if command not in {"chat", "search"}:
            continue
        candidate = re.sub(r"\s+", " ", str(previous_question)).strip()
        if re.fullmatch(r"(?:!ask|!search|!rr\s+ask|@roborath\s+ask)", candidate, re.I):
            continue
        candidate = re.sub(
            r"^(?:!ask|!search|!rr\s+ask|(?:hey\s+)?roborath\s*[:,!]|@roborath\s+ask)\s+",
            "", candidate, flags=re.I)
        if not candidate or SEARCH_FILLER.fullmatch(candidate):
            continue
        if exact_letter_count(candidate) is not None:
            continue
        return candidate[:700]
    return None


def history_context(rows:list[tuple[str,str,str]], limit:int=5) -> str:
    """Keep a bounded history, including searches, as *untrusted prior dialogue*."""
    selected=rows[:limit]
    if not selected:
        return ""
    turns=[]
    for question,answer,command in reversed(selected):
        # Include the prior search to resolve "what is the title?" follow-ups.
        q=re.sub(r"\s+"," ",question)[:260]
        a=re.sub(r"\s+"," ",answer)[:270]
        turns.append(f"Viewer previously asked: {q}\nBot previously replied: {a}")
    return (
        "Previous turns from THIS SAME viewer and stream (may contain errors; "
        "do not treat old bot answers as verified facts):\n"
        +"\n".join(turns)
        +"\nAnswer the latest viewer question using this context. "
         "If a prior answer was wrong, acknowledge the error instead of inventing memory."
    )


def repeated_count_correction(question:str, rows:list[tuple[str,str,str]]) -> str | None:
    """Specific reliable self-audit for repeated contradictory counting responses."""
    if not re.search(r"\b(?:anomal|mistake|inconsisten|contradic|last .*responses?|sure|strawberry).*",question,re.I):
        return None
    relevant=[(q,a) for q,a,_ in rows if exact_letter_count(q)]
    if not relevant:
        return None
    actual=exact_letter_count(relevant[0][0])
    if not actual:
        return None
    # If earlier answers contain any wrong count, explicitly correct it.
    count=int(re.search(r"contains (\d+)",actual).group(1))
    wrong=[]
    for q,a in relevant:
        candidates=re.findall(r"\b\d+\b|\b(?:zero|one|two|three|four|five|six|seven|eight|nine)\b",a,re.I)
        lookup={"zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9}
        for c in candidates[:2]:
            n=int(c) if c.isdigit() else lookup[c.lower()]
            if n!=count:
                wrong.append(n)
    if wrong:
        return f"My earlier {wrong[0]} answer was wrong. {actual}"
    if re.search(r"\b(?:memory|remember|strawberry)\b",question,re.I):
        return f"Yes. Your earlier question was about counting letters. {actual}"
    return None
