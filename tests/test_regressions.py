"""Failure boundaries and live-session regressions; no paid provider calls."""
import json
from pathlib import Path
from unittest.mock import patch

try:
    import httpx2 as httpx
except ImportError:
    import httpx
import pytest
from openai import OpenAI

from hands.discovery import OpenAIPlanner
from hands.evidence import Evidence
from hands.handoff import TerminalOperator
from hands.models import Parameter, Step, validate_inputs
from hands.policy import Policy
from hands.surface import BrowserSurface, SurfaceError
from hands.demo import serve


@pytest.fixture
def policy():
    with serve(0) as port:
        policy = Policy.model_validate_json(Path("config/sandbox.json").read_text())
        policy.origin = f"http://127.0.0.1:{port}"
        yield policy


def test_failed_start_does_not_poison_next_browser(policy):
    class Broken(BrowserSurface):
        def _start_browser(self):
            raise RuntimeError("startup failed")
    with pytest.raises(RuntimeError):
        with Broken(policy):
            pass
    with BrowserSurface(policy) as surface:
        surface.open("/")
        assert surface.visible(policy.controls[0].target)


def test_capture_survives_navigation_and_repeated_handoff(policy):
    with BrowserSurface(policy) as surface:
        surface.open("/")
        for _ in range(2):
            surface.start_human_capture()
            with pytest.raises(SurfaceError, match="human_owns_session"):
                surface.open("/")
            surface.page.reload()
            surface.locator(policy.controls[0].target).fill("private-input")
            surface.stop_human_capture()
            assert any(e["action"] == "input" for e in surface.human_events)
            assert "private-input" not in json.dumps(surface.human_events)
            assert surface.owner == "automation"


def test_terminal_handoff_handles_dialog_and_records_abort(policy, tmp_path):
    with BrowserSurface(policy) as surface:
        surface.open("/")
        surface.headed = True  # Test double for visibility only; browser and transfer are real.
        surface.dialog = True
        evidence = Evidence(tmp_path)
        with patch("hands.handoff.read_decision", return_value="abort"):
            assert not TerminalOperator(True).intervene(surface, evidence, 1, "unexpected_dialog")
        assert surface.owner == "automation"
    events = (evidence.path / "events.jsonl").read_text()
    assert "control_transferred" in events and "control_returned" in events
    assert '"code": "abort"' in events


def test_terminal_wait_pumps_browser_events(policy, monkeypatch):
    from hands.handoff import read_decision
    from threading import Event
    pumped = Event()
    def answer(_):
        assert pumped.wait(5), "browser was blocked by terminal input"
        return "resume"
    monkeypatch.setattr("builtins.input", answer)
    with BrowserSurface(policy) as surface:
        surface.open("/")
        surface.context.expose_binding("testPumped", lambda source: pumped.set())
        surface.page.evaluate("setTimeout(() => window.testPumped(), 100)")
        assert read_decision(surface) == "resume"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "bad", 1.2, None])
def test_decimal_input_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        validate_inputs({"amount": Parameter(type="decimal")}, {"amount": value})


@pytest.mark.parametrize("status,code", [(401,"model_authentication_failed"), (429,"model_rate_limited"), (500,"model_api_error")])
def test_provider_error_is_redacted(policy, tmp_path, status, code):
    def handler(request):
        return httpx.Response(status, json={"error": {"message": "private-provider-detail"}})
    with OpenAI(api_key="test-only", max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        planner = OpenAIPlanner("test-model", client)
        with pytest.raises(SurfaceError, match=code) as error:
            planner.decide("read balance", {}, [], policy, Evidence(tmp_path))
        assert "private-provider-detail" not in str(error.value)


def test_real_sdk_parses_structured_response(policy, tmp_path):
    decision = {"kind": "step", "step": Step(action="fill", target=policy.controls[0].target,
                input_ref="member_id").model_dump(), "reason": "supply_input"}
    def handler(request):
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["text"]["format"]["strict"] is True
        return httpx.Response(200, json={"id": "resp_test_only", "object": "response",
            "created_at": 0, "model": "test-model", "status": "completed",
            "output": [{"id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps(decision), "annotations": []}]}]})
    with OpenAI(api_key="test-only", http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        answer = OpenAIPlanner("test-model", client).decide("read balance", {}, [], policy, Evidence(tmp_path))
        assert answer.step.input_ref == "member_id"


def test_provider_env_does_not_override_or_load_unrelated_settings(tmp_path, monkeypatch):
    from hands.settings import load_provider_env
    monkeypatch.setenv("OPENAI_API_KEY", "existing")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("UNRELATED_TEST_SETTING", raising=False)
    source = tmp_path / ".env"
    source.write_text('OPENAI_API_KEY=ignored\nOPENAI_MODEL="test-model"\nUNRELATED_TEST_SETTING=no\n')
    load_provider_env(source)
    import os
    assert os.environ["OPENAI_API_KEY"] == "existing"
    assert os.environ["OPENAI_MODEL"] == "test-model"
    assert "UNRELATED_TEST_SETTING" not in os.environ


def test_discovery_artifact_replays_with_new_input(policy, tmp_path):
    """Scripted HTTP test double, never claimed as live LLM evidence."""
    from hands.discovery import discover
    from hands.engine import replay
    from hands.models import Capability
    fixture = Capability.model_validate_json(Path("examples/read-savings-balance.json").read_text())
    decisions = iter([{"kind": "step", "step": step.model_dump(), "reason": "navigate"}
                      for step in fixture.steps] + [{"kind": "done", "step": None, "reason": "verify"}])
    def handler(request):
        assert "10001" not in request.content.decode()
        decision = next(decisions)
        return httpx.Response(200, json={"id": "resp_test_only", "object": "response",
            "created_at": 0, "model": "test-model", "status": "completed",
            "output": [{"id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps(decision), "annotations": []}]}]})
    evidence = Evidence(tmp_path / "discovery")
    with OpenAI(api_key="test-only", http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        with BrowserSurface(policy) as surface:
            artifact, result = discover("Read balance for 10001", "balance", {"member_id": "10001"},
                OpenAIPlanner("test-model", client), surface, policy, evidence, TerminalOperator())
    assert result.status == "success"
    saved = Capability.model_validate_json((evidence.path / "capability.json").read_text())
    assert saved == artifact
    with BrowserSurface(policy) as surface:
        result = replay(saved, {"member_id": "10002"}, surface, policy, Evidence(tmp_path / "replay"), TerminalOperator())
    assert result.outputs == {"balance": "8040.00"}


def test_network_allowlist_blocks_browser_request(policy):
    from hands.policy import PolicyError
    with BrowserSurface(policy) as surface:
        surface.open("/")
        # Fault injection: the request must be aborted before reaching the network.
        surface.page.evaluate("fetch('https://example.com/private').catch(() => null)")
        with pytest.raises(PolicyError, match="blocked_network"):
            surface.check()
