# NeuroPlastic Navigation

**Shared memory for coding-agent swarms that remembers *where to look*, not what the answer was.**

Built at SatHack 2026.

## The problem

Every agent that debugs a system starts from zero. It lists folders, greps and opens the wrong files before it finds the real cause. Ten agents hitting related bugs repeat the same search ten times. Stored answers (semantic caches, notes) go stale the moment the code changes.

## The idea

Store **pointers, not facts**: "for this error, read `config.yaml` (look at `AUTH_POOL_SIZE`)". The agent still reads the file and decides. Memory only shortens the path.

1. **Start from a static map.** On day 1 the code is parsed (Python `ast`, config, DB tables, log strings) into a graph of files, functions, config keys, tables and errors.
2. **Learn only from verified fixes.** When an agent's fix passes the tests, the system compares the config before and after to find what was actually fixed, then links *error → fix location*.
3. **Forget what misleads.** A followed hint that missed the fix loses strength. After 3 misses the link is killed, and the reason is logged. Static links are never killed.
4. **The LLM stays in charge.** Hints are suggestions ranked by trust × strength. The agent verifies everything by reading.

## How a recall works

```
error text ──► normalize (numbers/IDs → <N>) ──► entry: embedding similarity to stored errors
          ──► walk the graph 1–3 hops (score = trust × strength, discounted per hop and for hubs)
          ──► top 5 hints: "read X (look at Y): why"
```

The entry step uses sentence embeddings (`all-MiniLM-L6-v2`), so reworded errors still match. Set `NAVMEM_ENTRY=overlap` to fall back to word overlap (also used automatically if `sentence-transformers` isn't installed).

## Results (real agent: Antigravity, via MCP)

Learn → drift → adapt → forget, with one agent and one bug:

| Run | Hint #1 | Calls before the root file | Total calls | Time | Fixed |
|---|---|---|---|---|---|
| auth-pool (fresh memory) | day-1 map | 2 | 17 | 116 s | ✅ learned `AUTH_POOL_SIZE` |
| gateway drift 1 | `AUTH_POOL_SIZE` (old answer) | 2 | 14 | 67 s | ✅ |
| gateway drift 2 | `PAYMENT_GATEWAY_TIMEOUT_MS` | **0** | 12 | 62 s | ✅ |
| gateway drift 3 | `PAYMENT_GATEWAY_TIMEOUT_MS` | **0** | 10 | 54 s | ✅ |

After drift run 3, the stale `AUTH_POOL_SIZE` link is dead, with its reason in the audit log.

An earlier multi-bug Antigravity run: average navigation calls before the root file were **4.5 (no memory) → 2.7 (memory, round 1) → 1.7 (round 2)**, with 8 of 8 fixes correct.

**Limits:** single runs, a small planted-bug system (6 bugs), and one agent harness. This is evidence the mechanism works, not a measured speed-up at scale. Embedding entry was added after these runs and has not been benchmarked yet.

## Repo layout

```
navmem/            the memory
  store.py           SQLite: nodes, edges (strength, trust, live/dead + reason), event log
  static_graph.py    day-1 map from code, config, DB and log strings
  normalize.py       error normalization
  embed.py           embedding entry match
  recall.py          error → ranked hints
  learn.py           verified fix → new links
  forget.py          misleading hints → weaker, then dead (with reason)
  mcp_server.py      MCP server for real agents (Antigravity, Claude Code, Cursor)
  dashboard.py       live browser dashboard
  obsidian_live.py   live Obsidian graph of the memory
  reset_demo.py      clean reset for demos/benchmarks
bench/
  fake_system/       small auth/payments/checkout/notify system with tests
  bugs.yaml          planted bugs, each with its accepted fixes
  agent.py, run.py   local-model benchmark (Ollama)
  scoring.py         intended / fallback / other / none
tests/             unit tests
ANTIGRAVITY_BENCHMARK.md   step-by-step benchmark with a real agent
```

## Run it (Windows PowerShell)

```
pip install -r requirements.txt
python -m pytest -q tests
python -m navmem.demo_learning          # learning + forgetting in the terminal
```

Use it from Antigravity (or any MCP client):

```
python -m navmem.install_mcp            # registers the navmem MCP server
python -m navmem.reset_demo             # clean memory
python -m navmem.bench_next auth-pool-too-small --condition memory --run r1
```

Paste the printed prompt into the agent. Watch it live with `python -m navmem.dashboard` (http://localhost:8765) or `python -m navmem.obsidian_live` (Obsidian graph view). The full benchmark steps are in `ANTIGRAVITY_BENCHMARK.md`.

## Tech stack

Python · SQLite · `ast` · PyYAML · sentence-transformers · MCP Python SDK · Ollama (qwen3:8b) · Antigravity · Obsidian

## What's next

- Benchmark embedding entry on reworded-error bugs
- Test on a real-repo benchmark (SWE-bench navigation)
- Multiple agents writing to one memory at the same time
