"""Concise, parser-backed Twitch help pages and command-topic text."""
from __future__ import annotations

import re


PAGES = {
    1: "Ask: !ask tell me a joke. Search: !search latest space news. Quick claim check: !verify the Earth orbits the Sun. For a careful explanation: !verify deep why do seasons happen?",
    2: "Mario: !rr mario status, on, off, reset, roster, next, scores or leaderboard. Report a first-place finish with !rr win joey. Two matching voters confirm it. Ask !rr help mario for details.",
    3: "Reminders: !rr remind 20m stretch your legs. Watch: !rr watch phone => knock knock. Privacy: !privacy, !forgetme or !optout; return with !optin. Ask !rr help alerts for alerts and reminders.",
    4: "Owner controls: allow @viewer to fact check; give @viewer conversation or all AI; remove @viewer from testing; show access; stop talking; resume talking. Only verified owner joeyleq can manage access or silence. !rr id shows your Twitch ID.",
}

TOPICS = {
    "ask": "Ask: !ask tell me a joke about billionaires. Follow up with !ask and your next question. RoboRath ignores ordinary unaddressed chat.",
    "search": "Search: !search latest NASA moon news. Results are discovery, not proof; ask !verify for a sourced claim check. Current facts may be unavailable.",
    "verify": "Verify: !verify the Earth orbits the Sun. For explanations or disputed history use !verify deep how did the Six-Day War begin? Deep requests use the research allowance.",
    "fact": "Quick check: !fact the Earth is flat, or !check this quote is real. One claim, short verdict and source when verified. One use per stream by default.",
    "research": "Research: !research history of Maoism. For a short claim check use !verify. Research gives more context and sources; one use per UTC day by default.",
    "mario": "Mario: !rr mario status|on|off|reset|roster|next|scores|leaderboard. Report a win with !rr win joey or ?! joey. Two distinct matching reports confirm first place.",
    "alerts": "Text alerts: !rr watch phone => knock knock. Watches expire after 12h and cool down for 5m. !rr help reminders explains timed reminders.",
    "triggers": "Owner rules: !rr rule add phone when phone => knock knock. Use !rr rule list, test phone phone, disable phone, enable phone or remove phone. Natural: Whenever you hear the word phone, say knock knock. Text matching, not semantic inference.",
    "reminders": "Queue: !rr remind 20m drink water. List: !rr reminders. Cancel: !rr reminder cancel 1. Delay: 1m to 7d, five outstanding per user. Delivery waits for verified live public mode and respects silence.",
    "privacy": "!privacy explains retention. !forgetme or !optout deletes your stored chat data and opts out; !optin resumes interaction. Only public chat is seen; no whispers or stream video.",
    "permissions": "Owner joeyleq alone grants or removes QA access and controls silence. The streamer can use AI without quotas when public use is enabled, but cannot administer permissions. Ask !rr help admin.",
    "admin": "Owner: show access; !rr status. Give permissions to everyone = two invokes each. Give to alice = two more. Give alice 3 invokes = three more. Set alice to 3 invokes = total cap. Remove alice; global turn off. Owner always allowed. No command prefix required for owner controls.",
}


def help_response(raw: str, *, specialist_enabled: bool | None = None) -> str | None:
    """Resolve help/commands requests. Text is kept below Twitch's 420-byte cap."""
    match = re.fullmatch(r"!rr\s+(help|commands)(?:\s+(\d+|[a-z]+))?", raw.strip(), re.I)
    if not match:
        return None
    command, arg = match.group(1).casefold(), (match.group(2) or "1").casefold()
    if command == "commands" and arg == "1":
        arg = "1"
    if arg.isdigit():
        page = int(arg)
        if page not in PAGES:
            return "Help pages: !rr help 1, 2, 3 or 4. Topics: !rr help ask, search, verify, mario, alerts, reminders, privacy, permissions or admin."
        text = PAGES[page]
        if page == 1 and specialist_enabled is False:
            text += " Fact/research relay is currently offline."
        return text
    return TOPICS.get(arg, "Try !rr help 1, 2, 3 or 4; topics include ask, search, verify, fact, research, mario, alerts, triggers, reminders, privacy, permissions and admin.")

