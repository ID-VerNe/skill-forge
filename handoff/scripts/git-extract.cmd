@echo off
setlocal enabledelayedexpansion
REM git-extract.cmd - extract handoff data (Windows CMD)

echo === 项目元数据 ===
IF EXIST package.json (
  echo 存在 package.json
)

echo -- 包管理器 --
IF EXIST pnpm-lock.yaml echo pnpm
IF EXIST package-lock.json echo npm
IF EXIST yarn.lock echo yarn
IF EXIST bun.lockb echo bun
IF EXIST pyproject.toml echo python
IF EXIST go.mod echo go
IF EXIST Cargo.toml echo rust
IF EXIST composer.json echo php

echo -- 技术栈标志 --
IF EXIST docker-compose.yml echo 有 docker-compose.yml
IF EXIST Dockerfile echo 有 Dockerfile
IF EXIST Makefile echo 有 Makefile

echo -- 目录结构 --
IF EXIST src\ echo   有 src/ 目录
IF EXIST app\ echo   有 app/ 目录
IF EXIST client\ echo   有 client/ 目录
IF EXIST frontend\ echo   有 frontend/ 目录
IF EXIST backend\ echo   有 backend/ 目录
IF EXIST server\ echo   有 server/ 目录
IF EXIST components\ echo   有 components/ 目录
IF EXIST pages\ echo   有 pages/ 目录
IF EXIST apps\ echo   有 apps/ 目录
IF EXIST packages\ echo   有 packages/ 目录
IF EXIST tools\ echo   有 tools/ 目录
IF EXIST lib\ echo   有 lib/ 目录
IF EXIST core\ echo   有 core/ 目录
IF EXIST api\ echo   有 api/ 目录
IF EXIST admin\ echo   有 admin/ 目录
IF EXIST web\ echo   有 web/ 目录
IF EXIST mobile\ echo   有 mobile/ 目录
IF EXIST worker\ echo   有 worker/ 目录

echo.
echo === Git 信息 ===
IF NOT EXIST .git (
  echo 当前目录不是 git 仓库，跳过 git 信息提取。
  exit /b 0
)

for /f "tokens=*" %%a in ('git rev-parse --abbrev-ref HEAD 2^>nul') do echo 当前分支: %%a
for /f "tokens=*" %%a in ('git rev-parse --short HEAD 2^>nul') do echo 当前 HEAD: %%a

echo.
echo === 基线检测 ===
IF EXIST .handoffs\ (
  set "LATEST_HANDOFF="
  for /f %%a in ('dir /b /on .handoffs\handoff-*.md 2^>nul') do set "LATEST_HANDOFF=%%a"
  IF DEFINED LATEST_HANDOFF (
    echo 找到上一份 handoff: .handoffs\!LATEST_HANDOFF!
  ) ELSE (
    echo 未找到 handoff 文件
  )
) ELSE (
  echo 未找到 .handoffs 目录
)

echo.
echo === Commit 日志（最近 30 条） ===
git log --oneline --decorate -30 2>nul

echo.
echo === Commit 详情（最近 10 条） ===
git log --format="---%%nHASH:%%h%%nDATE:%%ad%%nAUTHOR:%%an%%nDESC:%%s%%n" --date=format:"%%Y-%%m-%%d %%H:%%M" -10 2>nul

echo.
echo === 未提交的改动 ===
git status --short 2>nul

echo.
echo === git 身份 ===
for /f "tokens=*" %%a in ('git config user.name 2^>nul') do echo user.name: %%a
for /f "tokens=*" %%a in ('git config user.email 2^>nul') do echo user.email: %%a