"""Shared deterministic executor. This module does not import a model provider."""
import time
from .models import Capability, Result, Step, validate_inputs
from .policy import PolicyError
from .surface import SurfaceError


class Outcome(Exception):
    def __init__(self, code, business=False):
        self.code, self.business = code, business


class Executor:
    def __init__(self, surface, policy, evidence, operator):
        self.surface, self.policy, self.evidence, self.operator = surface, policy, evidence, operator
        self.deadline = time.monotonic() + policy.timeout_seconds
        self.interventions = set()

    def guard(self):
        if time.monotonic() > self.deadline:
            raise SurfaceError("run_timeout")
        self.surface.check()
        for condition in self.policy.conditions:
            if not self.surface.visible(condition.target):
                continue
            if condition.kind == "business":
                raise Outcome(condition.code, True)
            if condition.kind == "recoverable":
                self.evidence.event("recovery", code=condition.code)
                if condition.recovery:
                    self.surface.act(condition.recovery, {})
                else:
                    # Wait for a transient loading indicator to disappear, never re-click.
                    self.surface.wait_hidden(condition.target)
                if self.surface.visible(condition.target):
                    raise SurfaceError("recovery_exhausted")
            else:
                raise SurfaceError(condition.code)

    def execute(self, step, inputs, index):
        self.guard()
        self.policy.check_step(step)
        self.evidence.event("action", step=index, action=step.action,
                            control=self.policy.controls.index(next(c for c in self.policy.controls if c.target == step.target)))
        try:
            value = self.surface.act(step, inputs)
        except SurfaceError:
            # Reclassify a late business condition before calling it a technical failure.
            self.guard()
            raise
        return value

    def failure(self, exc, index):
        code = exc.code if isinstance(exc, Outcome) else str(exc) if isinstance(exc, (SurfaceError, PolicyError)) else "internal_error"
        business = isinstance(exc, Outcome) and exc.business
        self.evidence.event("stopped", step=index, code=code)
        try:
            self.evidence.snapshot(self.surface.observe())
        except Exception:
            self.evidence.snapshot({"state": "unavailable", "code": code})
        return Result(status="business_outcome" if business else "failure", code=code,
                      step=index, expected="unique permitted control and valid checkpoint",
                      observed=code, run_id=self.evidence.run_id)

    def handoff(self, index, exc):
        if isinstance(exc, (PolicyError, Outcome)) or index in self.interventions:
            return False
        self.interventions.add(index)
        try:
            resumed = self.operator.intervene(self.surface, self.evidence, index, str(exc) if isinstance(exc, SurfaceError) else "internal_error")
            if resumed:
                self.deadline = time.monotonic() + self.policy.timeout_seconds
                self.guard()
            return resumed
        except Exception:
            return False


def replay(capability: Capability, inputs, surface, policy, evidence, operator):
    engine = Executor(surface, policy, evidence, operator)
    evidence.event("run_started", provider="none")
    index = 0
    try:
        validate_inputs(capability.inputs, inputs)
        if (capability.vendor, capability.app_version, capability.inputs, capability.outputs, capability.success) != (
                policy.vendor, policy.app_version, policy.inputs, policy.outputs, policy.success):
            raise PolicyError("incompatible_contract")
        for step in capability.steps:
            policy.check_step(step)
        surface.open(capability.entry_path)
        outputs = {}
        for index, step in enumerate(capability.steps):
            # A guard failure happens BEFORE an action and is safe to resume once.
            try:
                engine.guard()
            except SurfaceError as exc:
                if not engine.handoff(index, exc):
                    raise
            value = engine.execute(step, inputs, index)
            if step.output_ref:
                outputs[step.output_ref] = value
        engine.guard()
        if not surface.visible(capability.success) or set(outputs) != set(capability.outputs):
            raise SurfaceError("checkpoint_failed")
        result = Result(status="success", code="completed", outputs=outputs, run_id=evidence.run_id)
    except Exception as exc:
        if isinstance(exc, ValueError):
            exc = Outcome("invalid_input", True)
        result = engine.failure(exc, index)
        if result.status == "failure":
            # Never blindly retry a click whose outcome may be uncertain.
            engine.handoff(index, exc)
    evidence.event("run_finished", status=result.status, code=result.code)
    evidence.result(result)
    return result
