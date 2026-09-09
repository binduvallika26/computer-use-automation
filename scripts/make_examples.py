"""Generate reviewed sandbox policy and a clearly hand-authored replay fixture."""
import json
from pathlib import Path
from hands.models import Target, Step, Parameter, Capability
from hands.policy import Policy, Control, Condition


def target(name, strategy="role", role="button"):
    return Target(strategy=strategy, name=name, role=role if strategy == "role" else None, frame="Core banking")


def generate():
    member = target("Member ID", "label")
    search, view, savings = map(target, ["Search members", "View member", "Savings account"])
    balance = target("Available balance", "label")
    success = target("Balance verified", "text")
    dismiss = target("Dismiss notice")
    controls = [Control(target=member, actions=["fill"])]
    controls += [Control(target=t, actions=["click"]) for t in [search, view, savings, dismiss]]
    controls += [Control(target=balance, actions=["read"]), Control(target=success, actions=["assert"]),
                 Control(target=target("Close account"), actions=["click"], risk="irreversible"),
                 Control(target=target("Restore demo session"), actions=[], risk="human_only")]
    conditions = [Condition(target=target(label, "text"), code=code, kind=kind) for label, code, kind in [
        ("Invalid member ID", "validation_error", "business"), ("Member not found", "not_found", "business"),
        ("Session expired", "session_expired", "hard"), ("Permission denied", "permission_denied", "hard"),
        ("Application unavailable", "app_unavailable", "hard"), ("Loading", "slow_load", "recoverable")]]
    conditions.append(Condition(target=target("Maintenance notice", "text"), code="known_notice", kind="recoverable",
                                recovery=Step(action="click", target=dismiss)))
    policy = Policy(origin="http://127.0.0.1:8765", paths=["/", "/core.html", "/favicon.ico"],
                    vendor="harbor-sandbox", app_version="1", controls=controls, conditions=conditions,
                    success=success, inputs={"member_id": Parameter(type="string", pattern=r"\d{5}")},
                    outputs={"balance": Parameter(type="decimal")})
    steps = [Step(action="fill", target=member, input_ref="member_id"),
             *[Step(action="click", target=t) for t in [search, view, savings]],
             Step(action="read", target=balance, output_ref="balance")]
    cap = Capability(name="read-savings-balance", vendor=policy.vendor, app_version=policy.app_version,
                     inputs=policy.inputs, outputs=policy.outputs, steps=steps, success=success)
    for name, obj in [("config/sandbox.json", policy), ("examples/read-savings-balance.json", cap)]:
        path = Path(name)
        path.parent.mkdir(exist_ok=True)
        path.write_text(obj.model_dump_json(indent=2), encoding="utf-8")
    Path("examples/capability.schema.json").write_text(json.dumps(Capability.model_json_schema(), indent=2), encoding="utf-8")


if __name__ == "__main__":
    generate()
