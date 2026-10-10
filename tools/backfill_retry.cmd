@echo off
rem Auto-retry the influencer YouTube backfill bundler until YouTube's transcript endpoint stops
rem IP-blocking this machine, then write task packets into .backfill-tasks/ for the owner to paste
rem into Gemini. Registered as the scheduled task "InvDash-Backfill-Retry" (every 2h).
rem
rem SAFE UNDER TASK SCHEDULER's detached session, unlike the Phase B *launch* (phase_b_daily.cmd):
rem this tool makes NO model call and spawns NO child research thread, so it never reaches the
rem ssl.create_default_context -> httpx path in a background thread that aborts the GIL there. It is
rem pure yt-dlp listing + youtube-transcript-api fetch on the main thread.
rem
rem Idempotent: a video already ingested (has_note) or whose transcript still cannot be fetched is
rem skipped, so a run while the IP is blocked simply logs the block and writes nothing; once the block
rem clears, the next run writes the packets. --limit keeps each run's request count small and kind to
rem the IP. Remove with:  schtasks /delete /tn "InvDash-Backfill-Retry" /f
rem Script lives in <repo>\tools\, so its parent is the repo root -- keep this path-portable.
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set INVDASH_AUTH_ENABLED=0
echo ---------- %DATE% %TIME% ---------- >> "data\backfill_retry.log"
".venv\Scripts\python.exe" -u "tools\backfill_task_bundler.py" --limit 3 >> "data\backfill_retry.log" 2>&1
echo (exit %ERRORLEVEL%) >> "data\backfill_retry.log"
