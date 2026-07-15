@echo off
REM ═══════════════════════════════════════════════════════════════════════
REM polyglot.cmd — Glue Engineer polyglot CLI wrapper (Windows cmd)
REM ═══════════════════════════════════════════════════════════════════════
REM Usage:
REM   polyglot scout python "requests"
REM   polyglot deep-init --project "my-project" --repos <url>...
REM   polyglot bridge python orjson rust serde_json
REM
REM Runs from ANY directory; all .glue/ output goes to the current
REM working directory (the project directory where Claude Code was launched).
REM ═══════════════════════════════════════════════════════════════════════

setlocal
set "SCRIPT_DIR=%~dp0"
set "PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%"
python -m polyglot %*
endlocal