#!/usr/bin/env bash
# Round 11's live matrix: the out-of-sample period, as six CUMULATIVE runs from one fixed start.
#
# **Why cumulative and not six independent sub-window runs.** The first version of this script ran
# each sub-window as its own tournament, starting 2026-03-19, 2026-04-20 and so on. Every one of
# those runs starts with a FLAT BOOK, so a card holding positions it entered in March was made to
# liquidate and re-enter at each boundary. `B-momentum` went from 11 trades and 56.9% exposure over
# the full window to two entire sub-windows at 0.0% exposure and zero trades -- not because it was
# in cash, but because its entry rule never re-fired inside 21 sessions from a standing start. That
# matrix measured "this card, liquidated every 21 sessions", which is a different strategy, and it
# systematically rewarded high-turnover cards over ones that hold. See DEFECTS.md D5; the invalid
# output is kept at data/rounds/r11-2026-08/results-independent-INVALID as the evidence for it.
#
# So every run starts at the same true start and ends at a sub-window boundary. Position continuity
# is preserved because there is only ever one entry point. `strategy-program/tools/round11.py`
# recovers each sub-period by differencing consecutive runs, which is exact for all three quantities
# it needs -- see that module's `live_cells`.
#
# Serial, and not for performance: the bar store is a single DuckDB file whose read path opens
# read-write, so a concurrent reader raises an IOException the runner records as an ordinary *card
# failure* and walks past, producing a report that looks complete and is quietly missing cards
# (DEFECTS.md D3). Nothing else may touch the store while this runs.
#
# Boundaries are pre-registered in strategy-program/ROUND-11-PLAN.md section 2 and come from SPY's
# own session calendar. They are not adjustable here.
#
# Usage: run_live_matrix.sh <cards-dir> <results-root>

set -uo pipefail

CARDS="${1:?usage: run_live_matrix.sh <cards-dir> <results-root>}"
OUT="${2:?usage: run_live_matrix.sh <cards-dir> <results-root>}"
PY='.venv/Scripts/python.exe'
PERSONA='uat/personas/pro-investor-01.setup.json'
START='2026-02-17'

export PYTHONPATH="backend;."

# Same guard as run_round.sh, same reason for its shape: a python process launching `-m app.tournament`,
# not any process whose command text mentions the module (see run_round.sh for the false positive).
others=$(powershell.exe -NoProfile -Command "@(Get-CimInstance Win32_Process | Where-Object { \$_.Name -match '^python' -and \$_.CommandLine -match '-m app\.tournament(\s|$)' }).Count" 2>/dev/null | tr -d '')
if [ -n "${others:-}" ] && [ "$others" -gt 0 ] 2>/dev/null; then
  echo "REFUSING TO START: $others tournament process(es) already running against the store." >&2
  exit 1
fi

# mkdir before the loop: the per-window log is written by a shell redirect, which fails if the
# directory does not exist yet -- and a failed redirect loses the whole window's output silently.
mkdir -p "$OUT"

n_cards=$(find "$CARDS" -maxdepth 1 -name '*.json' | wc -l)
echo "field: $n_cards cards from $CARDS"
echo "every run starts $START; the tag names where it ENDS"
echo

WINDOWS=(
  "live-1:2026-03-18"
  "live-2:2026-04-17"
  "live-3:2026-05-18"
  "live-4:2026-06-17"
  "live-5:2026-07-20"
  "live-6:2026-08-18"
)

for spec in "${WINDOWS[@]}"; do
  IFS=: read -r tag end <<<"$spec"
  echo "=============================================================="
  echo "CUMULATIVE $tag  $START -> $end"
  echo "=============================================================="

  # Capture the runner's own exit status *before* the pipe, so a total failure cannot hide behind a
  # grep further down the pipeline that simply matched nothing.
  "$PY" -m app.tournament --cards "$CARDS" --out "$OUT/$tag" --persona "$PERSONA" \
      --start "$START" --end "$end" --skip-pdf > "$OUT/$tag.log" 2>&1
  rc=$?

  ran=$(find "$OUT/$tag/runs" -name '*.json' 2>/dev/null | wc -l)
  failed=$(grep -c 'FAILED' "$OUT/$tag.log" 2>/dev/null || echo 0)
  echo "-- $tag: exit=$rc, $ran run files, $failed FAILED lines"
  grep 'FAILED' "$OUT/$tag.log" | sed 's/^/   /' || true
  echo
done

echo "=============================================================="
echo "RECONCILIATION -- expect 15 runs in each of 6 windows (90 total)"
echo "=============================================================="
printf '%-10s %6s %8s\n' window runs failed
total=0
for spec in "${WINDOWS[@]}"; do
  IFS=: read -r tag _ <<<"$spec"
  ran=$(find "$OUT/$tag/runs" -name '*.json' 2>/dev/null | wc -l)
  failed=$(grep -c 'FAILED' "$OUT/$tag.log" 2>/dev/null || echo 0)
  total=$((total + ran))
  printf '%-10s %6s %8s\n' "$tag" "$ran" "$failed"
done
echo
echo "total run files: $total (expected 90)"
echo "A shortfall is a lost card, not a rounding detail. Re-run that window alone"
echo "rather than scoring around the gap."
