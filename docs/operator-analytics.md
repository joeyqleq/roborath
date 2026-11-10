# Owner-only engagement statistics

The local source retains **all transcript text and per-user analytics for up to 30 days**. Daily analytics contains immutable Twitch user IDs, observed usernames, message counts, word counts, reply counts and stream IDs. It does not infer personal traits or continuous viewing time. Historical aggregate counts migrate without inventing unknown past word/reply counts.

This data must be used only by an authenticated operator UI, not by public Twitch commands. Do not expose the analytics database or dashboards publicly; validate the linked owner's immutable Twitch ID and Mattermost account. Inform users truthfully about retention and honor deletion/opt-out requests.

Important: active chat buckets do not prove a viewer was watching, connected, or logged in continuously. The metrics can identify people who regularly **write messages**, not silent viewers.

`src/roborath/analytics.py` counts incoming public messages before QA eligibility checks. Words use Unicode word boundaries. Native Twitch replies authored by the viewer and bot replies addressed to that viewer are **separate counts**. Bot replies are counted after a successful socket send, deduplicated by request and reply content. A socket send is not a Twitch server acknowledgment. Bot text does not increase the viewer's word count. Daily pruning drops the entire cutoff date, so nothing exceeds 30 days; part of the boundary date may expire earlier.

The read-only local export uses the private database's filesystem permissions; no public dashboard or Twitch export command is exposed. After an approved deployment, an authorized operator can run from the checkout/runtime with `PYTHONPATH=src/roborath` (or `/opt/roborath/src/roborath`):

```sh
python3 -m report streams --db /var/lib/roborath/chat.sqlite3
python3 -m report transcript --db /var/lib/roborath/chat.sqlite3 --stream STREAM_ID
python3 -m report analytics --db /var/lib/roborath/chat.sqlite3 --stream STREAM_ID
```

Use an actual ID from the first command. Transcript output is plain `username: message`; timestamps and IDs remain in SQLite for retrieval. The export excludes expired/opted-out messages. Keep exports private and delete them on the same retention schedule; automatic database pruning cannot delete operator-created copies elsewhere. No video/audio transcription or recovery of disconnected chat is provided. These source changes are not yet deployed.
