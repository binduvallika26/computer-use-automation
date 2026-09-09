import json
import pytest
from pathlib import Path
from hands.models import Capability, Step
from hands.policy import Policy, PolicyError
from hands.surface import BrowserSurface, SurfaceError
from hands.engine import replay
from hands.evidence import Evidence
from hands.handoff import TerminalOperator
from hands.demo import serve


@pytest.fixture(scope="session")
def server():
    with serve(0) as port:
        yield port


@pytest.fixture
def policy(server):
    p = Policy.model_validate_json(Path("config/sandbox.json").read_text())
    p.origin = f"http://127.0.0.1:{server}"
    return p


@pytest.fixture
def cap():
    return Capability.model_validate_json(Path("examples/read-savings-balance.json").read_text())


class FaultSurface(BrowserSurface):
    def __init__(self, policy, mode="normal"):
        super().__init__(policy)
        self.mode = mode

    def open(self, path):
        super().open(path)
        frame = self.page.frame_locator('iframe[title="Core banking"]')
        frame.get_by_text("Sandbox fault controls", exact=True).click()
        frame.get_by_label("Scenario", exact=True).select_option(self.mode)


@pytest.mark.parametrize("member,mode,status,code,balance", [
    ("10001", "normal", "success", "completed", "1250.50"),
    ("10002", "normal", "success", "completed", "8040.00"),
    ("99999", "normal", "business_outcome", "not_found", None),
    ("bad", "normal", "business_outcome", "invalid_input", None),
    ("10001", "slow", "success", "completed", "1250.50"),
    ("10001", "notice", "success", "completed", "1250.50"),
    ("10001", "denied", "failure", "permission_denied", None),
    ("10001", "expired", "failure", "session_expired", None),
    ("10001", "error", "failure", "app_unavailable", None),
    ("10001", "dialog", "failure", "unexpected_dialog", None),
])
def test_real_browser(policy, cap, tmp_path, member, mode, status, code, balance):
    evidence = Evidence(tmp_path)
    with FaultSurface(policy, mode) as surface:
        result = replay(cap, {"member_id": member}, surface, policy, evidence, TerminalOperator())
    assert (result.status, result.code) == (status, code)
    if balance:
        assert result.outputs == {"balance": balance}
    else:
        assert result.outputs == {}
    disk = "".join(p.read_text() for p in evidence.path.iterdir())
    assert member not in disk
    assert "$1,250.50" not in disk


@pytest.mark.parametrize("url", ["http://127.0.0.1.evil.test/", "https://example.com/", "http://127.0.0.1:8765/core.html?secret=x", "file:///etc/passwd"])
def test_url_policy(policy, url):
    with pytest.raises(PolicyError):
        policy.check_url(url)


def test_risky_control_blocked(policy):
    control = next(c for c in policy.controls if c.risk == "irreversible")
    with pytest.raises(PolicyError, match="risky"):
        policy.check_step(Step(action="click", target=control.target))


def test_replay_import_has_no_model_dependency():
    import ast
    tree = ast.parse(Path("hands/engine.py").read_text())
    assert not any(isinstance(n, ast.ImportFrom) and n.module in ("openai", "discovery") for n in ast.walk(tree))


def test_schema_rejects_literal_input(cap):
    data = cap.model_dump()
    data["steps"][0]["value"] = "secret"
    with pytest.raises(ValueError):
        Capability.model_validate(data)


def test_checkpoint_failure(policy, cap, tmp_path):
    cap.steps = cap.steps[:1]
    # Deliberately bypass model validation to exercise independent runtime checkpoint.
    with BrowserSurface(policy) as surface:
        result = replay(cap, {"member_id": "10001"}, surface, policy, Evidence(tmp_path), TerminalOperator())
    assert result.code == "checkpoint_failed"


def test_ownership_and_capture(policy):
    with BrowserSurface(policy) as surface:
        surface.open("/")
        surface.start_human_capture()
        with pytest.raises(SurfaceError, match="human_owns"):
            surface.act(Step(action="click", target=policy.controls[1].target), {})
        surface.locator(policy.controls[0].target).fill("secret-value")
        surface.page.wait_for_timeout(100)
        surface.stop_human_capture()
        assert surface.human_events
        assert "secret-value" not in json.dumps(surface.human_events)
        assert surface.owner == "automation"


def test_discovery_refuses_false_success(policy, tmp_path):
    from hands.discovery import discover
    from hands.models import Decision
    class FalsePlanner:
        provider = "test-double"
        def decide(self, *args):
            return Decision(kind="done", step=None, reason="verify")
    evidence = Evidence(tmp_path)
    with BrowserSurface(policy) as surface:
        artifact, result = discover("Read balance", "test", {"member_id":"10001"}, FalsePlanner(), surface, policy, evidence, TerminalOperator())
    assert artifact is None
    assert result.code == "premature_completion"
    assert not (evidence.path / "capability.json").exists()


def test_session_resumes_after_control_transfer(policy, cap, tmp_path):
    from scripts.record_replays import SimulatedOperator
    evidence = Evidence(tmp_path)
    with FaultSurface(policy, "expired") as surface:
        identity = id(surface.page)
        result = replay(cap, {"member_id":"10001"}, surface, policy, evidence, SimulatedOperator())
        assert id(surface.page) == identity
        assert surface.owner == "automation"
    assert result.status == "success"
    logs = (evidence.path / "events.jsonl").read_text()
    assert "control_returned" in logs and "simulated_human_action" in logs


def test_duplicate_visible_control_stops(policy, cap, tmp_path):
    class DuplicateSurface(BrowserSurface):
        def open(self, path):
            super().open(path)
            # Test-only fault injection, never a task action.
            self.page.frames[1].evaluate("document.body.appendChild(document.querySelector('button').cloneNode(true))")
    with DuplicateSurface(policy) as surface:
        result = replay(cap, {"member_id":"10001"}, surface, policy, Evidence(tmp_path), TerminalOperator())
    assert result.status == "failure"
