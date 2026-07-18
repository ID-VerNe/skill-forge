@echo off
REM commit.cmd — Commit with identity enforcement (Windows)
REM Usage: commit.cmd <message_file>
REM Reads commit message from file, sets identity, checks Co-Authored-By.

if "%1"=="" (
  echo Usage: commit.cmd ^<message_file^>
  exit /b 1
)
if not exist "%1" (
  echo [x] Message file not found: %1
  exit /b 1
)

REM Set identity
git config user.name "ID-VerNe"
git config user.email "yuu_seeing@foxmail.com"
set GIT_COMMITTER_NAME=ID-VerNe
set GIT_COMMITTER_EMAIL=yuu_seeing@foxmail.com

REM Check for Co-Authored-By (literal match, suppress all output)
findstr /i /l "Co-Authored-By" "%1" >nul 2>nul
if %errorlevel% equ 0 (
  echo [x] Commit message contains Co-Authored-By line! Remove it first.
  exit /b 1
)

REM Commit using -F to read from file
git commit -F "%1"
echo [v] Commit successful.