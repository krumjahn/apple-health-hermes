# Apple Health Data for Hermes

Read selected daily metrics from **Health Data AI Analyzer** on your Mac.
This native Hermes adapter uses the app's existing local API. It does not
access HealthKit, import exports, or start the app's API for you.

**Privacy:** the connection to the Mac app is local. Results returned to Hermes
enter your conversation and may be sent to your configured AI model provider
and retained in Hermes chat history. This is not a promise of wholly local AI.
Use a private, trusted profile and review its provider and retention settings
before opting in. Do not enable this in a shared chat or gateway where other
people can ask the agent to retrieve your health summaries.

## Requirements

- Hermes **0.23.1 or later**, running directly on the same Mac as the app.
- [Health Data AI Analyzer](https://applehealthdata.com), with its local API
  available at `127.0.0.1:8765` and a selected integration dataset.
- You manually enable Local API, select the intended dataset, supply its local
  API token to Hermes, and opt in to this plugin's health access.

The Mac app is a separate product; its availability and any subscription
requirements are determined by the app. Installing this free MIT adapter does
not unlock app features. This version does not support a remote Mac, a VPS,
or a container's separate loopback network. It adds no Python dependencies.

## Install and opt in

Until the catalog entry is accepted, install from the standalone repository:

```sh
hermes plugins install krumjahn/apple-health-hermes
```

1. In the Mac app's **Integrations** screen, select the intended analysis
   (for example, **Use Last Analysis** or **Use for Integrations**) and turn on
   **Local API** yourself. Check that the dataset contains the date you want.
2. In Hermes Desktop, open this plugin under **Settings → Plugins**. Enter the
   Mac app's local API token in **Mac app local API token**, a masked secret
   field backed by `APPLE_HEALTH_ANALYZER_TOKEN`. The app's integration screen
   identifies its token file. If your app version only offers **Copy Token Path**,
   retrieve the token yourself and transfer it directly to the masked field.
   **Never paste a token into chat, a prompt, a screenshot, or a tool argument.**
   The plugin does not discover or read token files. CLI users can supply this
   variable through Hermes's supported profile secret configuration.
3. Review the privacy notice, then turn on **Allow health summaries in Hermes**.
   This defaults to off and is separate from enabling the plugin.
   The non-secret CLI equivalent, only after you decide to opt in, is:

   ```sh
   hermes config set plugins.entries.apple-health-analyzer.settings.allow_health_access true
   ```

4. Enable the installed plugin through Hermes and start a new conversation.
   Ask: “Check Apple Health Analyzer's connection.”
5. Request an explicit date and metrics, for example:
   “Show my steps and sleep for 2026-01-02 from Apple Health Analyzer.”
   Choose a date actually present in your own dataset.

To revoke access, switch **Allow health summaries in Hermes** off (or set the
same config key to `false`). Every call rechecks this setting, so revocation
does not need a restart. You can also disable/remove the plugin, remove its
secret through Hermes, or switch off the Mac API. Revocation does not erase
existing conversations or provider copies; use those products' retention controls.

## Tools and limits

| Tool | Result |
| --- | --- |
| `apple_health_analyzer_status` | App identity/version and whether a dataset is loaded. No health values, metric list, file paths, or token. |
| `apple_health_analyzer_daily_metrics` | One explicit `YYYY-MM-DD` date and selected groups: `steps`, `sleep`, `workouts`, `heart_rate`, `hrv`. |

The daily tool returns numeric values and available seven-day baselines/deltas
with units. Sleep uses hours, workout duration uses minutes, heart rate uses
beats/minute, and HRV uses milliseconds (SDNN). Missing values remain `null`,
not zero. Baselines come from the app's available data and do not guarantee
that all seven days were measured. Dates follow the app's dataset calendar.
The dataset may be old; this adapter does not sync it.

If the app falls back to another date, the adapter withholds all health values
and reports `date_unavailable`. It never labels the latest summary as the date
you requested. It omits narrative signals, recovery scores, workout types,
sleep times, and unselected metrics. These are recorded summaries, not
diagnosis, treatment recommendations, or medical advice.

## Data flow and security disclosure

- **Local requests:** only GETs to the fixed literal address
  `http://127.0.0.1:8765`: `/openclaw/status` and
  `/openclaw/daily-brief?date=YYYY-MM-DD`. There is no configurable host,
  URL, or port. Proxy variables are not used; redirects are never followed.
- **Credential:** only `APPLE_HEALTH_ANALYZER_TOKEN`, obtained per call using
  Hermes's public `agent.secret_scope.get_secret`. It is sent only in
  `X-Health-Analyzer-Token` on a daily-summary request. Hermes stores the
  secret. This plugin neither reads nor writes credential files; status sends
  no token.
- **Consent:** no requests, including status, until the user enables
  `allow_health_access`. Import and registration do not probe the app. The
  agent must not enable the setting for the user.
- **Scope:** the app returns a whole daily summary locally. The adapter holds
  that response transiently and returns only selected numeric groups to Hermes.
  It does not read XML/ZIP files or contact Apple/iCloud, the app's cloud-summary
  service, OpenRouter, or a model API itself.
- **Limits:** five-second socket timeout, 64 KiB response cap, no automatic
  retries, strict date/metric validation, and fixed errors without server-body
  or exception echoes. A local process impersonating the app on its port is
  outside this adapter's trust boundary.
- **Persistence:** no plugin health database, file writes, logging, analytics,
  hooks, background jobs, shell commands, self-updater, or bundled binaries.
  Hermes and its configured provider can retain returned conversation results.
- **Sharing:** opt-in applies to the active profile. Anyone able to invoke
  tools in that profile may request summaries. Keep it private. This plugin
  does not add a separate person-level authorization system.

## Troubleshooting

| Error | Action |
| --- | --- |
| `consent_required` | Review the privacy notice and opt in yourself, if desired. |
| `token_required` / `unauthorized` | Configure the correct token in Hermes's secret field; never send it to the agent. |
| `request_failed` | Check the Mac app is running, Local API is on, and Hermes is on the same Mac. |
| `dataset_unavailable` | Select an analyzed dataset in the Mac app. |
| `date_unavailable` | Choose a date present in that dataset. No fallback values were shared. |
| `invalid_response` | Check app compatibility; do not bypass validation or forward the raw response. |

## Development and verification

```sh
python3 -B -m unittest discover -s tests -v
hermes plugins validate /absolute/path/to/apple-health-hermes --install-deps
```

Tests use invented values and ephemeral loopback fixture servers. They never
contact the app on port 8765, read a real token, or load health exports.
Validation loads the real Hermes registration surface with health access off.

The adapter is grounded in the Mac app's actual API implementation and is
independent of the older, broader `health-analyzer-mcp` npm package and its
automatic token-file discovery. It does not install or invoke that MCP server.
No real-health end-to-end test is claimed. Report issues using error codes,
versions, and synthetic reproductions; never attach health records or tokens.
