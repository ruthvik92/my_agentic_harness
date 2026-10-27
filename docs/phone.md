# Ask the harness from your phone

> **Legacy — phone-v1 screenshot guide.** This document describes the legacy
> phone-v1 screenshot interface. The primary guide for browser launching,
> config selection and the editor is [browser.md](browser.md).
>
> To reproduce the legacy screenshot setup, run
> `./browser --agent config/phone.yaml` — `./phone` now aliases the browser
> default. The remaining text below is preserved as a legacy reference.

Start the phone interface on the computer that runs Ollama and Docker:

```bash
./phone --host 192.168.0.40
```

Use your computer's current LAN IPv4 address. Run `hostname -I` to find it;
choose the address for your home network. `192.168.0.40` was this computer's
address when the interface was tested. The launcher finds UV on your PATH or in
`~/.local/bin`, changes to the harness directory, and runs the installed CLI.

The terminal prints the browser URL and a pairing code. On your phone, connect to
the same Wi-Fi, open **http://192.168.0.40:8767**, and enter that code. Keep the
computer awake and the terminal running. Use this HTTP interface on trusted home
Wi-Fi. Each server start creates a new pairing code; the code grants access to
questions, answers and traces on that server.

The full command is:

```bash
uv run --locked local-agent phone-web \
  --host 192.168.0.40 --port 8767 --agent config/phone.yaml
```

Without `--host`, the server binds to `127.0.0.1` for access from the computer.
On a phone, `localhost` refers to the phone itself. Use the computer's LAN address
in the phone browser. The server accepts explicit private IPv4 addresses and
loopback. To select a different data directory, put `--data-root PATH` before
`phone-web` in the full command.

## Send a screenshot and ask questions

1. Pair with the terminal code.
   **Saved chats (history)**, above the model selectors, lists earlier conversations. A count below it shows how many chats are retained. Open one to restore its image and
   messages, or choose **New chat** to start another.
2. Choose a schematic image (source file up to **20 MiB**). The browser checks
   the actual image bytes, converts other decodable formats to PNG/JPEG, and
   resizes images above **16 million pixels**. Prepared uploads must fit **4 MiB**.
   Conversion or resizing is shown beside the preview; check that labels remain readable.
3. Select **Image interpretation / chat model**. Its dropdown lists installed
   Ollama models and their advertised capabilities (vision, tools, thinking,
   completion). Models load when a question starts; Refresh updates the catalog.
   An image requires a vision model. Type a question, such as “Explain this amplifier stage. Which labels and
   connections are uncertain?” and tap **Ask**.
4. Wait for the queued/running status to become completed. The answer shows the
   model and run ID. Tap **Show / hide trace events** for the run timeline.
5. Ask a follow-up. The screenshot is reused, together with up to three recent
   complete question/answer exchanges (16,000 characters in total).

Model replies render Markdown headings, emphasis, lists, tables, links and code
blocks. **Only the latest model reply opens by default**; older replies show a
compact model/preview header. Tap that header to expand or collapse any reply.
Reopening a saved chat restores the same default. Wide tables and code scroll
inside the answer at phone width. Your questions remain plain text.

Formatting is a derived display view: saved message text, model memory and token
accounting retain the original Markdown. Raw HTML/scripts are displayed as text;
unsafe link schemes and model-generated image elements are removed. Rendering
uses locally installed packages rather than a browser CDN.

**New Conversation** clears the screenshot and conversation. Choosing a new image
also starts a new conversation after it loads successfully. A failed replacement
keeps the previous image and conversation. Completed threads and their uploaded
images are saved on the computer and restored after reload or from another paired
device. New Conversation leaves the earlier saved chat available. A new image is
saved when its first question is submitted; an unsubmitted image is still only in
the tab. A pending job ID and its question are retained locally so reloading can
continue checking that job. If the network
connection drops, **Resume** checks the same job without submitting it again.

A question can also be sent without an image. The app has two circuit stages:

- **Ask** sends the screenshot to the selected vision model for observations.
- **Infer draft netlist** sends those recorded observations and recent chat to
  the selected **Netlist inference model (text)**. The text model receives no
  image; it proposes partial SPICE text and uncertain connections in the chat.
  It does not compile a circuit graph, run SPICE, or export into the circuit case.

The compact breakdown shows the actual most recent VLM, chat, netlist and reviewer
models used in this thread, plus saved exchanges, memory limits and feedback.
Each answer retains its own model/provider/run ID, so later selection changes do
not relabel earlier answers. Advertised capabilities are not circuit accuracy scores.
The existing `local-agent circuit` workflow still handles PDF extraction and
graph-based draft netlists. Model answers remain
**unverified**, including plausible circuit interpretations.

Full chat stays visible (up to 100 exchanges per thread). Each new question gets
the latest three complete exchanges, capped at 16,000 characters; older messages
are saved but are not silently claimed to be in the model context. A large latest
exchange is truncated to fit. Netlist inference also includes the latest VLM
observations, capped at 7,000 characters. This is memory within the selected
thread, not automatic retrieval across unrelated chats.

Each model reply has **Rate this answer: 👍 / 👎** below its content. Expand an
older reply to reach its buttons. Votes are saved per answer and restored after
reload or from another paired device. Tap the selected vote again to clear it.
Voting does not rebuild the transcript or close replies you opened. Legacy
imported history without a job/answer ID has disabled controls because its model
provenance cannot be attributed reliably.

Each changed answer vote creates an audited `phone.answer_feedback` activity
with answer/job ID, source model run ID, actual model/provider, stage (`vision`,
`chat`, `netlist`, or `review`), owner, original answer timestamp, recovered flag,
and previous/new vote. These values come from the saved answer, not the current
model dropdown or client-supplied model fields. Original completed model runs are
unchanged. Repeating the same vote is idempotent; clearing/changing preserves
past events and updates the answer's current vote.

The protected endpoint is
`POST /api/threads/THREAD_ID/answers/JOB_ID/feedback` with
`{"vote":"up"}`, `{"vote":"down"}` or `{"vote":null}`. Only answers belonging
to that thread can be rated. Votes never enter the model's conversation memory.
Answer events are visible in **Show / hide trace events** for the thread and
are stored in the normal ledger alongside other browser activity.

This creates attributable data for future routing; routing does **not yet** use
these votes. A future scorer should use the latest vote per owner/answer, ignore
cleared ratings, separate task stages and recovered/failed results, and avoid
counting repeated vote changes as independent successes. Existing whole-thread
ratings are not copied into individual answers.

The **top** 👍 / 👎 buttons still rate the current thread. Tap the selected vote again to clear
it. Votes persist and create audited `phone.feedback` events with the thread ID,
local owner and related model run IDs. Repeating the same vote is idempotent.

## Paid OpenAI review

The reviewer uses [config/phone-verifier.yaml](../config/phone-verifier.yaml),
defaulting to **gpt-6-astra** through the official OpenAI API. It supports image
input and Chat Completions ([official model documentation](https://developers.openai.com/api/docs/models/gpt-6-astra)).
The **OpenAI reviewer (paid)** dropdown is independent of the local vision/chat
and netlist selectors. It offers Astra, GPT-6.1 Sol, GPT-6 Luna, GPT-5.4,
GPT-5.4 Mini and the previous GPT-4.1 reviewer, with capability and tradeoff labels.
Astra is OpenAI's most capable option; that is not a schematic accuracy benchmark.
[GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol) offers a
lower-cost alternative for complex work. Browser selection is remembered across
reloads and New Conversation. Each submitted review snapshots its actual model
in the job, answer and trace; changing the dropdown does not alter earlier runs.

Model catalogs use a read-only OpenAI `/models` request with the server-side key.
Only documented image-capable Chat Completions models supported by this harness
are offered; models absent from a successful account listing are disabled. The
list does not contain every embedding/audio/image-generation model. Refresh model
catalogs rechecks availability. An authentication rejection disables review. If
discovery is temporarily unavailable, supported choices remain usable with a
visible warning and access is checked during the requested review. Listing a
model does not establish funded quota or successful inference. Merely selecting
or refreshing does not make a paid inference request.

The reasoning models use `reasoning_effort: medium`, no tools or sampling
parameters, and a 16,384-token completion cap shared by reasoning and visible
answer. GPT-4.1 omits reasoning effort and uses a 4,096-token cap. The configured
65,536-token context budget is a conservative harness limit, not the model's
maximum. The key is never stored in the browser. You can still pass
`--verifier-agent PATH` to customize the official endpoint's server settings.

In the computer's launch terminal:

```bash
read -rsp 'OpenAI API key: ' OPENAI_API_KEY
echo
export OPENAI_API_KEY
./phone --host 192.168.0.40
```

Open a saved thread and press **Review with OpenAI (paid)**. This explicitly
sends its saved image and recent conversation (the same memory bounds above) to
OpenAI; API billing applies. The button is disabled until the server has a key and a chat is selected. It also stays disabled while a question is running. The note beside it explains the missing prerequisite. Key presence enables the button; the provider validates the key and billing when you request a review.
The review appears separately with its own run/trace and critiques earlier
answers and netlist text. Earlier answers are preserved. This is an independent
model opinion, not electrical verification; it cannot prove connectivity or
simulation results. There are no automatic paid reviews or paid replays on restart. The reviewer
allows two controller operations: workspace initialization and final diff capture.
These share the runtime's attempted-tool budget even though the model has no tools.
A captured OpenAI review from the earlier one-operation budget bug can be restored
at startup without another API call. Restored answers explicitly say **Recovered
recorded OpenAI review**, remain unverified, and link to the original failed run.
Job/run failure status is preserved; a separate `phone.review_recovered` activity
records the recovery and saved response reference. The complete recovered text
is also in the job folder's private `recovered-review.md`.

If you added `export OPENAI_API_KEY=...` to `~/.bashrc`, open a fresh Bash
terminal and restart the phone server from that terminal. An already running
server cannot see later changes to `.bashrc` or another terminal's environment.
A noninteractive service does not automatically source `.bashrc`; supply its
server environment through its launcher instead. Reload and pair again after
restarting. Never paste the key into the phone chat or pairing field.

## Token usage and estimated savings

Open **Token usage and estimated OpenAI savings** below the model breakdown.
It shows the selected chat and **all saved phone chats**; it does not include
unrelated CLI circuit/coding runs. Totals refresh when a chat is opened or a
question finishes, and the Refresh button updates them on demand. Historical
jobs are backfilled from their recorded run evidence at server startup.

Measured OpenAI input/output usage comes from provider responses. Measured local
usage uses Ollama's own tokenizer and is shown separately. These counts cannot
be compared directly across tokenizers. Cached OpenAI input is recorded as a
subset of input, not added again.

For each local stage, the harness estimates the OpenAI tokens for the **same
recorded prompt**, including reused memory and image inputs. Text is counted with
`tiktoken` for a stable **gpt-4.1-2025-04-14 comparison baseline**, independently
of the selected paid reviewer. The visible local answer supplies
an output-length surrogate; no hypothetical OpenAI answer is generated.
The per-job baseline model is saved when the question starts. Changing the
reviewer does not recalculate earlier estimates or change the comparison model.
Older phone jobs retain their captured baseline. GPT-4.1 main/GPT-4o image estimates use documented
resolution/detail tile rules; unsupported image baselines remain unavailable.
Base64 image transport is not counted as text.

The counterfactual performs the same non-review stages entirely through OpenAI,
without the hybrid workflow's additional paid critique:

```text
estimated all-OpenAI baseline = estimated local-stage replacements + actual OpenAI non-review stages
estimated net saved tokens = baseline - all measured OpenAI tokens (including paid review)
```

A local-stage estimate of 1,000 tokens plus a paid review of 300 tokens means
700 estimated net tokens saved. If review needs 1,200 tokens instead, net savings
are **-200**, not zero. An all-OpenAI primary chat without an extra review has
zero savings under this comparison. Missing provider usage or local estimates
makes net savings unavailable; known measurements still appear as partial totals.

This is an explicit counterfactual estimate, **not a billing or quality guarantee**.
Chat-message framing is approximate. OpenAI might produce a different answer,
use reasoning, or apply caching differently. Token savings do not directly give
dollar savings, because input/output/cache prices differ. The tokenizer downloads
its public vocabulary on first use; if unavailable offline, measured usage stays
visible and estimates remain unavailable.
See [OpenAI image token rules](https://developers.openai.com/api/docs/guides/images-vision)
and [tiktoken counting examples](https://developers.openai.com/cookbook/examples/how_to_count_tokens_with_tiktoken).

Accounting is stored in each job's private `status.json` as `token_usage`, with
per-request IDs, provider counts, estimates, baseline model and rule version.
New successful turns include it in `phone.turn_linked`. Historical backfills and
failed turns with evidence create `phone.usage_recorded` activity events; they
leave completed model runs unchanged. The protected `/api/usage` and
`/api/threads/THREAD_ID/usage` endpoints expose the same reports as the browser.

If the phone's photo picker says **Unable to load** before the preview appears,
save the crop locally and select it using **Files/Browse**. Export it as PNG or
JPEG if needed. HEIC, TIFF and other formats depend on the browser's decoder;
selecting them does not guarantee support. The page now reports separate read,
decode and size errors instead of relying on the phone's reported file type.

The screenshot assistant sees only submitted images and recent chat. It has no
filesystem tools, so asking it to inspect the harness or existing case files
does not grant that access. It receives accurate upload limits and submitted
image dimensions to help explain problems. Images rejected before **Ask** never
reach the model. Restart the phone server after code updates and reload the page.

If model dropdowns are empty or do not respond after an update, check that the
server was restarted. A process started before model controls were added can
serve updated HTML while lacking the `/thread-controls.js` and `/api/models`
routes. Reloading that old process's page cannot update its Python code. The
server now keeps HTML and JavaScript together from startup, reports when browser
files change, and shows an explicit error if the control helper fails to load.
Restart, reload, and use the new pairing code; saved chats are retained.

## Model and prerequisites

Run `uv sync --locked` after updating the harness. Docker must have the pinned
sandbox image from `local-agent build-sandbox`, and Ollama must be running. The
phone never needs Docker, UV, Ollama, or an API key.

[config/phone.yaml](../config/phone.yaml) selects **qwen3.8:27b**, the installed
vision model. The phone assistant advertises no model tools. It uses the existing
durable runtime for model requests, evidence capture and audit, including short
Docker operations for initializing its isolated workspace and capturing its final
diff. Those containers are removed after each operation; inference runs through
Ollama on the host.

To use hosted OpenAI, copy the phone configuration to another file and change:

```yaml
provider: openai
base_url: https://api.openai.com/v1
api_key_env: OPENAI_API_KEY
model: YOUR_EXACT_VISION_MODEL_ID
completion_token_field: max_completion_tokens
```

Set `OPENAI_API_KEY` in the computer's launch terminal, then start with
`./phone --host 192.168.0.40 --agent config/phone-openai.yaml`. Keep
`instructions_version: phone-v1` and `tools: []`. The harness reads the key from
the named environment variable; `.env` files are not loaded automatically.
Screenshots and conversation are sent to the provider selected in this config.

## Jobs and traces

Default storage:

- Phone submissions and results: `~/.local/share/local-agent/phone/jobs/JOB_ID/`.
- Saved chats and images: `~/.local/share/local-agent/phone/threads/THREAD_ID/thread.json`.
- Authoritative run ledger: `~/.local/share/local-agent/control/agent.db`.
- Immutable evidence: `~/.local/share/local-agent/control/blobs/`.
- Isolated workspaces: `~/.local/share/local-agent/sandboxes/`.

Requests and job status files are private, atomically published JSON. One phone
question runs at a time; up to three more can wait. The existing run lease prevents
simultaneous agent controllers from executing against the same data root. A busy
controller produces a visible job error; retry after that run finishes. Phone job
storage stops accepting new jobs at 1,000 retained jobs.
Thread storage is bounded at 1,000 threads / 100 exchanges per thread. Earlier
successful phone jobs are imported into Saved chats once on upgrade, retaining
their question, answer, submitted history, image and run ID; older jobs without
thread IDs become separate imported chats because their original grouping is unknown.
The existing CLI `backup` preserves the run ledger and immutable evidence; also
back up the private `phone/` directory to preserve the saved-thread index,
full conversation history and job files.

Thread traces combine its model runs and separate browser activity runs.
`phone.turn_linked` records the stage, actual model/provider, reused memory count
and source run IDs. Feedback uses a separate activity run because a completed
model run is immutable. Activity runs are in the normal ledger, audited and
exported like other runs; they perform no model inference or electrical verification.

After a server restart, queued/running jobs are marked **interrupted** and are not
automatically dispatched again. Completed answers remain in the job store. Ctrl+C
stops admission, interrupts queued jobs, and waits for the active bounded question
to finish. Abruptly killing a controller can leave a run requiring the harness's
normal reconciliation; inspect its recorded status before continuing it.

For the run ID shown beside an answer:

```bash
uv run --locked local-agent trace RUN_ID
uv run --locked local-agent audit RUN_ID
uv run --locked local-agent replay RUN_ID --recorded-only
```

See [interpreting runs and traces](traces.md). The existing `./traces` viewer
continues to serve read-only traces on loopback.

## Authentication and ownership

This app **does not use OAuth 2.0**. It uses a fresh terminal pairing code,
an HttpOnly SameSite session cookie (24-hour expiry), and Host/Origin checks.
Re-pair after a server restart; saved chats remain. Paired devices share the
single persistent `local-owner` profile and can access that owner's chats. This
is not separate per-person accounts or OAuth login. The OpenAI API key is a
server-side credential for the paid reviewer, separate from browser authentication.

If the phone cannot load the page, check the printed URL, computer's current LAN
address, whether the terminal is still running, and whether your network/firewall
permits phone-to-computer TCP connections on port 8767. Guest Wi-Fi can isolate
devices. Errors after submitting a question appear in the page; Docker, provider
and run-lock failures are retained with the job result.

## Implementation provenance

The local harness wrote drafts using local Ollama models in offline Docker.
`glm-4.7-flash:q8_0` produced the screenshot runtime and browser page in two
successful, audited runs. Codex reviewed and corrected their validation, resume,
login, polling and follow-up behavior, wired CLI/configuration/evidence support,
and substantially rewrote the draft HTTP server and job worker for authentication,
bounded execution and durable persistence. The feature was not implemented
entirely by the local model without review. `Progress.md` records the development
runs, failed attempts, changes and acceptance checks.
For the saved-thread/model-control upgrade, the harness also drafted the thread
store and JavaScript control helper. Codex corrected their path validation,
idempotency, history assembly and field references, then integrated the routes,
per-job configs, activity traces, paid review and browser recovery. Acceptance
tests use a fake reviewer and do not incur OpenAI charges.
