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

The checked-in discovery was driven live by the Codex assistant through the external-model stdin interface, one decision per fresh browser observation. It was **not** an OpenAI API call from this application. No API credential was available during development, so the OpenAI planner remains unverified end-to-end. The assignment's own-provider-API evidence requirement still needs that run; the command above produces it without code changes. See `evidence/README.md` for exact provenance. No genuine human operator session is claimed by the simulated handoff evidence.

This is a focused sandbox implementation, not a production banking integration. Only synthetic records belong in its demo environment.
