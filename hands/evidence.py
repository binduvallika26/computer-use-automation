"""Allowlisted event fields: never log page text, values, model prose or exceptions."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


class Evidence:
    def __init__(self, root: Path):
        self.run_id = uuid.uuid4().hex
        self.path = root / self.run_id
        self.path.mkdir(parents=True)

    def event(self, event: str, **fields):
        allowed = {"step", "action", "reason", "code", "status", "owner", "model",
                   "response_id", "provider", "control", "before", "after", "attempt"}
        assert set(fields) <= allowed
        row = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        with (self.path / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def snapshot(self, structure):
        (self.path / "failure-state.json").write_text(json.dumps(structure, indent=2), encoding="utf-8")

    def result(self, result):
        # Outputs are returned to caller in memory; never saved to disk.
        safe = result.model_dump(exclude={"outputs"})
        (self.path / "result.json").write_text(json.dumps(safe, indent=2), encoding="utf-8")
