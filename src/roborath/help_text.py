"""Concise, parser-backed Twitch help pages and command-topic text."""
from __future__ import annotations

import re


PAGES = {
    1: "Help 1/4 | Use !ask for everything: !ask latest Israel news; !ask verify this quote; !ask research the competing sources; !ask tell me a joke. Topics: !rr help stats, permissions or status. Next: !rr help 2.",
    2: "Help 2/4 | Mario: !rr mario status, on, off, reset, roster, next, scores or leaderboard. Report a first-place finish with !rr win joey. Two matching voters confirm it. Topic: !rr help mario. Next: !rr help 3.",
    3: "Help 3/4 | Stats: !ask how many words did user alice say? !ask leaderboard by characters. Reminders: !rr remind 20m stretch. Privacy: !privacy; !optout deletes your data; !optin resumes capture. Topics: !rr help memory or alerts. Next: !rr help 4.",
    4: "Help 4/4 | Owner English: give invoke permissions to all = two more each this stream; give to alice = two more; give alice 3 invokes = three more. Global turn off excludes Joeyleq. Show access; !rr status. Stop talking; resume talking. Topic: !rr help admin.",
}

TOPICS = {
    "ask": "!ask chooses the pipeline: conversation, exact chat statistics, news, verification or research. Examples: !ask latest Israel news; !ask verify this quote; !ask research competing sources. Follow up with !ask. Permissions and invoke limits still apply.",
    "search": "Search: !search latest NASA moon news. Results are discovery, not proof; ask !verify for a sourced claim check. Current facts may be unavailable.",
    "verify": "Verify: !verify the Earth orbits the Sun. For explanations or disputed history use !verify deep how did the Six-Day War begin? Deep requests use the research allowance.",
    "fact": "Use !ask verify this quote for a sourced check. Old !fact, !check and !verify aliases still work. Shared invokes apply when granted; legacy fact access has one use per stream. Failed requests refund allowance.",
    "research": "Use !ask research the competing sources for deeper investigation. !research still works. Shared invokes apply when granted; legacy research access has one use per UTC day. Source availability and spending limits still apply.",
    "mario": "Mario: !rr mario status|on|off|reset|roster|next|scores|leaderboard. Report a win with !rr win joey or ?! joey. Two distinct matching reports confirm first place.",
    "alerts": "Text alerts: !rr watch phone => knock knock. Watches expire after 12h and cool down for 5m. !rr help reminders explains timed reminders.",
    "triggers": "Owner rules: !rr rule add phone when phone => knock knock. Use !rr rule list, test phone phone, disable phone, enable phone or remove phone. Natural: Whenever you hear the word phone, say knock knock. Text matching, not semantic inference.",
    "reminders": "Queue: !rr remind 20m drink water. List: !rr reminders. Cancel: !rr reminder cancel 1. Delay: 1m to 7d, five outstanding per user. Delivery waits for verified live public mode and respects silence.",
    "privacy": "!privacy explains retention. !forgetme or !optout deletes your stored chat data and opts out; !optin resumes interaction. Only public chat is seen; no whispers or stream video.",
    "permissions": "Joeyleq only: give permissions to everyone; give invoke permissions to all; give to alice. Each gives two more shared invokes this stream. Give alice 3 invokes gives three more. Remove alice revokes access; global turn off blocks viewers, never Joeyleq. Show access lists permissions.",
    "admin": "Owner: show access; !rr status. Give permissions to everyone = two invokes each. Give to alice = two more. Give alice 3 invokes = three more. Set alice to 3 invokes = total cap. Remove alice; global turn off. Owner always allowed. No command prefix required for owner controls.",
    "status": "Owner: !rr status shows state, stream, model and invoke usage. Show access lists allowed/denied users; show access 2 gets page 2. These reports and resume talking remain available during silence. Global turn off always excludes Joeyleq.",
    "stats": "!ask how many words did user alice say? !ask how many characters did user alice write? !ask when did user alice first speak? Counts exclude username mentions; characters exclude whitespace. First speech is not join/watch time. Captured chat only.",
    "leaderboard": "!ask who here has spoken the most? ranks by words. !ask leaderboard by messages or !ask leaderboard by characters selects other rankings. Up to four chatters; current stream, retained received chat. RoboRath is excluded.",
    "memory": "Received public chat is saved for 30 days, independent of browser refreshes. !ask what did user alice say three hours ago? Missing/disconnected or deleted messages cannot be recovered. Owner notes: !rr remember music => Our favourite band is System of a Down; !rr forget music.",
    "news": "!ask latest Israel news retrieves dated publisher summaries with a source. !ask latest world news also works. Coverage may be incomplete; no matching recent report means unavailable, not no event. RSS summaries are publisher reports, not independent proof.",
    "theme": "Owner: !rr theme status shows the temporary topic theme; !rr theme off stops it. The current Hegseth theme lasts three verified streams, including the activation stream. Comments are capped and respect mute/global-off.",
    "trends": "Google Trends and keyword-volume data are not connected yet. RoboRath cannot currently confirm whether a username was searched in Israel. Missing Trends data does not prove zero searches. Owner setup requires authorized provider access.",
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

