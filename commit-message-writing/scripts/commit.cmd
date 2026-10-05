@echo off
REM commit.cmd — Commit with identity enforcement (Windows)
REM Usage: commit.cmd <message_file>
REM Reads commit message from file, loads identity via set-identity.cmd,
REM rejects Co-Authored-By trailers, then commits.
REM Exits non-zero on any failure (missing file, forbidden trailer,
REM git commit error).

REM NOTE: No `setlocal` — env vars set by `call set-identity.cmd` must
REM persist through this script's lifetime to reach `git commit`.

if "%1"=="" (
  echo Usage: commit.cmd ^<message_file^>
  exit /b 1
)
if not exist "%1" (
  echo [x] Message file not found: %1
  exit /b 1
)

REM Resolve script directory (works when called from anywhere)
for %%d in ("%~dp0.") do set "SCRIPT_DIR=%%~fd"

REM Reject Co-Authored-By (literal match, suppress output)
findstr /i /l "Co-Authored-By" "%1" >nul 2>nul
if %errorlevel% equ 0 (
  echo [x] Commit message contains Co-Authored-By line! Remove it first.
  exit /b 1
)

REM Load identity (calls set-identity.cmd in the same session)
call "%SCRIPT_DIR%\set-identity.cmd"
if %errorlevel% neq 0 (
  echo [x] Identity setup failed.
  exit /b %errorlevel%
)

REM Commit using -F to read from file
git commit -F "%1"
if %errorlevel% neq 0 (
  echo [x] git commit failed with exit code %errorlevel%
  exit /b %errorlevel%
)
echo [v] Commit successful.
exit /b 0
