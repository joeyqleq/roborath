# Owner-only engagement statistics

The Twitch bridge can retain activity summaries for up to **180 days**, while its raw chat event history defaults to **30 days**. The summarized data contains immutable Twitch user IDs, last-observed public username, message counts, distinct stream IDs, and 5-minute activity buckets. It does not contain transcript snippets or inferred psychological characteristics.

This data must be used only by an authenticated operator UI, not by public Twitch commands. Do not expose the analytics database or dashboards publicly; validate the linked owner's immutable Twitch ID and Mattermost account. Inform users truthfully about retention and honor deletion/opt-out requests.

Important: active chat buckets do not prove a viewer was watching, connected, or logged in continuously. The metrics can identify people who regularly **write messages**, not silent viewers.

`src/roborath/analytics.py` implements database initialization, activity-bucket recording, 30-day regulars ranking, 180-day pruning and user deletion. Integration hooks are in the bridge. UI access checks, backed-up retention cleanup, and live-stream integration are still to be implemented and tested before production.
