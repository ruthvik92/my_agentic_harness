# Local authoring and paid review

Local coding models write fixes and tests. Paid workspace reviewers read the
candidate, run checks, and return bounded findings with acceptance criteria.
Passing checks and making edits remain evidence, rather than automatic approval.

[Browser verification and capability recovery](browser-verification.md) explains
verified interactive tooling, classified command failures and persistent memory
of unavailable capabilities. These support the bounded repair policy below.

## Reviewed repairs

One-click repairs, repair loops, and continuations with an unresolved saved review
carry a controller-owned repair ledger. It includes the original goal, finding
IDs, acceptance criteria, known tooling, inspected files, actual file changes,
validation attempts, setup blockers and recovery decisions. A Node API probe or
successful file write is not by itself proof of useful repair progress: changes
are measured from regular project files and test attempts retain their actual
execution results. Arbitrary commands can author changes and are measured too.
Cache directories are excluded. Model-requested checks are labeled separately
from independent controller checks.

The compact ledger stays in fixed model context across compaction. Full state is
available in `scratch/repair-ledger.json`, but the authoritative copies are
immutable `repair.progress` events in the run ledger; changing the scratch file
cannot reset recovery counters. Resume reconstructs state from those events.
Original review reports and legacy saved chats remain supported. Legacy prose
is carried as a single legacy finding; precise structured findings are never
invented from a heuristic split of that prose.

When investigation or capability probing uses its allowance without a new
measured milestone, the controller redirects the local model to the specific
finding, a regression, a justified edit, or a concrete blocker. Equivalent probes
with different arguments count toward the same probing allowance. Novel reads
remain visible but cannot indefinitely postpone a repair milestone. After the
bounded recovery allowance is exhausted, the run ends as `local_stalled`. Work
and traces are retained, the failure is not approval, and a loop does not schedule
a paid rescue automatically. The guard also operates within tool batches.

Configuration is operator-controlled through the coding profile:

```yaml
repair_progress:
  mode: enforce                 # off, observe, enforce
  inspection_allowance: 16
  probe_allowance: 4
  recovery_allowance: 8
  max_recoveries: 2              # at most 3
  measurement_file_limit: 20000
  measurement_byte_limit: 268435456
```

The policy applies to reviewed local repairs; ordinary unrelated coding, chat,
and paid inspection are not subject to this repair policy. `observe` records
would-intervene decisions without stopping the model. Use it to calibrate larger
investigations; these defaults are initial settings, not a claim of universal
model reliability. Measurement never follows symlinks or special files. Source
metadata is also bounded to keep immutable state within the blob budget; an
unmeasurable project is a diagnostic limitation, not evidence of an edit.

## Automatic paid review eligibility

An automatic review requires a completed local attempt, an audited published
candidate and audited passing independent checks. Candidate *content* and
normalized verification evidence are fingerprinted. A new run ID, a no-change
commit, repeated output with a different duration, or another loop iteration
cannot authorize duplicate automatic spending.

A changed candidate or materially new independent evidence can qualify. This
allows a genuine no-code response to a finding, for example a new independently
executed regression. It does not certify that every acceptance criterion is
satisfied: the paid reviewer must assess the evidence. Failed tests stay local;
a duplicate state ends as `review_blocked` with the reason shown in the browser.
An explicit manual review remains a separate user-requested action. Existing
paid authorization, attempt/token limits, unknown-usage protections, cancellation
and no-automatic-replay rules remain in effect. Approval never merges automatically.

## Paid output and findings

The canonical input/context and token-accounting reference is [reviews](reviews.md).
This section describes the repair feedback contract.

New reviews return up to eight findings containing `id`, `location`, `observed`,
`expected`, `impact` and `acceptance`, with a short summary and executed test
commands. The reviewer describes required behavior rather than supplying patches.
Subsequent reviews receive compact prior findings to retain their IDs.

The reviewer profile's `output_reserve_tokens` is respected as an upper limit,
including for reasoning models; selecting a model no longer increases a smaller
operator allowance. Small allowances can produce incomplete reviews, which remain
unverified. Token accounting reports paid input, output, cached input and reported
reasoning usage. Reasoning is a breakdown already included in reported output,
not an additional charge counted twice. Missing reasoning detail is shown as
unavailable; a short visible response alone does not establish low billed output.

## Repeatable local trials

Run one bounded local attempt in a new output directory:

```bash
uv run --locked python scripts/check_local_repairs.py \
  --case python --model qwen3.8:27b \
  --image sha256:YOUR_TRUSTED_IMAGE \
  --output /absolute/path/to/new-trial
```

The `game` case additionally takes `--game-source /absolute/path/to/game` and
requires a trusted image with Node installed. `--finding-file` supplies a bounded
saved finding for a focused follow-up. The script copies the project into an
isolated repository, invokes the real browser repair runtime with Ollama, and
retains task/configuration, run IDs, traces, candidate artifacts, test evidence,
usage and diagnostics. It never calls a paid model or merges its result. The game
fixture's owner test contract runs Python and all `tests/test_*.js` scripts, so
new JavaScript regressions participate in independent checks.

Deterministic regression tests cover varying probes, successful and stalled
recovery, observation mode, command-based edits, missing dependencies, checkpoints,
paid gates, duplicate states, and accounting. Real local-model trials complement
those checks. They are completion/test evidence, not a replacement for reviewing
whether the generated tests actually exercise behavior. In the first game trial,
independent artifact inspection caught source-text assertions masquerading as
behavioral regressions despite passing checks.
