"""Shared helpers: config loading and logging for the fake system."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text())


def log(line: str) -> None:
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    with open(logs / "app.log", "a") as f:
        f.write(line + "\n")
