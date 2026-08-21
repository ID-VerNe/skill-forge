"""polyglot/commands/deep.py — deep-init / deep-pack / deep-validate / deep-compare / deep-summarize / deep-clean."""

import os
import sys
import shutil


def add_args(sub):
    p_deep_init = sub.add_parser("deep-init", help="Create deep analysis workspace")
    p_deep_init.add_argument("--dir", default=".glue/deep",
                            help="Workspace directory (default: .glue/deep)")
    p_deep_init.add_argument("--project", required=True, help="Project name")
    p_deep_init.add_argument("--requirements", nargs="+", default=[],
                            help="Structured requirement descriptions")
    p_deep_init.add_argument("--target-license", default="", help="Target license")
    p_deep_init.add_argument("--repos", nargs="+", required=True,
                            help="Repository URLs to analyze")

    p_deep_pack = sub.add_parser("deep-pack", help="Generate subagent task prompts")
    p_deep_pack.add_argument("--dir", default=".glue/deep",
                            help="Workspace directory (default: .glue/deep)")

    p_deep_val = sub.add_parser("deep-validate", help="Validate subagent architecture outputs")
    p_deep_val.add_argument("--dir", default=".glue/deep",
                           help="Workspace directory (default: .glue/deep)")
    p_deep_val.add_argument("--include-reuse-map", action="store_true",
                           help="Also validate reuse-map artifacts (Phase 3)")

    p_deep_comp = sub.add_parser("deep-compare", help="Compare multiple repo architecture reports")
    p_deep_comp.add_argument("--dir", default=".glue/deep",
                            help="Workspace directory (default: .glue/deep)")

    p_deep_summ = sub.add_parser("deep-summarize", help="Generate final report draft")
    p_deep_summ.add_argument("--dir", default=".glue/deep",
                            help="Workspace directory (default: .glue/deep)")

    p_deep_clean = sub.add_parser("deep-clean", help="Clean cloned repos but keep reports")
    p_deep_clean.add_argument("--dir", default=".glue/deep",
                             help="Workspace directory (default: .glue/deep)")
    p_deep_clean.add_argument("--all", action="store_true",
                             help="Also clean logs/ and tasks/")
    p_deep_clean.add_argument("--force", "-f", action="store_true",
                             help="Skip confirmation prompt")


def cmd_deep_init(args):
    """Create deep analysis workspace with cloned repos."""
    from polyglot.deep.outputs import create_workspace, create_session, add_repo_to_session, repo_dir
    from polyglot.deep.repo_resolver import url_to_slug, resolve_repo_url, clone_repo

    workspace = os.path.abspath(args.dir)
    create_workspace(workspace)

    session = create_session(
        workspace,
        project=args.project,
        requirements=args.requirements,
        target_license=args.target_license or "",
    )

    success_count = 0
    fail_count = 0

    for url in args.repos:
        slug = url_to_slug(url)
        rd = repo_dir(workspace, slug)
        src = os.path.join(rd, "source")

        print(f"[v] Cloning {url} → {src}")
        result = clone_repo(resolve_repo_url(url), src)

        if result["success"]:
            add_repo_to_session(
                workspace, session,
                name=slug, url=url, slug=slug,
                local_path=src, commit=result["commit"],
            )
            print(f"    commit: {result['commit'][:12]}")
            success_count += 1
        else:
            print(f"    [!] Clone failed: {result['error'][:120]}")
            fail_count += 1

    if success_count == 0 and fail_count > 0:
        print(f"\n[x] All {fail_count} clones failed — workspace is incomplete")
        sys.exit(1)

    print(f"\n[v] Workspace ready: {workspace}")
    print(f"    {len(session['candidate_repos'])} repos, {len(session['requirements'])} requirements")


def cmd_deep_pack(args):
    """Generate task prompt files for subagents."""
    from polyglot.deep.packager import generate_tasks
    workspace = os.path.abspath(args.dir)
    tasks = generate_tasks(workspace)
    if not tasks:
        print("[!] No tasks generated — check session.json has candidate_repos")
        return
    for slug, path in tasks:
        print(f"[v] {slug}: {path}")


def cmd_deep_validate(args):
    """Validate subagent architecture outputs."""
    from polyglot.deep.validator import main as validate_main
    workspace = os.path.abspath(args.dir)
    exit_code = validate_main(workspace, include_reuse_map=args.include_reuse_map)
    sys.exit(exit_code)


def cmd_deep_compare(args):
    """Structured comparison of multiple repo architecture reports."""
    from polyglot.deep.comparer import main as compare_main
    workspace = os.path.abspath(args.dir)
    exit_code = compare_main(workspace)
    sys.exit(exit_code)


def cmd_deep_summarize(args):
    """Generate final report draft from architecture reports."""
    from polyglot.deep.summarizer import main as summarize_main
    workspace = os.path.abspath(args.dir)
    exit_code = summarize_main(workspace)
    sys.exit(exit_code)


def cmd_deep_clean(args):
    """Clean cloned repos but keep reports."""
    import shutil
    from polyglot.deep.outputs import load_session, repo_dir

    workspace = os.path.abspath(args.dir)

    if not os.path.isdir(workspace):
        print(f"[x] Workspace directory not found: {workspace}")
        sys.exit(1)

    # Confirm before destructive action
    if not getattr(args, "force", False):
        print(f"[!] This will remove cloned source files from: {workspace}")
        print(f"    Architecture reports and JSON artifacts will be preserved.")
        try:
            confirm = input("    Continue? [y/N]: ").strip().lower()
            if confirm not in ("y", "yes"):
                print("[v] Cancelled.")
                return 0
        except EOFError:
            print("[v] Non-interactive mode — aborting for safety. Use --force to skip confirmation.")
            return 0

    session = load_session(workspace)

    if not session:
        # No session.json — try cleaning repos/ directory directly
        repos_dir = os.path.join(workspace, "repos")
        if os.path.exists(repos_dir):
            removed = 0
            for entry in os.listdir(repos_dir):
                src = os.path.join(repos_dir, entry, "source")
                if os.path.exists(src):
                    shutil.rmtree(src, ignore_errors=True)
                    removed += 1
                    print(f"[v] Removed source: {entry}")
            if removed == 0:
                print("[!] No source directories found under repos/")
            else:
                print(f"\n[v] Cleaned {removed} repo source directories")
        else:
            print("[x] No session.json and no repos/ directory found — nothing to clean")
        return

    removed = 0
    for repo in session.get("candidate_repos", []):
        slug = repo["slug"]
        src = os.path.join(repo_dir(workspace, slug), "source")
        if os.path.exists(src):
            shutil.rmtree(src, ignore_errors=True)
            removed += 1
            print(f"[v] Removed source: {slug}")

    print(f"\n[v] Cleaned {removed} repo source directories")
    if args.all:
        logs_dir = os.path.join(workspace, "logs")
        if os.path.exists(logs_dir):
            shutil.rmtree(logs_dir, ignore_errors=True)
            print("[v] Removed logs/")
        tasks_dir = os.path.join(workspace, "tasks")
        if os.path.exists(tasks_dir):
            shutil.rmtree(tasks_dir, ignore_errors=True)
            print("[v] Removed tasks/")