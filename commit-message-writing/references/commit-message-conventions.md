---
name: commit-message-conventions
description: Project commit message format and git conventions for abdm-cli
metadata: 
  node_type: memory
  type: reference
  originSessionId: e236e5c0-5168-4855-9190-066a0c49433e
---

## Commit Author
- Always use `--author="ID-VerNe <>"`
- Never mention AI/Claude/code agent in any commit message

## Type Prefix
Use conventional commits prefix:
- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation
- `style:` — formatting (no code behavior change)
- `refactor:` — refactoring (neither feature nor bug fix)
- `perf:` — performance improvement
- `test:` — adding tests
- `chore:` — build process or auxiliary tool changes

## Scope (optional)
Add scope after type to indicate the affected module:
- `feat(auth):` — auth module feature
- `fix(ui):` — UI bug fix
- `refactor(api):` — API refactoring

## Footer (optional)
- `Closes #<issue>` — link to resolved issue
- `BREAKING CHANGE: <description>` — mark incompatible changes

## Commit Message Structure
```
<type>: <short summary (max 72 chars)>

ADD:
- <itemized list of additions>
- <each on its own line with dash>

FIX:
- <itemized list of fixes>
- <each on its own line with dash>
```

- Body sections (`ADD:`, `FIX:`) use the English word followed by colon
- Sub-items use dash bullet points, each on its own line
- Summary line uses conventional commit prefix (lowercase, colon + space)