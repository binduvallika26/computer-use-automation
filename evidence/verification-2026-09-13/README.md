# Verification on 2026-09-13

Local Windows verification with Python 3.11+, Playwright 1.62.0 and Chromium 1234.

- `python -m pytest -q --tb=short`: **38 passed in 47.38 seconds**.
- `python -m pip check`: no broken requirements.
- `python -m scripts.run_demo --offline --evidence evidence/verification-2026-09-13`:
  all nine replay cases verified against the existing external-stdio discovery artifact.
- The manifest is in `verification/98e767fafa6d41919264ecc24c5ead91/manifest.json`.
- All 25 generated JSON/JSONL files were checked for the synthetic member IDs,
  balance values and test sensitive strings; none were found.

Browser tests cover successful extraction, business outcomes, runtime recovery,
hard failures, network restrictions, startup cleanup, ownership, action capture
across navigation, and browser event pumping while terminal input waits.
Provider tests use the real OpenAI SDK with an HTTP test double, including a full
discovery-to-artifact-to-replay integration test with a different member input.
They are not live provider calls and are not submitted as genuine LLM discovery evidence.

The expired-session replay uses a simulated operator, explicitly labeled in events
and the manifest. The terminal path supports a real human via `--manual-handoff`.
No genuine human interaction was performed during this verification.

## Remaining external prerequisite

The owner has no model API key configured. Consequently this verification does not
fulfill the assignment's own-model-API discovery expectation. The existing discovery
provenance remains documented in `../README.md`. Once credentials are available,
`python -m scripts.run_demo --evidence evidence/api-demo` records the real API run
and replays its newly generated artifact. Credentials stay in an ignored `.env` file
or process environment and are never part of the submission.
