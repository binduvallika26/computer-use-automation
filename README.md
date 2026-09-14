# Computer-use automation system

An LLM discovers a workflow in a live UI. A typed capability records the successful flow. A separate executor replays it with new inputs, without importing or calling a model.

The included target is **Harbor**, a synthetic member-servicing application inside an iframe: search → member detail → savings account → extract balance. All business state lives in the browser; there is no target business API. Python serves static files only.

## Setup

Requires Python 3.11+ and Chromium. Run commands from this repository root.

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[test]"
python -m playwright install chromium
```

For a dependency snapshot, install `requirements-lock.txt` before the editable package. The code uses no database or cloud service for replay.

Start the target in one terminal:

```bash
python -m hands.cli serve
```

Open <http://127.0.0.1:8765> to inspect the synthetic UI.

## Demo: discover, then replay

For the complete demo with automatic local server setup, copy `.env.example` to
`.env`, fill in your own `OPENAI_API_KEY`, then run:

```bash
python -m scripts.run_demo --evidence evidence/api-demo
```

This performs a real provider discovery, saves its capability, and verifies nine
replays with different inputs and runtime conditions. It exits nonzero on a
verification failure. A manifest records provider provenance and each result;
input values and balances are checked in memory and omitted from saved evidence.
Existing environment variables take precedence over `.env`. Only the two named
provider settings are loaded, and replay never reads `.env`.

The default model is `gpt-5.4-mini`, selected for this small structured UI workflow.
Override it with `OPENAI_MODEL` or `--model` when needed. A personal API key and
available API credit are still required; selecting a model does not create access.

To exercise the browser implementation without credentials:

```bash
python -m scripts.run_demo --offline
```

To include a real person restoring the same live browser, run
`python -m scripts.run_demo --offline --manual-handoff` from an interactive terminal.
At the expired-session prompt, restore the demo session in Chromium and type
`resume`. The default offline run labels its automated test operator as simulated.
You never submit API keys or tokens; the public deliverables are code and redacted evidence.

Configure `OPENAI_API_KEY` in your local environment and `OPENAI_MODEL` to a Responses API model available to your account that supports structured outputs. Do not put credentials in a command, artifact, or checked-in file. [OpenAI's structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs) describes the provider mechanism.

In a second terminal:

```bash
python -m hands.cli discover --goal "Look up member_id and read their current savings balance" --inputs '{"member_id":"10001"}' --evidence runs/discovery
```

The command prints the evidence directory. Use its saved capability:

```bash
python -m hands.cli replay --artifact runs/discovery/<run-id>/capability.json --inputs '{"member_id":"10002"}'
```

PowerShell 7 and POSIX shells accept these JSON arguments. Use synthetic inputs in shell history. A real service caller should invoke `replay()` with inputs in memory and manage the returned sensitive outputs separately.

## Run without model services

Replay the artifact recorded during the live external-model discovery included in this repository:

```bash
python -m hands.cli replay --artifact evidence/discovery/c40babdbd7a04143b68bc8df5580fa3d/capability.json --inputs '{"member_id":"10002"}'
python -m hands.cli replay --artifact evidence/discovery/c40babdbd7a04143b68bc8df5580fa3d/capability.json --inputs '{"member_id":"99999"}'
```

Expected results: `success` with balance `8040.00`, and `business_outcome` with code `not_found`. Decimal amounts are strings to avoid binary floating-point errors. No model key is read on replay.

`examples/read-savings-balance.json` is a separate **hand-authored fixture**, useful for tests. It is not presented as discovery evidence.

An external model host can participate in live discovery using `--planner stdio`. Each turn prints a fresh value-free UI observation and accepts one JSON `Decision` on stdin. This is an integration seam, not an offline fake LLM. If a human supplies the decisions, that run is human-driven and must be labeled accordingly.

## Exceptions and human handoff

```bash
python -m scripts.record_replays --artifact evidence/discovery/c40babdbd7a04143b68bc8df5580fa3d/capability.json
python -m scripts.record_replays --artifact evidence/discovery/c40babdbd7a04143b68bc8df5580fa3d/capability.json --manual-handoff
```

The first command runs real browsers with normal, not-found, slow-load, notice, permission-denial, and expired-session scenarios. It uses a **simulated operator only for the expired-session test**, clearly marked in the logs.

The second opens a visible browser and deliberately expires the demo session. When the terminal requests intervention, click **Restore demo session** in that same browser and then type `resume` in the terminal. The engine retains the pending step and session, records click/input event kinds without values, checks policy and exceptional states again, then resumes. Type `abort` to stop. Ownership prevents automation from acting during intervention. An uncertain click is never blindly repeated; failures after an action remain failures even if the operator inspects the session.

## Tests

```bash
python -m pytest -q
```

Tests launch real Chromium against an ephemeral local server. They cover parameterized outputs, business outcomes, known recovery, hard errors, ambiguity, false model completion, blocked actions/domains, redaction, ownership, and same-session resumption.

Regression tests also verify cleanup after browser startup failure, capture across
full navigation, browser event processing while terminal input waits, and the real
OpenAI SDK against an HTTP test double. HTTP test doubles do not establish live
provider access. If Chromium is missing, run `python -m playwright install chromium`.

## Repository map

| Path | Responsibility |
|---|---|
| `hands/models.py` | Versioned capability, steps, typed parameters and results |
| `hands/discovery.py` | Model planners and bounded discovery loop |
| `hands/engine.py` | Model-independent execution and error taxonomy |
| `hands/surface.py` | Browser perception, action and ownership boundary |
| `hands/policy.py`, `config/sandbox.json` | Operator-owned route/control/action policy |
| `hands/handoff.py` | Terminal intervention using the live browser |
| `hands/evidence.py` | Value-free structured evidence |
| `evidence/` | Recorded discovery, replay and failure evidence with provenance |
| `REPORT.md` | Design decisions, trade-offs and limits |

## Verification status

On 2026-09-13, **38 tests passed**, and all nine offline replay scenarios passed.
See [the verification record](evidence/verification-2026-09-13/README.md) for commands,
recorded results, and the distinction between SDK tests and live provider evidence.

The included discovery uses the external-model stdin interface. See [evidence provenance](evidence/README.md) for how discovery and handoff evidence were produced.

This is a focused sandbox implementation, not a production banking integration. Only synthetic records belong in its demo environment.
