"""Serializable contracts. Artifacts contain references, never invocation values."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(Model):
    strategy: Literal["role", "label", "text"]
    name: str = Field(min_length=1, max_length=120)
    role: str | None = None
    frame: str | None = None

    @model_validator(mode="after")
    def role_required(self):
        if self.strategy == "role" and not self.role:
            raise ValueError("role targeting requires a role")
        return self


class Step(Model):
    action: Literal["click", "fill", "read", "assert"]
    target: Target
    input_ref: str | None = None
    output_ref: str | None = None

    @model_validator(mode="after")
    def refs(self):
        if (self.action == "fill") != (self.input_ref is not None):
            raise ValueError("only fill must carry input_ref")
        if (self.action == "read") != (self.output_ref is not None):
            raise ValueError("only read must carry output_ref")
        return self


class Parameter(Model):
    type: Literal["string", "integer", "decimal"]
    sensitive: bool = True
    pattern: str | None = None


class Capability(Model):
    schema_version: Literal["1.0"] = "1.0"
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    version: str = "1.0.0"
    vendor: str
    app_version: str
    entry_path: str = "/"
    inputs: dict[str, Parameter]
    outputs: dict[str, Parameter]
    steps: list[Step] = Field(min_length=1, max_length=40)
    success: Target

    @model_validator(mode="after")
    def contract(self):
        used_outputs = []
        for s in self.steps:
            if s.input_ref and s.input_ref not in self.inputs:
                raise ValueError("undeclared input")
            if s.output_ref:
                if s.output_ref not in self.outputs:
                    raise ValueError("undeclared output")
                used_outputs.append(s.output_ref)
        if set(used_outputs) != set(self.outputs) or len(used_outputs) != len(set(used_outputs)):
            raise ValueError("each output must be extracted exactly once")
        return self


class Decision(Model):
    kind: Literal["step", "done", "stuck"]
    step: Step | None
    reason: Literal["navigate", "supply_input", "extract_output", "verify", "blocked"]


class Result(Model):
    status: Literal["success", "business_outcome", "failure"]
    code: str
    outputs: dict[str, str | int] = Field(default_factory=dict)
    step: int | None = None
    expected: str | None = None
    observed: str | None = None
    run_id: str


def validate_inputs(spec: dict[str, Parameter], values: dict):
    if not isinstance(values, dict) or set(values) != set(spec):
        raise ValueError("input names do not match contract")
    for name, p in spec.items():
        value = values[name]
        if p.type == "integer":
            if type(value) is not int:
                raise ValueError("expected integer")
        elif not isinstance(value, str) or len(value) > 256:
            raise ValueError("expected bounded string")
        if p.type == "decimal":
            try:
                if not Decimal(value).is_finite():
                    raise ValueError("expected finite decimal")
            except InvalidOperation:
                raise ValueError("expected decimal") from None
        if p.pattern and not re.fullmatch(p.pattern, str(value)):
            raise ValueError("input pattern mismatch")
