import argparse
import json
import os
from pathlib import Path
from .models import Capability
from .policy import Policy
from .surface import BrowserSurface
from .evidence import Evidence
from .handoff import TerminalOperator
from .engine import replay
from .demo import serve


def main():
    parser = argparse.ArgumentParser(description="Discover once, replay without a model.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="Serve the synthetic UI on 127.0.0.1:8765")
    for verb in ("discover", "replay"):
        p = sub.add_parser(verb)
        p.add_argument("--policy", default="config/sandbox.json")
        p.add_argument("--inputs", required=True, help="JSON object; use synthetic data only in shell history")
        p.add_argument("--evidence", default="runs")
        p.add_argument("--headed", action="store_true")
        p.add_argument("--operator", action="store_true")
        if verb == "discover":
            p.add_argument("--goal", required=True)
            p.add_argument("--name", default="read-savings-balance")
            p.add_argument("--model", default=os.getenv("OPENAI_MODEL"))
            p.add_argument("--planner", choices=["openai", "stdio"], default="openai")
        else:
            p.add_argument("--artifact", required=True)
    args = parser.parse_args()
    if args.command == "serve":
        import threading
        with serve():
            print("Synthetic sandbox: http://127.0.0.1:8765", flush=True)
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                pass
        return
    if args.command == "discover" and args.planner == "openai" and (not args.model or not os.getenv("OPENAI_API_KEY")):
        parser.error("Set OPENAI_API_KEY and pass --model (or set OPENAI_MODEL). Never commit the key.")
    policy = Policy.model_validate_json(Path(args.policy).read_text(encoding="utf-8"))
    evidence = Evidence(Path(args.evidence))
    operator = TerminalOperator(args.operator)
    with BrowserSurface(policy, args.headed) as surface:
        inputs = json.loads(args.inputs)
        if args.command == "discover":
            from .discovery import OpenAIPlanner, StdioPlanner, discover
            planner = OpenAIPlanner(args.model) if args.planner == "openai" else StdioPlanner()
            _, result = discover(args.goal, args.name, inputs, planner, surface, policy, evidence, operator)
        else:
            artifact = Capability.model_validate_json(Path(args.artifact).read_text(encoding="utf-8"))
            result = replay(artifact, inputs, surface, policy, evidence, operator)
    print(result.model_dump_json(indent=2))
    print(f"Evidence: {evidence.path}")
    raise SystemExit(1 if result.status == "failure" else 0)


if __name__ == "__main__":
    main()
