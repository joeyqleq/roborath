# RoboRath commands (planned and implemented)

RoboRath participates in twitch.tv/rath_bone as the normal Twitch user `roborath`. It requires an authenticated user-token and does **not** obtain moderator powers.

## Currently implemented in the source code

| Command | Access | Effect |
|---|---|---|
| `!fact <claim>`, `!check <claim>` | All | Two requests per user per Twitch stream; max one answer message |
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
