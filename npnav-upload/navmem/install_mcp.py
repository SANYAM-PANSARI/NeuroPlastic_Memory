"""Register the navmem MCP server ONCE in Antigravity, in benchmark mode.

Usage: python -m navmem.install_mcp            # adds "navmem" to ~/.gemini/config/mcp_config.json
       python -m navmem.install_mcp --print    # only print the entry, change nothing
Your existing config is backed up next to it as mcp_config.json.bak before any change.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT.parent / "harness"
CONFIG = Path.home() / ".gemini" / "config" / "mcp_config.json"


def entry() -> dict:
    return {"command": sys.executable,
            "args": [str(ROOT / "navmem" / "mcp_server.py"), "--bench-dir", str(HARNESS),
                     "--memory", str(ROOT / "bench" / "antigravity_memory.db"),
                     "--log", str(ROOT / "bench" / "antigravity_log.jsonl")]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", help="print the entry only")
    ap.add_argument("--config", default=str(CONFIG))
    a = ap.parse_args()
    if a.print:
        print(json.dumps({"mcpServers": {"navmem": entry()}}, indent=2))
        return
    cfg_path = Path(a.config)
    cfg = {}
    if cfg_path.exists():
        text = cfg_path.read_text(encoding="utf-8").strip()
        cfg = json.loads(text) if text else {}
        shutil.copy(cfg_path, cfg_path.with_suffix(".json.bak"))
        print(f"backed up existing config to {cfg_path.with_suffix('.json.bak')}")
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.setdefault("mcpServers", {})["navmem"] = entry()
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    HARNESS.mkdir(parents=True, exist_ok=True)
    print(f"navmem registered in {cfg_path}")
    print(f"Open this ONE folder in Antigravity for the whole benchmark: {HARNESS}")
    print("Then refresh MCP Servers (agent panel ... > MCP Servers) and check navmem is connected.")


if __name__ == "__main__":
    main()
