# Local authoring and paid review reliability plan

Status: implemented for reviewed repairs, 2026-10-29, under the user's subsequent
authorization. See [operating notes](local-repair-reliability.md). Thresholds are
initial settings; broader model calibration remains ongoing. The completed trial
set includes a successful Python repair, a game repair with weak regression tests,
and a bounded follow-up that timed out without completing behavioral verification.

## Objective and evidence

Local models author implementation and tests. Paid models inspect candidates,
execute checks, and return concise findings with acceptance criteria. The harness
must distinguish useful exploration from stalled work and spend paid review
budget only when there is something new to assess.

Use game development as an integration workload, not a source of game-specific
runtime rules. The observed repair run `run_1d83ac2bd81d41768ca33a01ae4ec295`
received its review correctly but exhausted 60 model turns: 18 file reads,
40 Node-global probes, no edits, and no test execution. There was no context
compaction. The earlier paid review had a separate compaction/repetition failure.
These require evidence-driven progress control, not just larger budgets or
detecting byte-identical tool calls.

## 1. Establish reusable evidence and a baseline

- Create deterministic trace fixtures covering read-only exploration, equivalent
  capability probes with different arguments, coding through run_command,
  legitimate broad investigation, failing tests, and missing dependencies.
- Measure requests, local/paid tokens, repeated inspection, time until a relevant
  reproduction/edit/check, independent check results, and unresolved findings.
- Keep model-declared progress separate from controller-observed evidence. A
  successful tool exit or a changed commit ID is not proof of task progress.
- Record the current game failures as regressions alongside Python CLI/backend
  and configuration tasks. Do not put DOM names, game paths, or languages into
  general runtime stop rules.

## 2. Maintain durable repair state

- Introduce a bounded, controller-owned ledger shared by direct repair and loop
  repair paths: original goal, target commit, finding IDs, acceptance criteria,
  observations, reproduction evidence, source/test changes, test results,
  blockers, and the next intended step.
- Preserve provenance to full findings and outputs. Read files, probe results,
  and model explanations remain untrusted data, not permission changes.
- Restore the ledger from recorded events/checkpoints after compaction or
  restart. Keep current findings prominent without repeatedly attaching entire
  old conversations and test logs.
- Start with compatible adapters for existing prose reviews; do not invalidate
  saved chats or require another paid review to structure an old finding.

Relevant areas: mobile/repair_controls.py, mobile/task_context.py,
mobile/browser_agent.py, runtime/context.py, runtime/recovery.py.

## 3. Add a staged local progress guard

- Support investigation, reproduction, repair, and validation as working stages,
  with evidence-backed transitions. Allow returning to investigation when a
  concrete failure reveals a new question; do not enforce a rigid script.
- Observe actual source/test changes, including changes made through commands,
  rather than crediting write-tool invocations. Count a useful reproduction or
  a diagnosed dependency blocker as progress even before an edit.
- Track inspection and capability-probing effort relative to those milestones.
  Detect families of equivalent probes as well as exact repetition. Combine
  these signals with stage/budget usage; avoid a broad command-denylist.
- First intervene with specific controller feedback: what is already known,
  what remains unresolved, and which next step can advance the finding. Ask
  for a concrete experiment or repair step, not another general plan.
- If a bounded recovery allowance produces no new evidence, stop as
  local_stalled with preserved work and a useful report. Do not manufacture
  completion, force arbitrary edits, or silently switch to a paid author.
- Make thresholds configurable and calibrate them against both failure and
  legitimate-investigation fixtures. The initial policy is repair-specific;
  extend to other authoring workflows after checking false positives.

Relevant areas: runtime/agent.py, runtime/recovery.py, tools/guidance.py,
mobile/browser_agent.py. Keep policy logic independently testable.

## 4. Gate repeated paid reviews on new evidence

- Before automatically queueing a paid review, require an auditable candidate,
  required independent checks, and evidence addressing the outstanding findings.
  Missing tests or environment blockers remain explicit outcomes.
- Compare candidate content and verification evidence with the last reviewed
  state. A new run ID or no-change commit must not trigger duplicate spending.
- Permit a justified no-code resolution when materially new verification
  evidence answers a finding; do not require edits merely to satisfy the gate.
  An unchanged candidate with unchanged evidence is not eligible for an
  automatic repeated review. An explicitly requested manual repeat is separate.
- A local stall does not authorize a paid rescue. Any existing advisory paid
  diagnosis must remain explicitly authorized and consume the existing limits.
- Preserve unknown-usage, cancellation, crash-recovery, and no-automatic-replay
  protections. Never automatically merge an approval.

Relevant areas: mobile/loops.py, mobile/review_controls.py,
mobile/workspace_review.py, testing/checks.py.

## 5. Keep paid feedback compact and actionable

- Evolve findings to a bounded schema: ID, location, observed/expected behavior,
  impact, reproduction evidence, and acceptance criteria. Paid reviewers
  describe required changes; local models write patches and tests.
- Keep inspection and execution evidence available through references rather
  than copying full logs into every finding. Preserve reviewer discovery and
  independent test replay.
- Tune report and reasoning allowances from measured usage. Track actual paid
  output usage; a shorter visible summary alone is not evidence of lower billed
  output. Handle truncated/incomplete findings as unverified.
- Show the current stage, last meaningful milestone, recovery interventions,
  remaining budgets, and the reason another paid review is eligible or blocked.

## Validation and rollout

1. Land the fixtures, ledger, and diagnostics with guard decisions recorded but
   not enforced. Establish a baseline before tuning thresholds.
2. Enable bounded local recovery for reviewed repairs. Verify the 40-probe
   failure is interrupted before exhausting its full budget and that a healthy
   local run can reproduce, edit, test, and publish without interference.
3. Add duplicate-paid-review gates and compact findings with saved-report
   compatibility tests. Exercise both one-click repairs and authorized loops.
4. Run real local-model trials on the game and at least one non-browser project.
   Use mocked paid responses for routine tests; any live paid trial remains
   explicitly authorized and budgeted.

Acceptance must cover legitimate long investigations, command-based edits,
failing tests, unavailable runtimes, no-code rebuttals, context compaction,
restart/cancellation, unchanged candidates, and uncertain paid usage. Require
trace evidence for progress claims and source preservation. Compare guard
false positives and measured token usage with the baseline; do not claim model
reliability from mocked-provider tests alone.
