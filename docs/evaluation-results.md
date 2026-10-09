# Live evaluation — October 6, 2026

Configured model: `qwen3:30b-a3b-instruct-2507-q8_0`. The same model, image, schemas, instructions and 2k output reserve were used for both profiles. Calculator is the development control; mean and clamp are additional held-out repairs.

| Context | Verified | Mean wall time | Invalid calls | Compactions | Peak sampled GPU VRAM | Peak GPU temperature |
| --- | --- | --- | --- | --- | --- | --- |
| 8192 | 3/3 | 10.75s | 0 | 3 | 32166 MiB | 56°C |
| 16384 | 3/3 | 10.19s | 0 | 0 | 32932 MiB | 63°C |

All six runs audited cleanly. All models were resident before the measured tasks. Sampled decode rates were approximately 152–171 tokens/s; raw usage and prompt/decode durations are retained per request. Recovery attempts: zero.

One round of three small tasks per profile, run sequentially. The latency difference is not sufficient evidence to change the default 8k context. Hardware sampling is approximate; probes warmed the model, and these measurements do not establish cold-start latency or sustained thermal behavior.

| Task | 8k run | 16k run |
| --- | --- | --- |
| calculator | `run_72e7999e48444aa6a4ad48ed4b1b0e50` | `run_efc954cdd0b94749bd9f063ea3ca9892` |
| mean | `run_00cacb2a9ac64d6890fb588367be9dbf` | `run_4e203b72f1694ad1b2228a7c111d5dcc` |
| clamp | `run_cc06f976c4a3489f946e7c20888ae38d` | `run_eb24cfad27c44746a47f298440b74474` |

Full local report: `/home/ruthvik/.local/share/local-agent/control/reports/34deaeac7ccdb65b8a605a41882f57df6a4e87dcaa8736a9e97197019747bd6b.json`.
Immutable report reference: `blob://34deaeac7ccdb65b8a605a41882f57df6a4e87dcaa8736a9e97197019747bd6b`.

Reproduce with `uv run --locked local-agent evaluate --windows 8192 16384 --rounds 1`. New runs receive fresh workspaces and IDs.
