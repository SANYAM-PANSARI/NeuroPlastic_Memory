"""Minimal tool-calling agent loop. The model is swappable (Ollama, or a script for tests)."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

from bench.tools import Toolbox

SYSTEM = (
    "You are debugging a small Python project. Find the root cause of the symptom and fix it. "
    "Read code, config, logs and the database; do not guess. Make the smallest fix with "
    "edit_file, then call run_tests. If tests fail, keep investigating. When run_tests says "
    "PASSED, call done(summary) once and stop."
)


@dataclass
class ToolCall:
    name: str
    args: dict


class OllamaModel:
    def __init__(self, model: str, host: str | None = None, think: bool = False):
        import ollama
        self.client = ollama.Client(host=host) if host else ollama.Client()
        self.model = model
        self.think = think

    def step(self, messages: list, tools: list) -> tuple[dict, list[ToolCall]]:
        r = self.client.chat(model=self.model, messages=messages, tools=tools, think=self.think,
                             options={"temperature": 0, "num_ctx": 8192})
        msg = r.message
        calls = [ToolCall(tc.function.name, dict(tc.function.arguments or {}))
                 for tc in (msg.tool_calls or [])]
        return msg.model_dump(exclude_none=True), calls


def run_agent(model, box: Toolbox, symptom: str, max_steps: int = 20, time_limit: float = 240) -> dict:
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": symptom}]
    t0 = time.time()
    for step in range(max_steps):
        if time.time() - t0 > time_limit:
            print("    time limit reached", flush=True)
            break
        assistant_msg, calls = model.step(messages, box.specs())
        print(f"    step {step + 1}: " + (", ".join(f"{c.name}({str(c.args)[:60]})" for c in calls) or "no tool call"), flush=True)
        messages.append(assistant_msg)
        if not calls:
            messages.append({"role": "user", "content": "Use a tool, or call found() if you are done."})
            continue
        for c in calls:
            out = box.call(c.name, c.args)
            messages.append({"role": "tool", "tool_name": c.name, "content": str(out)})
        if box.claim:
            break
    return {"seconds": round(time.time() - t0, 2), "found": box.claim, "calls": box.calls,
            "transcript": json.dumps(messages, default=str)[:20000]}
