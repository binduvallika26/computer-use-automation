"""Read only provider settings from an explicitly selected local env file."""
import os
from pathlib import Path

DEFAULT_MODEL = "gpt-5.4-mini"


def load_provider_env(path=".env"):
    source = Path(path)
    if not source.is_file():
        return
    for line in source.read_text(encoding="utf-8-sig").splitlines():
        name, separator, value = line.strip().partition("=")
        if separator and name.strip() in {"OPENAI_API_KEY", "OPENAI_MODEL"}:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value:
                os.environ.setdefault(name.strip(), value)
