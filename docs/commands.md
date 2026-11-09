# RoboRath commands (planned and implemented)

RoboRath participates in twitch.tv/rath_bone as the normal Twitch user `roborath`. It requires an authenticated user-token and does **not** obtain moderator powers.

## Currently implemented in the source code

| Command | Access | Effect |
|---|---|---|
| `!fact <claim>`, `!check <claim>` | All | One request per user per Twitch stream; max one answer message |
| `!research <topic>` | All | One request per user per UTC day; up to two messages |
| `hey roborath, fact <claim>` | All | Explicit natural-language fact-check invocation |
| `@roborath research <topic>` | All | Explicit natural-language research invocation |
| `!rr help`, `!rr help 2` | All | Short command-help pages |
| `!rr id` | All | Displays the requesting account's immutable Twitch user ID |
| `!rr remind 20m <text>` | All | Queues one reminder; at most five outstanding, 1m–7d |
| `!rr watch <phrase> => <response>` | All | Up to three per-user public-text watches, expiring in 12h |
| `!rr mario scores` | All | First-place wins for the current game session |
| `!rr mario leaderboard` | All | All-time confirmed first-place scores |
| `!rr win <player>` or `?! <player>` | All, mode on | Vote on first place; two independent matching reports required |
| `!forgetme`, `!optout` | All | Delete stored public chat, aggregates, grants and alerts; opt out |
| `!optin` | All | Resume participating |
| `!privacy` | All | Short and accurate retention summary |
| `!rr grant <numeric_user_id> fact 2` | Owner or fact-grant supervisor | Adds two fact requests in this stream |
| `!rr grant <numeric_user_id> research 1` | Owner or research-grant supervisor | Adds one research request today |
| `!rr supervisor add <numeric_user_id> fact_grant` | Verified owner | Grant limited, persistent quota-grant permission |
| `!rr supervisor remove <numeric_user_id> fact_grant` | Verified owner | Revoke limited permission |
| `!rr mario on/off` | Owner or mario supervisor | Enable/disable Nintendo Switch mode |
| `!rr mario roster raf moodbasket joey` | Owner or mario supervisor | Set player nicknames |
| `!rr mario next` | Owner or mario supervisor | Open next round after winner confirmation |

For supervisor permissions, allowed capability strings are `fact_grant`, `research_grant`, `mario_manage`, `trigger_manage`. The owner may assign/revoke them at any time; they never grant owner powers.

## Important limits

- The configured owner Twitch ID must be resolved from the **real** `joeyleq` account, not inferred from the display name in a chat message. Same for the broadcaster `rath_bone`.
- `rath_bone` is exempt from public fact/research quotas but is **not** a RoboRath administrator.
- A non-moderator bot cannot ban or time out other users.
- Watches search the public messages received by the IRC bot, not viewers' private chats or audio/video.
- Chat archive and aggregates are accessible only to permitted operators; a graphical Mattermost console is not yet installed.
- Source URLs are shortened by a third-party shortening service where available. On failure, the bot suppresses a raw long URL.
- This document specifies the current **staged source**; live Twitch chat and Mattermost relaying remain untested.

## Conversation and web lookup (November 9, 2026)

- `!ask <question>`: general conversation or Mario Kart knowledge. Verified
  sender identity is supplied separately, so `roborath` is the bot's own name,
  `joeyleq` is the operator and `rath_bone`/Rath is the streamer.
- Weather and clearly time-sensitive questions in `!ask` use a keyless
  public lookup where available. Weather uses timestamped Open-Meteo conditions
  and deterministic WMO-code descriptions.
- `!search <query>`: fetch public web search result titles with short links.
  Search results are NOT independently verified complete articles, so the bot
  does not invent winners, dates or allegations from snippets.
- Replies are plain chat messages addressed to the verified sender
  (`@username`), rather than visually confusing Twitch mini-threads.
  `ROBORATH_THREADED_REPLIES=true` restores Twitch reply tags if desired.
- Search is best-effort and may be rate limited. `ROBORATH_WEB_SEARCH_ENABLED=false`
  disables external web lookup. The separate `!fact`/`!research` specialist
  remains fail-closed until its restricted Mattermost relay is tested.


## Mario session controls and conversation reliability (2026-11-09)

- `!rr mario status`: show on/off, current round, roster size.
- `!rr mario on` / `!rr mario off`: owner/supervisor controls that
  bypass the public chat cooldown.
- `!rr mario reset`: owner/supervisor only; clear this stream's active mode,
  roster, votes, winners and round number, return to round 1.
- Mario mode automatically turns OFF after 5 hours from activation. A new
  stream ID starts a separate session. Mario mode does not hijack general
  `!ask` questions or replace their conversational AI instructions.
- `!rr doctor`: owner-only concise status for model, Mario and relay.
- Operator requests have no per-viewer cooldown. Normal viewers have an
  8-second cooldown with one explicit notice, rather than silent nonanswers.
  Global reply pacing is 4 seconds.
- Public replies contain exactly one addressed Twitch `@username`, not two.
  No generated hashtags or emoji clutter. English is the default unless
  explicitly requested otherwise.
- Model backend: Nebius Qwen3-30B first, Qwen3-235B for stronger questions,
  Merge Nova-2-Lite fallback. Actual provider permissions and balance apply.


## Short-term context and answer scenarios (2026-11-09)

- Same Twitch viewer and same stream only: last eight answered conversation/search
  turns from the past five hours are included as **untrusted dialogue history**.
  Messages from another viewer or stream are never included. No claim of
  permanent personal memory. Turns are serialized per viewer.
- Operator can repeat a deterministic letter-count question unprefixed within
  90 seconds of the preceding answered turn; other conversations still use
  explicit !ask or !search commands so the bot doesn't reply to all chatter.
- Deterministic counting supports curly apostrophes and variants such as
  `how many r’s r there in strawberry?` and `sstrawberry`.
- Self-correction: follow-up queries about recent contradictions can correct
  a previous numerical error from stored dialogue, not invent memory.
- Latest creator upload: requests naming an exact verified YouTube channel,
  including Rabbi Shmuley / @ShmuleyShow, fetch an official channel Atom
  feed, return the latest published title/date and short source link.
  Other @handles can be resolved through the public YouTube channel page.
  Generic search snippets remain a discovery fallback, not verified facts.
- Subsequent `!ask tell me the title name` recovers the same viewer's recent
  video search (five hour maximum) and rechecks the official source.
- Help/control messages now receive an outbound-queue audit status; standalone
  unaddressed chatter is tagged ignored_unaddressed. IRC NOTICE messages are
  surfaced as categorized warning events. A successful websocket send is
  not a platform acknowledgement of public chat delivery.
- NVIDIA Nemotron 3 Ultra 550B appears in the available model catalog and
  NVIDIA advertises a trial endpoint, but ORA3 direct inference timed out;
  do not enable it for latency-sensitive Twitch until live inference passes.


## Owner-only Twitch QA (2026-11-09)

For this testing period, `ROBORATH_OWNER_ONLY_TEST_MODE=true` is deployed on
ORA3. RoboRath responds to **Twitch user ID 1414798445 (joeyleq) only**,
regardless of display-name casing. Every other sender, including the channel's
streamer, is ignored before logging, AI inference, moderator commands,
notifications, or quota checks. Scheduled reminders are paused entirely.
Disable this flag only after the owner explicitly authorizes public testing.
The separate private Mattermost relay remains fail-closed until verified.
