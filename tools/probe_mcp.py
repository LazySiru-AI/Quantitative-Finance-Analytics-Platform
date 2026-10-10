"""Verify the vibe-trading MCP server over stdio exactly as .mcp.json declares it."""
import json
import os
import pathlib
import subprocess
import sys

cfg = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
s = cfg["mcpServers"]["vibe-trading"]

env = {**os.environ, **s.get("env", {})}
proc = subprocess.Popen(
    [s["command"], *s["args"]],
    cwd=s.get("cwd"), env=env,
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, encoding="utf-8",
)

msgs = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "probe", "version": "0.0.1"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
]
out, err = proc.communicate("\n".join(json.dumps(m) for m in msgs) + "\n", timeout=180)

responses = {}
for line in out.splitlines():
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        m = json.loads(line)
    except json.JSONDecodeError:
        continue
    if "id" in m:
        responses[m["id"]] = m

init = responses.get(1, {}).get("result")
if init:
    info = init["serverInfo"]
    print(f"initialize  OK   server={info['name']} v{info['version']} "
          f"protocol={init['protocolVersion']}")
else:
    print(f"initialize  FAILED  {responses.get(1)}")

tools = responses.get(2, {}).get("result", {}).get("tools")
if tools:
    names = sorted(t["name"] for t in tools)
    print(f"tools/list  OK   {len(names)} tools")
    planned = ["analyze_trade_journal", "get_market_data", "get_macro_series",
               "get_sec_filings", "get_stock_profile", "get_financial_statements",
               "extract_shadow_strategy", "run_shadow_backtest", "backtest",
               "pattern_recognition"]
    missing = [p for p in planned if p not in names]
    print(f"planned tools present: {len(planned) - len(missing)}/{len(planned)}"
          + (f"  MISSING: {missing}" if missing else ""))
    placers = [n for n in names if any(k in n.lower()
               for k in ("place_order", "submit_order", "buy", "sell", "bash", "shell"))]
    print(f"order-placement / shell tools exposed: {placers or 'none'}")
else:
    print("tools/list  FAILED")

skipped = [ln.strip() for ln in err.splitlines() if "Skipped" in ln]
print(f"skipped modules: {skipped or 'none'}")
