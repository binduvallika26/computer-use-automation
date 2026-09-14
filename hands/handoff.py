"""Explicit ownership transfer of a live browser, using a local terminal operator."""
from queue import Queue, Empty
from threading import Thread


def read_decision(surface):
    """Keep the Playwright thread pumping while the terminal waits for a person."""
    answers = Queue()
    def read():
        try:
            answers.put(input("operator> ").strip())
        except (EOFError, OSError):
            answers.put("abort")
    Thread(target=read, daemon=True).start()
    while True:
        try:
            return answers.get_nowait()
        except Empty:
            surface.page.wait_for_timeout(50)


def snapshot(surface):
    try:
        return surface.observe()
    except Exception:
        return {"state": "unavailable"}


class TerminalOperator:
    def __init__(self, enabled=False):
        self.enabled = enabled

    def intervene(self, surface, evidence, step, code):
        evidence.event("intervention_requested", step=step, code=code, owner=surface.owner)
        before = snapshot(surface)
        evidence.snapshot(before)
        if not self.enabled or not surface.headed:
            evidence.event("intervention_unavailable", code="requires_headed_operator")
            return False
        surface.start_human_capture()
        evidence.event("control_transferred", owner="human", step=step, code=code)
        decision = "abort"
        try:
            print(f"Paused at step {step}: {code}. Use the SAME Chromium window.\n"
                  "Resolve the obstruction only; do not perform the pending action.\n"
                  "Return here and type resume, or abort.")
            decision = read_decision(surface)
        finally:
            surface.stop_human_capture()
            for event in surface.human_events:
                evidence.event("human_action", action=event["action"], control=event["control"])
            evidence.event("control_returned", owner="automation", before=before, after=snapshot(surface))
            evidence.event("operator_decision", code="resume" if decision == "resume" else "abort")
        return decision == "resume"
