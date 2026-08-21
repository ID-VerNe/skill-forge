"""polyglot/commands/discover.py — `discover` : GitHub repo search entry point.

Pipeline-level command: GitHub repo search is the language-agnostic entry
point (finds repos that ecosystem registries can't, e.g. zig/nim), then
candidates are enriched with ecosystem details (version, downloads,
license) where a matching backend exists.
"""

import json

from polyglot.router import import_backend
from polyglot.common.gh_search import search as gh_search


def add_args(sub):
    p_discover = sub.add_parser("discover", help="Discover GitHub repos by keyword, enriched with ecosystem data")
    p_discover.add_argument("keyword", help="Search keyword")
    p_discover.add_argument("--limit", type=int, default=5)
    p_discover.add_argument("--qualifiers", default="", help="GitHub search qualifiers (e.g. 'stars:>100 language:rust')")
    p_discover.add_argument("--sort", default="", help="GitHub sort key (stars|updated|forks)")
    p_discover.add_argument("--format", choices=["json", "markdown"], default="markdown")
    p_discover.add_argument("--no-enrich", action="store_true", help="Skip ecosystem enrichment")


def cmd_discover(args):
    # Load the candidate repo list from gh
    result = gh_search(args.keyword, limit=args.limit, qualifiers=args.qualifiers, sort=args.sort)

    output = {
        "schema": "polyglot-output-v1",
        "tool": "discover",
        "language": "cross",
        "query": args.keyword,
        "timestamp": result["timestamp"],
        "results": [],
        "errors": list(result["errors"]),
        "metadata": {
            "duration_ms": result["metadata"]["duration_ms"],
            "cache_hit": result["metadata"]["cache_hit"],
            "has_more": result["metadata"]["has_more"],
            "source": "github",
        },
    }

    # Enrichment: route each repo by its language to the matching ecosystem scout
    for repo in result["results"]:
        enriched = dict(repo)
        if not args.no_enrich:
            lang = repo.get("language", "").lower()
            backend_lang = _map_gh_language_to_backend(lang)
            if backend_lang:
                try:
                    mod = import_backend(backend_lang, "scout")
                    # Search by repo name (last segment after /) for ecosystem match
                    pkg_name = repo["name"].split("/")[-1] if "/" in repo["name"] else repo["name"]
                    detail = mod.search(pkg_name, limit=1)
                    if detail and detail.get("results"):
                        d = detail["results"][0]
                        enriched["version"] = d.get("version", "") or enriched["version"]
                        enriched["downloads"] = d.get("downloads", 0) or enriched["downloads"]
                        enriched["registry_url"] = d.get("registry_url", "") or enriched["registry_url"]
                        enriched["license_name"] = d.get("license_name", "") or enriched["license_name"]
                        enriched["dependencies"] = d.get("dependencies", [])
                        enriched["ecosystem_lookup"] = True
                except Exception as e:
                    # Ecosystem lookup is optional enrichment — failures are non-fatal
                    pass
        output["results"].append(enriched)

    if args.format == "json":
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(f"[*] Discover '{args.keyword}' — {len(output['results'])} repos from GitHub:")
        sort_label = args.sort or "relevance"
        print(f"    (source: GitHub repo search | sort: {sort_label})")
        for i, r in enumerate(output["results"], 1):
            lang = r.get("language", "") or "?"
            stars = f"★{r['stars']}" if r.get("stars") else ""
            ver = f"@{r['version']}" if r.get("version") else ""
            print(f"  {i}. {r['name']}{ver} {stars} [{lang}]")
            desc = r.get("description", "")
            if desc:
                print(f"     {desc[:100]}")
            if r.get("ecosystem_lookup"):
                lic = f" | {r['license_name']}" if r.get("license_name") else ""
                print(f"     ecosystem: {r['registry_url']} | downloads={r.get('downloads', 0)}{lic}")
        for e in output["errors"]:
            print(f"  [!] {e[:100]}")


def _map_gh_language_to_backend(lang: str) -> str | None:
    """Map a GitHub repo language to the polyglot backend that can look it up."""
    mapping = {
        "python": "python",
        "javascript": "javascript",
        "typescript": "javascript",
        "js": "javascript",
        "ts": "javascript",
        "rust": "rust",
        "java": "java",
        "kotlin": "kotlin",
        "c": "c_cpp",
        "c++": "c_cpp",
        "c#": "c_cpp",
        "cpp": "c_cpp",
        "go": "go",
        "golang": "go",
    }
    return mapping.get(lang.lower().strip(), None)