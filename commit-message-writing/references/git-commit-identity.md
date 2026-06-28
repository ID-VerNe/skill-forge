---
name: git-commit-identity
description: When making commits, always use ID-VerNe identity and never add Co-Authored-By trailers
metadata:
  type: feedback
---

**Do not** use "Code Agent" or any Claude-related name as Author or Committer in git commits.

**Do not** add `Co-Authored-By: Claude ...` or similar trailers to commit messages — GitHub interprets these as co-authors and displays "N people" on the commit.

Before committing, always:
1. Set both `user.name` and `user.email` via git config to the user's identity
2. Set env vars `GIT_COMMITTER_NAME` and `GIT_COMMITTER_EMAIL` to match
3. Verify no `Co-Authored-By` line is present in the commit message body

User's identity: `ID-VerNe <yuu_seeing@foxmail.com>`

**Why:** The user wants all commits to appear solely under their own name on GitHub. Claude/Code Agent should never be visible in commit attribution.

**How to apply:** Before every `git commit`, run `git config user.name "ID-VerNe" && git config user.email "yuu_seeing@foxmail.com"`. Use `GIT_COMMITTER_NAME` / `GIT_COMMITTER_EMAIL` env vars on `--amend` if needed. Strip any `Co-Authored-By` lines from the commit message.