@echo off
REM set-identity.cmd — Set git identity for commits (Windows)
REM Usage: call set-identity.cmd

git config user.name "ID-VerNe"
git config user.email "yuu_seeing@foxmail.com"

set GIT_COMMITTER_NAME=ID-VerNe
set GIT_COMMITTER_EMAIL=yuu_seeing@foxmail.com

echo [v] Git identity: ID-VerNe