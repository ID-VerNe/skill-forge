@echo off
REM set-identity.cmd — Set git identity for commits (call, don't type directly)
REM Usage: call set-identity.cmd
REM
REM Reads identity from identity.env (single source of truth). Applies:
REM   1. `git config` — persistent identity for this repo
REM   2. `set GIT_*`  — per-session overrides for the CURRENT cmd.exe only
REM
REM WARNING: Windows CMD has no real "source" — env vars set here live only
REM inside the cmd.exe that CALLS this script. A new cmd.exe window or a
REM separate process will NOT see them. If you need identity for a follow-up
REM commit, either `call` in the same window, or rely on `git config`
REM (already persisted by step 1 above).
REM
REM NOTE: This script intentionally does NOT use `setlocal` — the exported
REM env vars must survive past the script return so that a subsequent
REM `git commit` in the same cmd.exe window sees them.

for %%d in ("%~dp0.") do set "SCRIPT_DIR=%%~fd"
set "IDENTITY_FILE=%SCRIPT_DIR%\identity.env"

if not exist "%IDENTITY_FILE%" (
  echo [x] identity.env not found: %IDENTITY_FILE%
  exit /b 1
)

REM Load identity into environment (KEY=VAL lines; for /f skips blanks)
for /f "usebackq tokens=1,* delims==" %%a in ("%IDENTITY_FILE%") do (
  set "%%a=%%b"
)

REM Verify required keys
if "%GIT_AUTHOR_NAME%"=="" (
  echo [x] GIT_AUTHOR_NAME missing from identity.env
  exit /b 1
)
if "%GIT_AUTHOR_EMAIL%"=="" (
  echo [x] GIT_AUTHOR_EMAIL missing from identity.env
  exit /b 1
)

REM --- Step 1: persist to git config (per-repo) -------------------------
git config user.name "%GIT_AUTHOR_NAME%"
git config user.email "%GIT_AUTHOR_EMAIL%"
if %errorlevel% neq 0 (
  echo [x] git config failed
  exit /b %errorlevel%
)

REM --- Step 2: export env vars into the current cmd session -------------
REM (git reads GIT_AUTHOR_* / GIT_COMMITTER_* directly from env)
set "GIT_COMMITTER_NAME=%GIT_AUTHOR_NAME%"
set "GIT_COMMITTER_EMAIL=%GIT_AUTHOR_EMAIL%"

echo [v] Git identity: %GIT_AUTHOR_NAME% ^<%GIT_AUTHOR_EMAIL%^>
exit /b 0
