"""Operator-owned policy; model and artifacts cannot widen it."""
from urllib.parse import urlsplit
from pydantic import Field
from .models import Model, Step, Target, Parameter


class PolicyError(Exception):
    pass


class Control(Model):
    target: Target
    actions: list[str]
    risk: str = "safe"


class Condition(Model):
    target: Target
    code: str
    kind: str  # business, recoverable, hard
    recovery: Step | None = None


class Policy(Model):
    origin: str
    paths: list[str]
    vendor: str
    app_version: str
    controls: list[Control]
    conditions: list[Condition] = Field(default_factory=list)
    success: Target
    inputs: dict[str, Parameter]
    outputs: dict[str, Parameter]
    max_steps: int = Field(default=20, ge=1, le=40)
    timeout_seconds: int = Field(default=120, ge=1, le=600)
    wait_ms: int = Field(default=3000, ge=100, le=30000)
    actions: list[str] = Field(default_factory=lambda: ["click", "fill", "read", "assert"])

    def check_url(self, url: str):
        u, base = urlsplit(url), urlsplit(self.origin)
        if (u.scheme, u.netloc) != (base.scheme, base.netloc) or u.path not in self.paths:
            raise PolicyError("route_not_allowed")
        if u.username or u.password or u.query or u.fragment or u.scheme not in ("http", "https"):
            raise PolicyError("route_not_allowed")

    def check_step(self, step: Step):
        if step.action not in self.actions:
            raise PolicyError("action_not_allowed")
        control = next((c for c in self.controls if c.target == step.target), None)
        if not control or step.action not in control.actions:
            raise PolicyError("control_not_allowed")
        if control.risk != "safe":
            raise PolicyError("risky_action_blocked")
        if step.input_ref and step.input_ref not in self.inputs:
            raise PolicyError("input_not_allowed")
        if step.output_ref and step.output_ref not in self.outputs:
            raise PolicyError("output_not_allowed")
