"""Live dashboard for NeuroPlastic Navigation: watch the memory while agents work.

Reads the memory database and the MCP server's log every 1.5 s, so it updates live while an
agent (e.g. in Antigravity) works through the navmem MCP server. Standard library only.

Usage: python -m navmem.dashboard [--memory bench/antigravity_memory.db] [--log bench/antigravity_log.jsonl]
Then open http://localhost:8765
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_state(memory: Path, log: Path) -> dict:
    state = {"nodes": [], "edges": [], "events": [], "tasks": [], "live": None}
    if memory.exists():
        db = sqlite3.connect(f"file:{memory}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        state["nodes"] = [dict(r) for r in db.execute("SELECT id, type, pointer FROM nodes")]
        state["edges"] = [dict(r) for r in db.execute(
            "SELECT id, src, dst, type, why, strength, trust, source, status, dead_reason, misled_count FROM edges")]
        state["events"] = [dict(r) for r in db.execute(
            """SELECT e.id, e.ts, e.action, e.delta, e.reason, g.src, g.dst, g.type FROM events e
               JOIN edges g ON g.id = e.edge_id WHERE g.source = 'learned' ORDER BY e.id DESC LIMIT 40""")]
        db.close()
    if log.exists():
        open_tasks: dict[str, dict] = {}
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            tid = e.get("task_id")
            if e["event"] == "start_task":
                open_tasks[tid] = {"task_id": tid, "bug": e.get("bug"), "condition": e.get("condition"),
                                   "run": e.get("run"), "hints": e.get("hints", []), "steps": [], "ts": e["ts"]}
            elif e["event"] == "tool" and tid in open_tasks:
                open_tasks[tid]["steps"].append({"tool": e["tool"], "args": e.get("args", {}),
                                                 "result": e.get("result_head", "")[:90]})
            elif e["event"] == "finish_task":
                t = open_tasks.pop(tid, {"bug": e.get("bug")})
                state["tasks"].append({**{k: e.get(k) for k in (
                    "condition", "run", "bug", "tests_passed", "fixed", "nav_calls_to_root", "tool_calls",
                    "seconds", "links_learned", "fix_choice")}, "hints": t.get("hints", [])})
        if open_tasks:
            state["live"] = max(open_tasks.values(), key=lambda t: t["ts"])
    return state


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>NeuroPlastic Navigation</title>
<style>
:root{--bg:#0f1220;--panel:#171b2e;--line:#2a3150;--ink:#e8eaf2;--mute:#9aa3bd;--blue:#5b8cf0;--red:#e05a5a;--green:#3fbf7f;--amber:#e0a03a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.4 Inter,Segoe UI,system-ui,sans-serif}
header{display:flex;align-items:center;gap:28px;padding:14px 22px;border-bottom:1px solid var(--line)}
header h1{font-size:18px;margin:0;font-weight:700}header h1 span{color:var(--blue)}
.stat{display:flex;flex-direction:column}.stat b{font-size:20px}.stat small{color:var(--mute);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
main{display:grid;grid-template-columns:320px 1fr 360px;gap:14px;padding:14px;height:calc(100vh - 66px)}
section{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;overflow:auto}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--mute);margin:0 0 10px}
.pill{display:inline-block;padding:2px 8px;border-radius:99px;font-size:11px;font-weight:600;background:#25305a;color:#a9c1f5;margin-right:4px}
.pill.none{background:#3a2f22;color:#f0c27a}.step{padding:5px 0;border-bottom:1px solid #222944;font-family:Consolas,monospace;font-size:12px}
.step .r{color:var(--mute);display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hint{font-size:12px;color:#c9d6f7;padding:3px 0}.ev{padding:7px 0;border-bottom:1px solid #222944;font-size:12px}
.ev b{font-size:11px;text-transform:uppercase;letter-spacing:.05em}.add{color:var(--green)}.strengthen{color:var(--blue)}.weaken{color:var(--amber)}.kill{color:var(--red)}
.ev .why{color:var(--mute)}table{width:100%;border-collapse:collapse;font-size:12px}th,td{text-align:left;padding:5px 4px;border-bottom:1px solid #222944}th{color:var(--mute);font-weight:600}
.ok{color:var(--green)}.bad{color:var(--red)}#graphwrap{overflow:auto}svg text{fill:var(--ink);font-size:11px}
.legend{display:flex;gap:16px;font-size:12px;color:var(--mute);margin-bottom:8px}.legend i{display:inline-block;width:22px;height:3px;vertical-align:middle;margin-right:6px}
.empty{color:var(--mute);font-style:italic}
</style></head><body>
<header><h1>NeuroPlastic <span>Navigation</span></h1>
<div class="stat"><b id="s-nodes">0</b><small>locations</small></div>
<div class="stat"><b id="s-learned">0</b><small>learned links</small></div>
<div class="stat"><b id="s-dead">0</b><small>dead links</small></div>
<div class="stat"><b id="s-tasks">0</b><small>tasks done</small></div>
<div class="stat"><b id="s-pass">-</b><small>tests passed</small></div></header>
<main>
<section><h2>Live agent</h2><div id="live" class="empty">Waiting for an agent to call start_task...</div>
<h2 style="margin-top:18px">Finished tasks</h2><div id="tasks" class="empty">None yet</div></section>
<section id="graphwrap"><h2>Memory graph</h2>
<div class="legend"><span><i style="background:#3a4266"></i>static (parsed)</span><span><i style="background:var(--blue)"></i>learned (verified fix)</span><span><i style="background:var(--red)"></i>dead (reason kept)</span></div>
<svg id="graph"></svg></section>
<section><h2>Memory changes (audit log)</h2><div id="events" class="empty">No learned links yet</div></section>
</main>
<script>
const COLS = [["err","Errors"],["fn","Functions"],["file","Files"],["cfg","Config & DB"]];
const short = id => { const s = id.split(":").slice(1).join(":"); const p = s.split(/[\/.]/); return id.startsWith("fn:") ? p.slice(-1)[0] : id.startsWith("err:") ? s.slice(0,34) : s.split("/").slice(-1)[0]; };
const esc = s => String(s ?? "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
function draw(st){
  const used = new Set(); st.edges.forEach(e => { if (e.type !== "contains" || e.source === "learned") { used.add(e.src); used.add(e.dst); } });
  const nodes = st.nodes.filter(n => used.has(n.id));
  const col = n => n.type === "table" ? 3 : COLS.findIndex(c => c[0] === n.type);
  const W = 800, X = [4, 212, 420, 628], pos = {}, count = [0,0,0,0];
  nodes.sort((a,b) => a.id.localeCompare(b.id)).forEach(n => { const c = col(n); if (c < 0) return; pos[n.id] = {x: X[c], y: 50 + count[c]++ * 30}; });
  const H = 70 + Math.max(...count) * 30;
  let s = COLS.map((c,i) => `<text x="${X[i]}" y="20" style="fill:#9aa3bd;font-size:11px;font-weight:600;letter-spacing:.08em">${c[1].toUpperCase()}</text>`).join("");
  const order = {static:0, learned:1}; const edges = st.edges.filter(e => pos[e.src] && pos[e.dst]).sort((a,b) => (order[a.source]-order[b.source]) || (a.status==="dead") - (b.status==="dead"));
  for (const e of edges) {
    const a = pos[e.src], b = pos[e.dst]; const x1 = a.x + 168, y1 = a.y, x2 = b.x, y2 = b.y;
    const [x1b, x2b] = x2 > x1 ? [x1, x2] : [a.x, b.x + 168];
    const learned = e.source === "learned", dead = e.status === "dead";
    const color = dead ? "#e05a5a" : learned ? "#5b8cf0" : "#3a4266";
    const w = dead ? 2 : learned ? 1.5 + e.strength : 1;
    const mx = (x1b + x2b) / 2;
    s += `<path d="M${x1b} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2b} ${y2}" fill="none" stroke="${color}" stroke-width="${w}" ${dead ? 'stroke-dasharray="6 5"' : ""} opacity="${learned||dead ? 1 : .55}"><title>${esc(e.type)}: ${esc(e.why || "")}${dead ? " | DEAD: " + esc(e.dead_reason) : ""}</title></path>`;
  }
  for (const n of nodes) { const p = pos[n.id]; if (!p) continue;
    const hot = st.edges.some(e => e.source === "learned" && e.status === "live" && (e.src === n.id || e.dst === n.id));
    s += `<g><rect x="${p.x}" y="${p.y-11}" width="168" height="22" rx="6" fill="${hot ? "#1d2a52" : "#1b2036"}" stroke="${hot ? "#5b8cf0" : "#2a3150"}"/><text x="${p.x+8}" y="${p.y+4}">${esc(short(n.id))}</text><title>${esc(n.id)}</title></g>`;
  }
  const svg = document.getElementById("graph"); svg.setAttribute("width", W); svg.setAttribute("height", H); svg.innerHTML = s;
}
function render(st){
  const learned = st.edges.filter(e => e.source === "learned"), dead = st.edges.filter(e => e.status === "dead");
  document.getElementById("s-nodes").textContent = st.nodes.length;
  document.getElementById("s-learned").textContent = learned.filter(e => e.status === "live").length;
  document.getElementById("s-dead").textContent = dead.length;
  document.getElementById("s-tasks").textContent = st.tasks.length;
  const passed = st.tasks.filter(t => t.tests_passed).length;
  document.getElementById("s-pass").textContent = st.tasks.length ? `${passed}/${st.tasks.length}` : "-";
  const L = st.live, live = document.getElementById("live");
  if (L) { live.className = "";
    live.innerHTML = `<div><span class="pill ${L.condition==="none"?"none":""}">${esc(L.condition)}</span><span class="pill">${esc(L.run)}</span> <b>${esc(L.bug)}</b></div>
      <div style="margin:8px 0 4px;color:#9aa3bd;font-size:12px">Hints given (${L.hints.length})</div>${L.hints.map((h,i) => `<div class="hint">${i+1}. ${esc(h)}</div>`).join("") || '<div class="hint empty">none</div>'}
      <div style="margin:10px 0 4px;color:#9aa3bd;font-size:12px">Agent steps (${L.steps.length})</div>${L.steps.map((s,i) => `<div class="step">${i+1}. ${esc(s.tool)} ${esc(JSON.stringify(s.args)).slice(0,60)}<span class="r">${esc(s.result)}</span></div>`).join("")}`;
  } else { live.className = "empty"; live.textContent = "Waiting for an agent to call start_task..."; }
  const tasks = document.getElementById("tasks");
  if (st.tasks.length) { tasks.className = "";
    tasks.innerHTML = `<table><tr><th>run</th><th>bug</th><th>pass</th><th>nav</th><th>calls</th></tr>${st.tasks.slice().reverse().map(t => `<tr><td>${esc(t.condition)}/${esc(t.run)}</td><td>${esc((t.bug||"").slice(0,18))}</td><td class="${t.tests_passed?"ok":"bad"}">${t.tests_passed?"yes":"no"}</td><td>${t.nav_calls_to_root ?? "-"}</td><td>${t.tool_calls ?? "-"}</td></tr>`).join("")}</table>`; }
  const ev = document.getElementById("events");
  if (st.events.length) { ev.className = "";
    ev.innerHTML = st.events.map(e => `<div class="ev"><b class="${e.action}">${esc(e.action)}</b> ${esc(short(e.src))} &rarr; ${esc(short(e.dst))}<div class="why">${esc(e.reason || "")}</div></div>`).join(""); }
  draw(st);
}
async function tick(){ try { render(await (await fetch("/api/state")).json()); } catch (e) {} }
tick(); setInterval(tick, 1500);
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--memory", default=str(ROOT / "bench" / "antigravity_memory.db"))
    ap.add_argument("--log", default=str(ROOT / "bench" / "antigravity_log.jsonl"))
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    memory, log = Path(a.memory), Path(a.log)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/api/state"):
                body, ctype = json.dumps(read_state(memory, log), default=str).encode(), "application/json"
            else:
                body, ctype = PAGE.encode(), "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):   # keep the terminal quiet
            pass

    print(f"Dashboard: http://localhost:{a.port}   (memory: {memory}, log: {log})")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
