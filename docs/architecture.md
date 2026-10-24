# Architecture and trust boundaries

- Target Twitch channel: `rath_bone` (broadcaster) and normal bot login `roborath`.
- Owner: `joeyleq` on Twitch; `p5n` inside Mattermost. **Do not infer privilege from a typed/display name.** Resolve and compare immutable account IDs before implementing owner commands.
- Twitch IRC WebSocket -> ORA3 IRC adapter -> SQLite log/cooldown/memory -> private Mattermost relay channel -> designated non-admin FactCheck Agent -> Twitch IRC reply.
- All responses from untrusted chat must pass a fixed tool allowlist. Never route public chat directly to the privileged Mattermost Admin AI agent or pentest MCP.
- v0.1 source in this repository is a **staged baseline**, not a deployed or authenticated production service. The running ORA3 service remains disabled until user OAuth and restricted Mattermost bot/channel tokens are provisioned.
- Production IRC access token renewal, immutable-ID owner checks, full stream indexing, admin UI, moderation, news alerts, URL shortening, advanced research and Mario Kart scores require separate integration work and tests.
- Public viewer chat archives and derived operator analytics should use reasonable retention, restricted access, deletion/opt-out, and truthful disclosures. No forged claims that retained data was destroyed. Never infer sensitive psychological vulnerabilities or political affiliations to manipulate audience members.
- A streamer cannot authorize this bot on behalf of a channel it does not control; the bot is an ordinary participant and must comply with room-level verification, ban, slow-mode, follower-only and subscriber-only rules.
