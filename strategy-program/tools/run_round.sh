#!/usr/bin/env bash
# Run one competition round: every window, serially, with reconciliation.
#
# Serial is not a performance choice. The bar store is a single DuckDB file whose read path opens
# read-write, so a concurrent reader raises an IOException that the runner records as a *card
# failure* and then walks past. A contended round therefore produces a report that looks complete
# and is quietly missing cards. Nothing else may touch the store while this runs.
#
# Usage: run_round.sh <cards-dir> <results-root>

set -uo pipefail

CARDS="${1:?usage: run_round.sh <cards-dir> <results-root>}"
OUT="${2:?usage: run_round.sh <cards-dir> <results-root>}"
PY='.venv/Scripts/python.exe'
PERSONA='uat/personas/pro-investor-01.setup.json'

export PYTHONPATH="backend;."

# Refuse to start if another run is already alive. Two concurrent runs do not queue -- they both
# take the store's write lock, and every card in both fails with an IOException the runner records
# as an ordinary card failure and walks past. The result is two runs producing zero results while
# looking, line by line, like ordinary guard refusals. This has happened; see DEFECTS.md D3.
#
# Match a *python* process whose command line launches the tournament module (`-m app.tournament`,
# which is exactly what this script and run_live_matrix.sh invoke) -- not any process whose command
# text merely mentions `app.tournament`. The looser pattern refused a round on 2026-09-09 because two
# orphaned bash shells from another session carried a heredoc that imported
# `app.tournament.models`; neither had a python child and nothing was touching the store.
others=$(powershell.exe -NoProfile -Command "@(Get-CimInstance Win32_Process | Where-Object { \$_.Name -match '^python' -and \$_.CommandLine -match '-m app\.tournament(\s|$)' }).Count" 2>/dev/null | tr -d '\r\n')
if [ -n "${others:-}" ] && [ "$others" -gt 0 ] 2>/dev/null; then
  echo "REFUSING TO START: $others tournament process(es) already running against the store." >&2
  echo "Kill them first -- a concurrent run silently produces zero results." >&2
  exit 1
fi

n_cards=$(find "$CARDS" -maxdepth 1 -name '*.json' | wc -l)
echo "field: $n_cards cards from $CARDS"
echo

# tag:start:end:only-filter  (empty filter = whole field)
WINDOWS=(
  "q4-2018:2018-09-21:2018-12-24:"
  "covid:2020-02-19:2020-06-30:"
  "bear-2022:2022-01-03:2022-10-12:"
  "chop-2015:2015-04-07:2016-04-15:"
  "chop-2011:2011-05-26:2012-06-06:"
  "bull-2024:2024-08-21:2025-08-20:"
  "recent:2025-08-21:2026-08-18:"
  "gfc:2007-10-09:2009-03-09:"
  "13f-legal:2025-11-17:2026-08-18:c06-13f"
)

for spec in "${WINDOWS[@]}"; do
  IFS=: read -r tag start end only <<<"$spec"
  echo "=============================================================="
  echo "WINDOW $tag  $start -> $end"
  echo "=============================================================="
  args=(--cards "$CARDS" --out "$OUT/$tag" --persona "$PERSONA"
        --start "$start" --end "$end" --skip-pdf)
  [ -n "$only" ] && args+=(--only "$only")

  "$PY" -m app.tournament "${args[@]}" 2>&1 | tee "$OUT/$tag.log"

  # Reconcile: the runner never aborts on a failed card, so a silent shortfall is the
  # failure mode to catch here rather than in the report.
  ran=$(find "$OUT/$tag/runs" -name '*.json' 2>/dev/null | wc -l)
  failed=$(grep -c 'FAILED' "$OUT/$tag.log" 2>/dev/null || echo 0)
  echo
  echo "-- $tag: $ran run files, $failed FAILED lines"
  grep 'FAILED' "$OUT/$tag.log" | sed 's/^/   /' || true
  echo
done

echo "=============================================================="
echo "RECONCILIATION"
echo "=============================================================="
printf '%-12s %6s %8s\n' window runs failed
for spec in "${WINDOWS[@]}"; do
  IFS=: read -r tag _ _ _ <<<"$spec"
  ran=$(find "$OUT/$tag/runs" -name '*.json' 2>/dev/null | wc -l)
  failed=$(grep -c 'FAILED' "$OUT/$tag.log" 2>/dev/null || echo 0)
  printf '%-12s %6s %8s\n' "$tag" "$ran" "$failed"
done
echo
echo "Any IOException among the FAILED lines above means a card was lost to store"
echo "contention rather than to an honest guard failure. Re-run that window alone."
