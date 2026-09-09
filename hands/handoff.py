"""Explicit ownership transfer of a live browser, using a local terminal operator."""
import time


class TerminalOperator:
    def __init__(self, enabled=False):
        self.enabled = enabled

    def intervene(self, surface, evidence, step, code):
        evidence.event("intervention_requested", step=step, code=code, owner="human")
        evidence.snapshot(surface.observe())
        if not self.enabled or not surface.headed:
            evidence.event("intervention_unavailable", code="requires_headed_operator")
            return False
        before = surface.observe()
        surface.start_human_capture()
        try:
            print(f"Paused at step {step}: {code}. Use the SAME Chromium window.\n"
                  "Resolve the obstruction only; do not perform the pending action.\n"
                  "Return here and type resume, or abort.")
            decision = input("operator> ").strip()
            # Pump Playwright so the binding callbacks are delivered before reading them.
            surface.page.wait_for_timeout(100)
        finally:
            surface.stop_human_capture()
        for event in surface.human_events:
            evidence.event("human_action", action=event["action"], control=event["control"])
        after = surface.observe()
        evidence.event("control_returned", owner="automation", before=before, after=after)
        return decision == "resume"
