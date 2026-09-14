"""Self-contained discovery/replay evidence, with honest provider provenance."""
import argparse
import json
import os
from pathlib import Path

from hands.demo import serve
from hands.engine import replay
from hands.evidence import Evidence
from hands.handoff import TerminalOperator
from hands.models import Capability
from hands.policy import Policy
from hands.settings import DEFAULT_MODEL, load_provider_env
from hands.surface import BrowserSurface
from scripts.record_replays import ScenarioSurface, SimulatedOperator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Replay existing discovery; makes no model call")
    parser.add_argument("--manual-handoff", action="store_true", help="A person restores the live session")
    parser.add_argument("--artifact", default="evidence/discovery/c40babdbd7a04143b68bc8df5580fa3d/capability.json")
    parser.add_argument("--evidence", default="runs/demo")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--model")
    args = parser.parse_args()
    if not args.offline:
        load_provider_env(args.env_file)
        args.model = args.model or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL
        if not os.getenv("OPENAI_API_KEY") or not args.model:
            parser.error("Configure OPENAI_API_KEY and OPENAI_MODEL in .env; never paste credentials into logs.")
    root = Path(args.evidence)
    summary = Evidence(root / "verification")
    manifest = {"discovery": "existing_external_stdio" if args.offline else "openai",
                "api_discovery_verified": False, "replays": []}
    with serve(0) as port:
        policy = Policy.model_validate_json(Path("config/sandbox.json").read_text())
        policy.origin = f"http://127.0.0.1:{port}"
        if args.offline:
            artifact = Capability.model_validate_json(Path(args.artifact).read_text())
            manifest["artifact"] = Path(args.artifact).as_posix()
        else:
            from hands.discovery import OpenAIPlanner, discover
            evidence = Evidence(root / "discovery")
            planner = OpenAIPlanner(args.model)
            try:
                with BrowserSurface(policy) as surface:
                    artifact, result = discover("Look up member_id and read their current savings balance",
                        "read-savings-balance", {"member_id": "10001"}, planner,
                        surface, policy, evidence, TerminalOperator())
            finally:
                planner.client.close()
            manifest["discovery_run"] = evidence.run_id
            manifest["api_discovery_verified"] = artifact is not None and result.status == "success"
            if artifact is None:
                manifest["discovery_error"] = result.code
                (summary.path / "manifest.json").write_text(json.dumps(manifest, indent=2))
                print(json.dumps(manifest, indent=2))
                raise SystemExit(1)
            manifest["artifact"] = (evidence.path / "capability.json").as_posix()
        cases = [("10002", "normal", "success", "completed", "8040.00"),
                 ("99999", "normal", "business_outcome", "not_found", None),
                 ("bad", "normal", "business_outcome", "invalid_input", None),
                 ("10001", "slow", "success", "completed", "1250.50"),
                 ("10001", "notice", "success", "completed", "1250.50"),
                 ("10001", "denied", "failure", "permission_denied", None),
                 ("10001", "error", "failure", "app_unavailable", None),
                 ("10001", "dialog", "failure", "unexpected_dialog", None),
                 ("10001", "expired", "success", "completed", "1250.50")]
        for member, mode, status, code, balance in cases:
            manual = args.manual_handoff and mode == "expired"
            operator = TerminalOperator(True) if manual else SimulatedOperator() if mode == "expired" else TerminalOperator()
            evidence = Evidence(root / "replay")
            with ScenarioSurface(policy, mode, headed=manual) as surface:
                result = replay(artifact, {"member_id": member}, surface, policy, evidence, operator)
            passed = (result.status, result.code) == (status, code)
            passed = passed and result.outputs == ({"balance": balance} if balance else {})
            row = {"scenario": mode, "run_id": evidence.run_id, "status": result.status,
                   "code": result.code, "verified": passed,
                   "operator": "human" if manual else "simulated" if mode == "expired" else "none"}
            manifest["replays"].append(row)
            print(json.dumps(row), flush=True)
    manifest["replays_verified"] = all(row["verified"] for row in manifest["replays"])
    (summary.path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Verification: {summary.path / 'manifest.json'}")
    raise SystemExit(0 if manifest["replays_verified"] else 1)


if __name__ == "__main__":
    main()
