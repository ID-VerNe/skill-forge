@echo off
REM stage.cmd — Stage files one by one (Windows)
REM Usage: stage.cmd <file1> [file2 ...]
REM
REM Rules enforced:
REM   - Every argument must be an existing regular file.
REM   - Directories are REJECTED — `git add <dir>` would recurse and silently
REM     stage everything under it, defeating the explicit-per-file contract.
REM   - Exit /b 1 on any missing or directory argument (before running git add).

if "%1"=="" (
  echo Usage: stage.cmd ^<file1^> [file2 ...]
  echo Tip: run 'git status' first to see what's available.
  exit /b 1
)

:loop
if "%1"=="" goto end
if exist "%1" (
  if exist "%1\" (
    echo [x] Refusing to stage a directory: %1
    echo     'git add ^<dir^>' would recurse and stage every file inside it.
    echo     Stage individual files instead -- see 'git status' for the list.
    exit /b 1
  )
  git add -- "%1"
  echo [v] Staged: %1
) else (
  echo [x] Not found: %1
  exit /b 1
)
shift
goto loop

:end
echo [v] All files staged successfully.
exit /b 0
