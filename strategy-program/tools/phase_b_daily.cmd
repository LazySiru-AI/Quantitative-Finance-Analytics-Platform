@echo off
rem Round 33 Phase B daily step. Invoked by the "Round33-PhaseB-Daily" scheduled task on weekdays.
rem
rem SCHEDULED PATH RUNS FILL/RESOLVE ONLY (--no-launch), deliberately. The in-process LLM *launch*
rem (child Trading Agents / Vibe research) crashes natively under Task Scheduler's detached
rem environment -- a "Fatal Python error: PyEval_SaveThread ... the GIL is released" abort during
rem SSL context creation (ssl.create_default_context -> httpx -> market.registry.default_registry)
rem in a child research thread, observed 2026-09-01. The exact same launch runs fine interactively
rem (a normal console/window-station), so this is an environment issue, not a code bug, and a native
rem process abort cannot be caught in Python. Running --no-launch here keeps the reliable, deterministic
rem daily work -- fill matured screen orders + resolve matured observations -- which never touches
rem threads or SSL and so cannot crash, and leaves no orphaned "running" run behind.
rem
rem To ACCRUE new gated candidates (the launch half), run the launch from an interactive session:
rem     .venv\Scripts\python.exe -u strategy-program\tools\phase_b_step.py
rem or POST the frozen request to a running backend (app.workflow.phase_b.phase_b_request), whose
rem server process is not detached and researches children without crashing.
cd /d "%~dp0..\.."
echo ---------- %DATE% %TIME% (scheduled: fill/resolve only) ---------- >> "data\round33\phase_b_daily.log"
".venv\Scripts\python.exe" -u "strategy-program\tools\phase_b_step.py" --no-launch >> "data\round33\phase_b_daily.log" 2>&1
