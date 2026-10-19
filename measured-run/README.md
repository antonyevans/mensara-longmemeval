# The scripts that produced the published numbers

These are the runner scripts exactly as they ran for the 17 October 2026 result, with only
host names, the SSH key path, test-account names and local file paths replaced by
placeholders (`TEST-BOX`, `DEPLOY_KEY`, `member-a`, `MEMBER-A-HASH` and so on). They are here
so you can see how every number was made. **You cannot run them on a hosted Mind**: they need
root on the server and the Mind's own source code. To replicate, use the harness in
[`lme_mind/`](../lme_mind/) instead (see the main [README](../README.md)).

## How this run differed from the public harness

| Step | Published run (these scripts) | Public harness (`lme_mind/`) |
|---|---|---|
| Import | The Mind's own `write` command as root on the server, 2 parallel lanes (one per test member, each in their own private folder) | `propose_write` over MCP as the owner, one question at a time |
| Session digests | The Mind's digest prompt, run ahead of time through the Codex CLI with `gpt-6-luna` (low effort) and placed in the Mind's own digest cache, keyed by the exact file bytes | Made by the Mind itself, on its five-minute history timer, with your Mind's model connection |
| Cross-session consolidation ("Latest values", "Preferences and habits") | Same request the Mind builds, run ahead of time with `gpt-6.1-sol` and placed in the Mind's cache | Made by the Mind itself |
| Timeline | `derive-history --offline` on the server: the Mind's own code, reading the cached digests | The Mind's own history timer |
| Clearing | Deleted under the repository gate as root | Delete proposals, approved by the signed-in owner |
| Reader | Codex CLI, `gpt-6.1-sol`, medium effort, signed in as each test member, five Mind read tools only | The same command, using your sign-in |
| Judge | Official prompt, `gpt-6-sol` at high effort through the Codex CLI | Official prompt; `openai:gpt-4o-2024-08-06` by default, or the same Codex judge |

We ran the digests ahead of time so the 500-question run did not wait on the server's model
connection; the cache key is the exact bytes of each session file, so the Mind's code used them
as if it had made them. The digest instructions are the Mind's own (`history/prompt.py`), copied
into `precompute_digests.py` with different line wrapping.

## Provenance

Runner commit `8628eb68` in our internal operations repository. The run's manifest recorded these
sha256 hashes of the files as checked out on the run machine (Windows line endings for the
first four). They are hashes of the files before the placeholders above were substituted, so the
copies here do not match them byte for byte. `run_dev.py` also imports two small helpers
(`prefill_cache.py`, `http_mind.py`) used only by the offline development loop, which are not
included.

| File | sha256 at run time |
|---|---|
| consolidation.py | `c5fdba0087e25aa936e3615f2d788713a96b8245093b076898a5424261c40b2f` |
| precompute_consolidations.py | `6e3a05c5a120bcac1e091ecf8c59456e13e3617a8fddf542f211d4c841e38b69` |
| precompute_digests.py | `62326a9ab799ef1a2a645e1187df8765ad832c172e3389974be6f5543a66abb6` |
| summarize_run.py | `5145b247dcd56b6e4bd290923ad3bad63dd0e922b059c63cd678d52d2bbc6562` |
| live_case.py | `c174f2c21606b8ec51ee57a5805e6257a59de621754fdad231e0c7c5c8f993a5` |
| lme_render.py | `a83a6d03d910f22b114ce130213875c5ddabf2c5c24c6d5e4dbbb8335528fbad` |
| run_dev.py | `f722638fdbfe460ef98092734d406933c278029e3d4133d8c3cff0b4ba27d1fd` |
| run_live.py | `407812214e1dcf4892437734fff7b5eba05a07b883003e6da2d6aa591d46c182` |

Dataset: `longmemeval_s_cleaned.json`, sha256 `d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442`.
The judge prompt is byte-identical to the official `get_anscheck_prompt` (checked in
`tests/test_offline.py`).
