# Routing measurements and Google Trends integration boundary

Installed model inventories were checked on ORA1, ORA3, ORA5, ORA6, ORA7 and ORA8. The user's specialized model is `tev1:0.8b` on ORA8, with decision capability. It uses Ollama `/v1/systemone`, not the ordinary generate/chat API. No new model was downloaded.

Qwen3.5 2B cold calls on ORA3/ORA5 took about 6.15/5.83 seconds. Warm constrained-output trials took roughly 1.29–2.09 seconds and misclassified three simple route examples. These small diagnostic runs are not an accuracy benchmark.

TEV1's proper typed API returned chat/fact/search for three synthetic examples. Cold latency was 9.191 seconds; the subsequent two warm calls were 0.766 and 0.770 seconds, excluding ORA3-to-ORA8 overhead. The explanation sample had low confidence (0.24), with verification/current-lookup confidence about 0.67/0.84. These three cases do not demonstrate improved speed and accuracy over deterministic rules. Model routing therefore remains disabled. An optional adapter has a 1.2-second timeout, minimum confidence 0.65, and two-minute failure circuit. Clear commands, statistics, jokes and lookup/verification/research requests bypass inference. Authorization never depends on a classification result.

References: [Ollama decision API](https://ollama.com/blog/ollama-now-supports-jev-style-decision-models), [TEV1 model](https://ollama.com/library/tev1).

Google's official Trends API remains an application-based alpha at inspection. Access requires acceptance and the credentials/provisioning supplied for that account; no working Trends API access is configured in RoboRath. It supports date aggregation and region/subregion analysis. Google Trends UI data is relative search interest, not an exact count of searches; the alpha's consistently scaled values likewise must not be presented as raw search counts. Low-volume usernames can be suppressed or noisy. Missing/zero data is insufficient evidence to say nobody searched, and a matching term cannot identify the searchers or prove they meant this particular Twitch user.

Proposed truthful report: literal term and spelling variants; country Israel (`IL`); exact start/end dates; reportable interest or insufficient data; series and peak dates; geographic breakdown only where supplied; provider/scale/source timestamp. No fabricated absolute volume, person identity or city detail. Default statement for no usable data: “Insufficient Google Trends data for this term, Israel, and period; this does not prove zero searches.”

Access options: apply for the official alpha; use an authorized third-party Trends provider such as SerpApi with its API key and bounded quota; or import an owner-provided Google Trends CSV. No account, purchase, application submission, API integration or live Trends query was performed in this phase. A third-party key cannot remove Google's low-volume limits.

Sources: [official alpha](https://developers.google.com/search/apis/trends), [Google data FAQ](https://support.google.com/trends/answer/4365533?hl=en), [SerpApi Trends API](https://serpapi.com/google-trends-api).

Useful next counters, separate from implemented leaderboards: average words/message; per-hour activity; distinct participants; first-time speakers; questions answered vs failed; invoke balances; source-confirmed corrections. Prefer descriptive counters over inferred traits, viewer presence or watch-time claims. Raw transcript and counts expire after 30 days.
