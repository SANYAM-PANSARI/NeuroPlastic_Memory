# Benchmarking NeuroPlastic Navigation in Antigravity

**Goal:** check whether a real agent (Antigravity) fixes bugs faster with our memory.
Same bugs, three runs:

| Run | Memory | Why |
|---|---|---|
| `none / r1` | off: no hints, nothing learned | the baseline |
| `memory / r1` | on, starting from the day-1 map | first contact |
| `memory / r2` | on, with what r1 learned | does learning help? |
| `memory / d1, d2, d3` | on; the gateway bug 3 times in a row | does it forget a shortcut that stopped working? |

Bugs: `auth-pool-too-small`, `checkout-hangs-same-cause`, `payments-timeout-drift`,
`payments-gateway-drift` (4 bugs x 3 runs + 3 drift runs = 15 tasks).

- `payments-timeout-drift` has **two valid fixes** (lower PAYMENT_CONCURRENCY, or raise
  AUTH_POOL_SIZE). Both count as correct; the results say which one the agent chose.
- `payments-gateway-drift` (added 2026-11-22, before any run) is the real forgetting test: same
  symptom as the pool bug, but only PAYMENT_GATEWAY_TIMEOUT_MS fixes it. Every tool call is logged to `bench\antigravity_log.jsonl`;
the server re-runs the tests itself to score each task.

**You register the server once and open one folder.** Before each task you run one
command that tells the server which bug is next; when the agent calls `start_task`, the
server plants that bug in a fresh copy and works there.

---

## Setup (once)

```
cd /d D:\THAPAR\Hackathons\SatHack\npnav
pip install -r requirements.txt
python -m pytest -q tests                 (expect: 23 passed)
python -m navmem.install_mcp
```
`install_mcp` adds `navmem` to `C:\Users\<you>\.gemini\config\mcp_config.json`
(your old config is backed up as `mcp_config.json.bak`).

In Antigravity:
1. Open the folder `D:\THAPAR\Hackathons\SatHack\harness` (keep it open the whole time).
2. Agent panel → … → MCP Servers → refresh. Check **navmem** is connected.

---

## Option A: by hand (Antigravity app or IDE)

**Start fresh:** delete `bench\antigravity_memory.db` and `bench\antigravity_log.jsonl`
(the old memory still holds a link wrongly killed by a bug that is now fixed).

For each task, in this order (all `none`, then `memory r1`, then `memory r2`, then drift):

```
python -m navmem.bench_next auth-pool-too-small --condition none --run r1
```
It prints the prompt. Paste it into the agent (a **new chat** each time) and let it finish.
Then the next one:

```
python -m navmem.bench_next checkout-hangs-same-cause --condition none --run r1
python -m navmem.bench_next payments-timeout-drift   --condition none --run r1
python -m navmem.bench_next payments-gateway-drift   --condition none --run r1
python -m navmem.bench_next auth-pool-too-small      --condition memory --run r1
python -m navmem.bench_next checkout-hangs-same-cause --condition memory --run r1
python -m navmem.bench_next payments-timeout-drift   --condition memory --run r1
python -m navmem.bench_next payments-gateway-drift   --condition memory --run r1
python -m navmem.bench_next auth-pool-too-small      --condition memory --run r2
python -m navmem.bench_next checkout-hangs-same-cause --condition memory --run r2
python -m navmem.bench_next payments-timeout-drift   --condition memory --run r2
python -m navmem.bench_next payments-gateway-drift   --condition memory --run r2
python -m navmem.bench_next payments-gateway-drift   --condition memory --run d1
python -m navmem.bench_next payments-gateway-drift   --condition memory --run d2
python -m navmem.bench_next payments-gateway-drift   --condition memory --run d3
```
Always run `bench_next` **before** pasting: the server reads it when the agent calls `start_task`.

## Option B: automatic (Antigravity CLI, `agy`)

1. Install (PowerShell): `irm https://antigravity.google/cli/install.ps1 | iex`, then run `agy`
   once to sign in.
2. Check the plan: `python -m navmem.run_antigravity --dry-run`
3. Run: `python -m navmem.run_antigravity --fresh --model "<model slug>"`
   - Approve tool prompts as they appear, or add `--auto-approve` for fully unattended runs.
     **Warning:** `--auto-approve` lets the agent run ANY command on your laptop without asking.
   - Each task is stopped after 10 minutes (`--time-limit`).
   - Try one bug first: `--bugs auth-pool-too-small`, then check the log has lines.

---

## Read the results

```
python -m navmem.analyze_harness
```
Prints a table and a summary per run, and writes `bench\antigravity_results.csv`.

| Column | Meaning |
|---|---|
| pass | tests pass after the agent's fix |
| root | it fixed the planted root cause |
| nav | tool calls before it first opened the root-cause file (**lower is better**) |
| calls / secs | total tool calls and time |
| hints | how many hints it got |
| outside | **True = it used Antigravity's own tools**: that run says little about us |

**Win conditions (set before the runs):**
1. `memory / r2` needs fewer `nav` calls than `none / r1`, with no drop in `pass`.
2. Drift: by `d3`, the first hint for the gateway bug is PAYMENT_GATEWAY_TIMEOUT_MS, not
   AUTH_POOL_SIZE, and the old link has been weakened or killed with a logged reason.

## Keep it fair
- Same model for every task; a new chat for every task.
- Don't help the agent mid-task (except "use only the navmem tools").
- Many `outside = True` rows means the agent ignored our tools: fix that before trusting results.
- Start over: delete `bench\antigravity_memory.db` and `bench\antigravity_log.jsonl` (or `--fresh`).

## Troubleshooting
- **navmem not connected:** run `python -m navmem.install_mcp --print` and compare with the config;
  run the server by hand to see errors:
  `python navmem\mcp_server.py --bench-dir D:\THAPAR\Hackathons\SatHack\harness`
  (no output and waiting = fine, press Ctrl+C).
- **"no such file current_run.json":** you skipped `bench_next` before the task.
- **`agy` hangs with no output:** known Windows issue when its output is redirected; our runner
  never redirects it.
