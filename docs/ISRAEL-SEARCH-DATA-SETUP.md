# Israel keyword data — setup options

Verified against provider documentation on 2026-11-10. No Google Trends, keyword-volume account or credentials are configured in RoboRath; the new help topic says so. Ordinary search/news retrieval is separate from Trends and Keyword Planner.

Help release checkpoint: `81244ba` deployed to ORA3, active/running with zero restarts. All four pages and nineteen topics were checked in the installed runtime; worst-case text including maximum username and owner title is 317 bytes. All topic routes are recognized as help permissions. Local full suite 214 passed and CI run 42755728761 passed on Python 3.13 and 3.14. Backup `/var/lib/roborath/backups/help-20261110T042515Z`. Google data access remains unconfigured; next action depends on the owner's chosen provider and securely provisioned account access. Mem0 connection still requires reauthentication; this is the durable checkpoint.

## Trends: time-series search interest

The quickest low-friction trial is an authorized third-party Trends provider. SerpApi's current Free plan lists 250 searches/month and 50/hour. It requires a SerpApi API key. An Israel request would use country `IL`, the literal keyword and explicit start/end dates; timeline and subregion requests may consume separate queries. Those responses are relative interest, not exact search counts. Do not enable automatic paid renewals for this trial. A key alone does not connect RoboRath: the adapter still needs implementation and live quota/response validation once access is supplied securely.

Official alternative: Google's Trends API is still an application-based alpha. Apply through its developer page and use the approved account's provisioning/credentials if accepted. This is not a generally available API unlocked by an ordinary Google Search key.

For either route, the output must distinguish reportable interest, insufficient data and provider failure. Zero/absent data is not proof of no searches. Google may suppress or add statistical noise to low-volume terms. No searcher identities are exposed, and a shared name does not identify a particular Twitch user. City/subregion detail is shown only if returned with enough data.

## Approximate keyword volume

The Google Ads API itself has no usage charge; Cloud billing is optional for API setup, with quotas still applying. A paid third-party provider is not required. Source: [official Cloud/OAuth setup](https://developers.google.com/google-ads/api/docs/oauth/cloud-project). The recommended no-provider-fee route for this owner is official Keyword Planner API approval plus OAuth, not a paid Trends reseller. This does not change the data's approximate monthly granularity or make a missing keyword a verified zero.

Google Ads Keyword Planner historical metrics provide approximate monthly volumes and keyword ideas with geographic targeting. This differs from an exact count over arbitrary 60-day boundaries. Close variants may be combined; missing small keywords do not prove zero searches.

Current official onboarding has changed: developer tokens were sunset on September 9, 2026. Use a Google Cloud project with Google Ads API enabled, OAuth credentials and authorized access to the relevant Google Ads customer account. Apply for **Basic or Standard API access** through Cloud Console for keyword planning; Explorer access excludes `KeywordPlanIdeaService`. Basic/Standard applications require the documented brand verification. Some older Google pages still describe developer tokens; follow the current access-policy page.

Once approved, a private integration would store the project/OAuth credential references and customer account ID on ORA3, resolve Israel's geographic target, issue bounded read-only historical-metrics/keyword-ideas calls and label the resulting estimates and periods. Never paste keys or refresh tokens into Twitch or commit them to the repository. No ad campaign or ad spend is needed to implement read-only calls, but actual account eligibility and returned data must be tested.

An owner-provided Trends/Keyword Planner CSV is another way to evaluate data coverage before setting up an API. It does not provide automatic updates.

Sources: [Google Trends alpha](https://developers.google.com/search/apis/trends), [Google data FAQ](https://support.google.com/trends/answer/4365533?hl=en), [SerpApi Trends API](https://serpapi.com/google-trends-api), [SerpApi pricing](https://serpapi.com/pricing), [Google Ads historical metrics](https://developers.google.com/google-ads/api/docs/keyword-planning/generate-historical-metrics), [current Google Ads onboarding](https://developers.google.com/google-ads/api/docs/api-policy/developer-token), [API access restrictions](https://developers.google.com/google-ads/api/docs/api-policy/access-levels?hl=en).
