#!/bin/bash
# set-identity.sh — Set git identity for commits
# Usage: source set-identity.sh
# Must be sourced (not executed) to export env vars into the current shell.

git config user.name "ID-VerNe"
git config user.email "yuu_seeing@foxmail.com"

export GIT_COMMITTER_NAME="ID-VerNe"
export GIT_COMMITTER_EMAIL="yuu_seeing@foxmail.com"

echo "[v] Git identity: ID-VerNe <yuu_seeing@foxmail.com>"