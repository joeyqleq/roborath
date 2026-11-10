# Israel keyword data — setup options

Verified against provider documentation on 2026-11-10. No Google Trends, keyword-volume account or credentials are configured in RoboRath; the new help topic says so. Ordinary search/news retrieval is separate from Trends and Keyword Planner.

Help release checkpoint: `81244ba` deployed to ORA3, active/running with zero restarts. All four pages and nineteen topics were checked in the installed runtime; worst-case text including maximum username and owner title is 317 bytes. All topic routes are recognized as help permissions. Local full suite 214 passed and CI run 42755728761 passed on Python 3.13 and 3.14. Backup `/var/lib/roborath/backups/help-20261110T042515Z`. Google data access remains unconfigured; next action depends on the owner's chosen provider and securely provisioned account access. Mem0 connection still requires reauthentication; this is the durable checkpoint.

## Trends: time-series search interest

The quickest low-friction trial is an authorized third-party Trends provider. SerpApi's current Free plan lists 250 searches/month and 50/hour. It requires a SerpApi API key. An Israel request would use country `IL`, the literal keyword and explicit start/end dates; timeline and subregion requests may consume separate queries. Those responses are relative interest, not exact search counts. Do not enable automatic paid renewals for this trial. A key alone does not connect RoboRath: the adapter still needs implementation and live quota/response validation once access is supplied securely.

Official alternative: Google's Trends API is still an application-based alpha. Apply through its developer page and use the approved account's provisioning/credentials if accepted. This is not a generally available API unlocked by an ordinary Google Search key.

For either route, the output must distinguish reportable interest, insufficient data and provider failure. Zero/absent data is not proof of no searches. Google may suppress or add statistical noise to low-volume terms. No searcher identities are exposed, and a shared name does not identify a particular Twitch user. City/subregion detail is shown only if returned with enough data.

## Approximate keyword volume

The Google Ads API itself has no usage charge; Cloud billing is optional for API setup, with quotas still applying. A paid third-party provider is not required. Source: [official Cloud/OAuth setup](https://developers.google.com/google-ads/api/docs/oauth/cloud-project). For approximate monthly volume, the no-provider-fee route is official Keyword Planner API approval plus OAuth. The owner's later clarification prioritizes dated interest rather than volume; Google Trends is the closer product fit for that request. Ads OAuth does not grant Trends access. Neither route makes missing data a verified zero.

Counting repair checkpoint: runtime `fcb5e77` deployed at 2026-11-10 04:31 UTC, active with zero restarts. The owner's real “howw many words has ... said ... what's his rank?” request previously missed the narrow handler and elicited a false model claim that historical logs were unavailable. Typo normalization, said/sent/written/spoken variants, observed-login fallback and per-user rank now handle it deterministically. The exact wording was verified against the installed retained transcript, and 43 focused tests passed. Backup `/var/lib/roborath/backups/activity-grammar-20261110T043135Z`; CI run 42756389146. Google integration still awaits approved account access; free API usage does not waive authorization, quotas or low-volume data limits. Mem0 remains unavailable due reauthentication, so this is the durable checkpoint.

Google Ads Keyword Planner historical metrics provide approximate monthly volumes and keyword ideas with geographic targeting. This differs from an exact count over arbitrary 60-day boundaries. Close variants may be combined; missing small keywords do not prove zero searches.

Current official onboarding has changed: developer tokens were sunset on September 9, 2026. Use a Google Cloud project with Google Ads API enabled, OAuth credentials and authorized access to the relevant Google Ads customer account. Apply for **Basic or Standard API access** through Cloud Console for keyword planning; Explorer access excludes `KeywordPlanIdeaService`. Basic/Standard applications require the documented brand verification. Some older Google pages still describe developer tokens; follow the current access-policy page.

Once approved, a private integration would store the project/OAuth credential references and customer account ID on ORA3, resolve Israel's geographic target, issue bounded read-only historical-metrics/keyword-ideas calls and label the resulting estimates and periods. Never paste keys or refresh tokens into Twitch or commit them to the repository. No ad campaign or ad spend is needed to implement read-only calls, but actual account eligibility and returned data must be tested.

An owner-provided Trends/Keyword Planner CSV is another way to evaluate data coverage before setting up an API. It does not provide automatic updates.

Sources: [Google Trends alpha](https://developers.google.com/search/apis/trends), [Google data FAQ](https://support.google.com/trends/answer/4365533?hl=en), [SerpApi Trends API](https://serpapi.com/google-trends-api), [SerpApi pricing](https://serpapi.com/pricing), [Google Ads historical metrics](https://developers.google.com/google-ads/api/docs/keyword-planning/generate-historical-metrics), [current Google Ads onboarding](https://developers.google.com/google-ads/api/docs/api-policy/developer-token), [API access restrictions](https://developers.google.com/google-ads/api/docs/api-policy/access-levels?hl=en).


## Owner clarification: handle, country and dates (2026-11-10)

Requested behavior, still unconnected: `!ask is my username searched in Israel?` selects the authenticated sender's Twitch login. An explicit requested username/quoted keyword overrides self-reference, including another chatter's handle. Preserve the requested spelling; do not silently merge username variants. Israel and the last 60 days are proposed defaults from prior requests; explicit country/date ranges override. Country support should use the provider's supported geographic targets, not a separate credential per country. City/subregion output is conditional on provider coverage and enough data. A returned date is an aggregate reporting bucket, never an identified individual's search timestamp. Result states: reportable interest, no reportable data, unavailable/error. Low-volume noise means a chart signal alone is not proof somebody searched for that particular Twitch person.

For the clarified priority, first test a representative literal username in the free Google Trends browser UI with Israel and the desired dates. This requires no Ads OAuth. A CSV/export link can establish data coverage before spending time on integration. Google's official Trends API remains restricted alpha: apply through https://developers.google.com/search/apis/trends and follow the approved onboarding if accepted. Do not invent a general Trends OAuth scope or promise that enabling Ads API unlocks it.

### If approximate monthly Keyword Planner data is also wanted

1. Have a real Google Ads customer account that the authorizing Google user can access; record its customer ID. The Cloud project ID and Ads customer ID are different.
2. Create/select a Google Cloud project and enable Google Ads API. API usage has no charge and Cloud billing is optional, with quotas applying.
3. On the project's Google Ads API Overview, apply Test -> Explorer -> Basic. Planning/KeywordPlanIdeaService is excluded from Explorer. Basic requires brand verification first; apply honestly for the intended use and do not assume approval. Current onboarding no longer requires applying for a developer token (sunset 2026-09-09).
4. Configure Google Auth Platform branding/audience/consent; for an initial personal test add the authorizing Google account as a test user. Add OAuth scope `https://www.googleapis.com/auth/adwords`.
5. Create an OAuth client of type Desktop app for the local one-user authorization flow, download the client JSON, and place it outside the repository in a private local directory. User supplies the file path rather than pasting its client secret into chat. A Web app flow instead requires a registered exact redirect URI.
6. The operator runs a local browser consent flow using that client and offline access. The Google account signs in and grants consent; the integration saves the resulting refresh token privately on ORA3. No password or pasted short-lived access token is needed.
7. Supply project ID, API approval status and Ads customer ID; if access goes through an Ads manager, also identify its login-customer ID. Keep credential JSON and refresh tokens out of Twitch/GitHub/chat.
8. External OAuth apps left in Testing normally have refresh tokens that expire after seven days for Ads scopes. Production app configuration/verification must be resolved before promising unattended long-term operation.
9. Validate a bounded historical-metrics request on the authorized customer account. Report approximate monthly periods and any close-variant grouping; do not present this as daily Trends results or an exact arbitrary 60-day count. No ad campaign creation is part of this integration.

Primary references: [Cloud project/setup and API cost](https://developers.google.com/google-ads/api/docs/oauth/cloud-project), [access levels and planning restrictions](https://developers.google.com/google-ads/api/docs/api-policy/access-levels), [single-user OAuth setup](https://developers.google.com/google-ads/api/docs/oauth/single-user-authentication), [OAuth scope and offline access](https://developers.google.com/google-ads/api/docs/oauth/internals), [testing-token expiry](https://developers.google.com/identity/protocols/oauth2), [historical metrics and close variants](https://developers.google.com/google-ads/api/docs/keyword-planning/generate-historical-metrics), [Trends aggregation/noise/low-volume limits](https://support.google.com/trends/answer/4365533?hl=en).

[JQMEM v2 | kind=checkpoint | app=roborath | harness=chatgpt-desktop]
Objective: Dated username search-interest lookup with sender default, explicit username override and any supported country.
Decision: Trends best fits date-based interest; Ads OAuth only provides Keyword Planner monthly metrics, not Trends access. No provider credentials or integration configured.
Next: User tests representative term in free Trends UI/applies for official alpha; if monthly Ads data also wanted, provide private OAuth client JSON path, project ID/access level, Ads customer ID, then perform local consent. Never claim a suppressed zero is no searches. Mem0 connector requires reauthentication.
