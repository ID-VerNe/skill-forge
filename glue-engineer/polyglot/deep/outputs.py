"""polyglot/deep/outputs.py — Workspace creation, session management, directory handling."""

import json
import os
import time
from datetime import datetime, timezone


def create_workspace(workspace_dir: str):
    """Create the .glue/deep/ directory structure."""
    dirs = [
        workspace_dir,
        os.path.join(workspace_dir, "repos"),
        os.path.join(workspace_dir, "tasks"),
        os.path.join(workspace_dir, "logs"),
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)


def repo_dir(workspace_dir: str, slug: str) -> str:
    return os.path.join(workspace_dir, "repos", slug)


def source_dir(workspace_dir: str, slug: str) -> str:
    return os.path.join(workspace_dir, "repos", slug, "source")


def task_dir(workspace_dir: str) -> str:
    return os.path.join(workspace_dir, "tasks")


def artifact_paths(workspace_dir: str, slug: str) -> dict:
    """Return paths for all required subagent artifacts."""
    rd = repo_dir(workspace_dir, slug)
    return {
        "architecture_md": os.path.join(rd, "architecture.md"),
        "architecture_json": os.path.join(rd, "architecture.json"),
        "source_manifest": os.path.join(rd, "source_manifest.json"),
        "unresolved": os.path.join(rd, "unresolved.md"),
    }


DEFAULT_SESSION = {
    "project": "",
    "requirements": [],
    "target_license": "",
    "candidate_repos": [],
    "created_at": "",
    "workflow": "glue-engineer-v4",
}


def create_session(workspace_dir: str, project: str, requirements: list, target_license: str = ""):
    """Create a new session.json and return it."""
    session = dict(DEFAULT_SESSION)
    session["project"] = project
    session["requirements"] = requirements
    session["target_license"] = target_license
    session["created_at"] = datetime.now(timezone.utc).isoformat()
    session_path = os.path.join(workspace_dir, "session.json")
    with open(session_path, "w", encoding="utf-8") as f:
        json.dump(session, f, indent=2, ensure_ascii=False)
    return session


def load_session(workspace_dir: str) -> dict:
    """Load session.json from workspace."""
    session_path = os.path.join(workspace_dir, "session.json")
    if not os.path.exists(session_path):
        return None
    with open(session_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_session(workspace_dir: str, session: dict):
    """Save session.json."""
    session_path = os.path.join(workspace_dir, "session.json")
    with open(session_path, "w", encoding="utf-8") as f:
        json.dump(session, f, indent=2, ensure_ascii=False)


def add_repo_to_session(workspace_dir: str, session: dict, name: str, url: str, slug: str, local_path: str, commit: str = ""):
    """Add a repo entry to session and save."""
    entry = {
        "name": name,
        "url": url,
        "slug": slug,
        "local_path": local_path,
        "commit": commit,
    }
    # dedup by slug
    session["candidate_repos"] = [r for r in session["candidate_repos"] if r["slug"] != slug]
    session["candidate_repos"].append(entry)
    save_session(workspace_dir, session)
    return entry