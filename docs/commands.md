# RoboRath command reference

This matrix describes the local source after the 2026-11-10 command audit. It does not prove that any particular revision is installed on ORA3. The deployed revision, owner-only QA flag, relay health and stream state must be checked on the host before interpreting a missing reply. During owner-only QA, verified owner ID `1414798445` is the only account allowed to receive chat replies, regardless of grants.

## Chat and verification

| Command | Who can use it | Effect and limits | Source status |
|---|---|---|---|
| `!ask tell me a joke about billionaires` | Owner; explicitly granted conversation users when public testing is enabled; streamer when enabled | One short conversation reply; ordinary viewer cooldown is 8 seconds; global reply pacing is 4 seconds | Implemented; actual provider availability varies |
| `!rr ask is the Moon tidally locked?` | Same as `!ask` | Explicit conversation alias | Implemented |
| `RoboRath, is the Moon tidally locked?` | Same as conversation | Explicit natural-language invocation | Implemented |
| `@roborath ask is the Moon tidally locked?` | Same as conversation | Explicit mention invocation | Implemented |
| `!rr fact the Earth is flat`, `!rr check the Earth is flat`, `@roborath fact the Earth is flat`, `RoboRath, fact the Earth is flat` | Same eligibility as `!verify` | Explicit quick-check aliases | Implemented |
| `!rr verify deep how do seasons happen?`, `@roborath verify deep how do seasons happen?`, `RoboRath, verify deep how do seasons happen?` | Same eligibility as deep verification | Explicit deep-check aliases | Implemented |
| `!rr research history of Maoism`, `@roborath research history of Maoism`, `RoboRath, research history of Maoism` | Same eligibility as research | Explicit research aliases | Implemented |
| `!search latest NASA moon news` | Owner; explicitly granted conversation users when public testing is enabled; streamer when enabled | Current web discovery; snippets are not verified articles; 8-second viewer cooldown | Implemented with DDGS/Bing fallback; cluster search integration remains under evaluation |
| `!verify the Earth orbits the Sun` | Owner; granted fact users when enabled; streamer when enabled | Quick claim verdict and verified citation; 1 fact use per viewer per stream by default; one Twitch message | Implemented in parser; relay must be enabled and healthy |
| `!verify deep why do seasons happen?` | Owner; granted research users when enabled; streamer when enabled | Explicit deeper, sourced answer; 1 research use per viewer per UTC day by default; at most 2 Twitch messages | Implemented in parser; relay must be enabled and healthy |
| `!check the Earth is flat` / `!fact the Earth is flat` | Same as quick verification | Backward-compatible quick fact-check aliases | Implemented |
| `!research history of Maoism` | Same as deep verification | Backward-compatible research command | Implemented |
| `!verify` / `!fact` / `!research` without a question | Authorized sender only | Returns a concrete usage example and consumes no quota | Implemented for legacy verbs; unified usage is documented in Twitch help |

The quick/deep choice is explicit; `!verify` defaults to the quick fact allowance. Prefix its question with `deep` or `research` to select the research allowance. This deterministic selection is not an uncertainty classifier. Use deep mode for open-ended explanation, contested historical context, or multiple related claims. Both modes require source-backed evidence; a failed relay must refund the allowance.

## Help

| Command | Effect |
|---|---|
| `!rr help` or `!rr help 1` | Ask, search and verify examples |
| `!rr help 2` | Mario controls and score reports |
| `!rr help 3` | Watches, reminders, privacy and opt-out |
| `!rr help 4` | Owner access and silence controls |
| `!rr help ask`, `search`, `verify`, `fact`, `research`, `mario`, `alerts`, `triggers`, `reminders`, `privacy`, `permissions`, `admin` | Focused help for one topic |
| `!rr commands` or `!rr commands 1` | Same as help page 1 |
| `!rr commands 2`, `3`, `4` | Same as the corresponding help page |

Each help response is ordinary chat text and is kept below 420 UTF-8 bytes. Examples are concrete; angle-bracket placeholders are not sent to chat.

## Mario Kart

| Exact syntax | Who may use it | Effect |
|---|---|---|
| `!rr mario status` or `!rr mario` | Any admitted chatter | Shows mode, round and roster count |
| `!rr mario scores` | Any admitted chatter | Current-session confirmed wins |
| `!rr mario leaderboard` | Any admitted chatter | All-time confirmed wins |
| `!rr win joey` or `?! joey` | Any admitted chatter while mode is on | Reports a first-place winner; two distinct matching reports confirm it |
| `!rr mario on`, `off`, `reset`, `roster raf moodbasket joey`, `next` | Verified owner only | Starts/stops/resets a session, sets 2–12 player names, or advances after winner confirmation; mode expires after five hours |

No second/third-place data is inferred. Mario state never substitutes for ordinary question answers.

## Watches, reminders and privacy

| Exact syntax | Who may use it | Effect and limits |
|---|---|---|
| `!rr remind 20m stretch your legs` | Any admitted chatter | Schedules a text reminder in 1 minute to 7 days; at most five outstanding per user and 50 total |
| `!rr watch phone => knock knock` | Verified owner only | Adds a literal public-chat phrase watch; at most three active watches per owner, 12-hour expiry and five-minute cooldown |
| `Whenever you hear the word phone, say knock knock` | Verified owner only | Creates or updates a named whole-word rule; deterministic case-insensitive, punctuation-tolerant matching; one response at most per incoming message |
| `!rr rule add phone-joke when phone => knock knock` | Verified owner only | Same named-rule configuration in explicit form; `edit` replaces the named rule |
| `!rr rule list` | Verified owner only | Lists configured rule names and enabled state |
| `!rr rule test phone-joke The phone rang` | Verified owner only | Tests a sample locally without posting its response |
| `!rr rule enable phone-joke`, `disable phone-joke`, `remove phone-joke` | Verified owner only | Enables, pauses, or deletes a named rule |
| `When someone speaks for the first time in a stream, say Welcome to the chaos.` | Verified owner only | Sets a first-message welcome; deduplicated by immutable user ID and stream ID |
| `!rr welcome set Welcome to the chaos.` / `!rr welcome off` | Verified owner only | Set or pause the first-message welcome |
| `!privacy` | Any admitted chatter | Reports received public chat and derived excerpts up to 30 days, activity counts up to 30 days, and deletion/opt-out controls |
| `!forgetme`, `!optout`, or `!stop` | Any chatter | Deletes the user's stored bot data and opts out of future interaction/logging |
| `!optin` | Any chatter | Clears the user's opt-out |
| `!rr id` | Any admitted chatter | Shows the sender's immutable Twitch user ID |
| `!ask what did chat say about Mao three hours ago?` | Owner; explicitly granted conversation users when public testing is enabled; streamer when enabled | Stream-scoped transcript retrieval with available time/user attribution; results cannot cover messages missed while disconnected | Implemented locally; live deployment not verified |

Named rules use deterministic whole-word, case-insensitive text matching with punctuation tolerance; they are not semantic context rules and do not call an LLM. Maximum 20 owner rules; cooldown is 1 minute to 24 hours (default five minutes); at most one response per incoming message. First-chat welcomes are deduplicated per user and stream. The older `!rr watch` command is source-supported and currently owner-only, with a 12-hour expiry and five-minute cooldown. Its matcher is case-folded substring matching, so `phone` can match inside `headphone`. Reminders and automation controls are persisted; live/public sending still obeys mute and QA gates. Twitch has Follow and live notifications, not a standard stream Like button.

Relative and fixed reminders are supported by the source: `!rr remind 20m stretch your legs` and `!rr remind at 2026-11-11T15:30:00Z check the oven`. Use a future ISO-8601 time with a timezone offset for fixed reminders. `!rr reminders` or `!rr reminders list` lists your pending reminders; `!rr reminder cancel 4` cancels your own reminder (the owner can cancel any). At most five reminders per user, 50 total, scheduled from one minute to seven days ahead. Reminder numbers are returned when queued.

The source also contains a bank of 30 hand-written Follow reminders, scheduled from verified stream start every 20 minutes with persisted stream/tick deduplication. It skips missed ticks instead of posting a burst after reconnect. It remains disabled during owner-only QA, mute, and offline state. Live deployment of the new timers has not been verified.

## Owner access and administration

Only the verified Twitch account ID `1414798445` can grant/revoke permissions, allocate extra fact/research calls, administer Mario/watch controls, list access, configure named rules and welcomes, or mute/resume the bot. Display names are resolved through authenticated Twitch lookup; typed usernames never establish identity. The streamer receives unlimited conversation, search, fact-check and research use only when public participation is enabled; the streamer has no administrative rights.

| Exact syntax / natural language | Effect |
|---|---|
| `RoboRath, allow @viewerx to fact check` | Grant fact-check eligibility |
| `Give @viewerx conversational abilities` | Grant conversation/search eligibility |
| `Give @viewerx all AI abilities` | Grant conversation, fact and research eligibility; no admin power |
| `Grant @viewerx research` | Grant research eligibility |
| `Remove @viewerx from testing` / `Revoke @viewerx fact checking abilities` | Revoke grants |
| `Show access` | Show access list to the verified owner |
| `Stop talking` / `Don't reply to anyone` | Persistently silence replies, queues and timers; no acknowledgment |
| `Resume talking` | Restore replies without changing grants |
| `!rr access grant viewerx fact` (likewise `conversation`, `research` or `all`) | Exact grant alias; target login must resolve through Twitch Helix |
| `!rr access revoke viewerx fact` (likewise `conversation`, `research` or `all`) | Exact revoke alias; target login must resolve through Twitch Helix |
| `!rr grant 555123 fact 2` / `!rr grant 555123 research 1` | Allocate bounded extra quota to a verified numeric Twitch ID; owner only |
| `!rr doctor` | Owner-only concise status of model, Mario and relay configuration; configuration readiness is not proof of end-to-end health |

Access grants only work when owner-only QA is disabled for an approved public test. `!rr supervisor add/remove` is retired: administration is not delegated. Old supervisor database rows are inert. The legacy `!rr supervisor` parser path is not a supported command and now fails closed. `!rr grant NUMERIC_ID fact 2` / `research 1` is owner-only; no supervisor can allocate calls. Ordinary budgets remain one fact per viewer per stream and one research per viewer per UTC day, plus explicit owner grants. Owner and streamer usage are unlimited when they are admitted to the request path.

## Offline operator CLI

`src/roborath/admin_cli.py` is local/operator-only, never Twitch chat. Its supported read commands are `status`, `regulars`, `quotas`, and `mario`, with `--db` and `--limit 1..100` options. Do not expose the CLI or database path to viewers.

## Diagnosing no reply

Check the deployed commit and process, then owner-only QA flag and global mute. For an authorized user, check the exact parser spelling and that a complete question followed the command; then inspect the applicable cooldown/quota, relay/model availability, reply queue and Twitch connection. A successful websocket send does not prove Twitch displayed the message. In owner-only QA, silence for non-owner messages is intentional, even when the sender has a stored grant.
