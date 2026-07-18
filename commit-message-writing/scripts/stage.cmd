@echo off
REM stage.cmd — Stage files one by one (Windows)
REM Usage: stage.cmd <file1> [file2 ...]

if "%1"=="" (
  echo Usage: stage.cmd ^<file1^> [file2 ...]
  echo Tip: run 'git status' first to see what's available.
  exit /b 1
)

:loop
if "%1"=="" goto end
if exist "%1" (
  git add "%1"
  echo [v] Staged: %1
) else (
  echo [x] Not found: %1
  exit /b 1
)
shift
goto loop

:end
echo [v] All files staged successfully.