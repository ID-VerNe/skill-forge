# Custom Team Guide

You can create your own team in `teams/custom/` and the skill will automatically discover it.

## How to create a custom team

1. Create a folder: `teams/custom/<your-team-name>/`
2. Create `team.json` with the team metadata and agent list
3. Create one `.md` file per agent with their full prompt

## team.json format

```json
{
  "schema": "multi-lens-team-v1",
  "name": "my-team",
  "version": "1.0.0",
  "description": "Describe what this team is for",
  "scenario": ["keyword1", "keyword2"],
  "agents": [
    { "slug": "agent-one", "label": "Agent One", "phase": 1 },
    { "slug": "agent-two", "label": "Agent Two", "phase": 1 }
  ]
}
```

The `scenario` array contains keywords that the skill uses to match user input to your team.

## Agent file format

Each agent file has frontmatter and a full prompt:

```markdown
---
role: agent-one
team: my-team
phase: 1
---

You are an [AGENT NAME].

From your perspective, analyze the following:

[TOPIC]

Produce:
1. ...
2. ...
```

## Output directory

When your custom team runs, outputs go to `outputs/<your-team-name>/<agent-slug>.md` in the user's current working directory (the directory where they launched the conversation, not the skill directory).