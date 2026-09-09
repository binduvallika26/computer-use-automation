"""Run the discovered artifact in fresh browsers, including injected exceptions."""
import json
from pathlib import Path
from hands.models import Capability
from hands.policy import Policy
from hands.surface import BrowserSurface
from hands.engine import replay
from hands.evidence import Evidence
from hands.handoff import TerminalOperator


class ScenarioSurface(BrowserSurface):
    def __init__(self, policy, mode, headed=False):
        super().__init__(policy, headed)
        self.mode = mode

    def open(self, path):
        super().open(path)
        frame = self.page.frame_locator('iframe[title="Core banking"]')
        frame.get_by_text("Sandbox fault controls", exact=True).click()
        frame.get_by_label("Scenario", exact=True).select_option(self.mode)


class SimulatedOperator:
    """Test-only operator: exercises real control transfer, not a real human."""
    def intervene(self, surface, evidence, step, code):
        evidence.event("intervention_requested", step=step, code=code, owner="human")
        before = surface.observe()
        evidence.snapshot(before)
        surface.start_human_capture()
        try:
            frame = surface.page.frame_locator('iframe[title="Core banking"]')
            frame.get_by_role("button", name="Restore demo session", exact=True).click()
            surface.page.wait_for_timeout(100)
        finally:
            surface.stop_human_capture()
        for event in surface.human_events:
            evidence.event("simulated_human_action", **event)
        evidence.event("control_returned", owner="automation", before=before, after=surface.observe())
        return True


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--manual-handoff", action="store_true")
    args = parser.parse_args()
    cap = Capability.model_validate_json(Path(args.artifact).read_text())
    policy = Policy.model_validate_json(Path("config/sandbox.json").read_text())
    cases = [("10002", "normal"), ("99999", "normal"), ("10001", "slow"),
             ("10001", "notice"), ("10001", "denied"), ("10001", "expired")]
    if args.manual_handoff:
        cases = [("10001", "expired")]
    for member, mode in cases:
        evidence = Evidence(Path("evidence/replay"))
        operator = TerminalOperator(True) if args.manual_handoff else SimulatedOperator() if mode == "expired" else TerminalOperator()
        with ScenarioSurface(policy, mode, args.manual_handoff) as surface:
            result = replay(cap, {"member_id": member}, surface, policy, evidence, operator)
        print(json.dumps({"scenario": mode, "run_id": result.run_id, "status": result.status, "code": result.code, "outputs": result.outputs}))


if __name__ == "__main__":
    main()
