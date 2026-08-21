"""
polyglot/common/gh_slug.py — GitHub repo slug parsing from module paths.

Extracts 'owner/repo' from Go module paths (and other format paths)
so star-count lookups can be performed against the GitHub API.
"""

import re


def parse_github_slug(module_path: str) -> str | None:
    """Extract 'owner/repo' from a Go module path if it's on GitHub.

    Examples:
      github.com/gin-gonic/gin              -> gin-gonic/gin
      github.com/gin-gonic/gin/binding      -> gin-gonic/gin
      github.com/gin-gonic/gin/v2           -> gin-gonic/gin
      gopkg.in/gin-gonic/gin.v1             -> gin-gonic/gin
      go.opentelemetry.io/...               -> None
      gitlab.com/...                         -> None
    """
    # Direct github.com path
    m = re.match(r"^github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:/|$|v\d+)", module_path)
    if m:
        slug = m.group(1)
        slug = re.sub(r"\.git$", "", slug)
        return slug

    # gopkg.in -> maps to github.com for many packages
    m = re.match(r"^gopkg\.in/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.v\d+)?$", module_path)
    if m:
        return m.group(1)

    return None


# ── Minimal smoke test ──
if __name__ == "__main__":
    test_paths = [
        "github.com/gin-gonic/gin",
        "github.com/gin-gonic/gin/binding",
        "github.com/gin-gonic/gin/v2",
        "gopkg.in/gin-gonic/gin.v1",
        "go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin",
        "github.com/WeidiDeng/ttyd-go",
    ]
    for p in test_paths:
        s = parse_github_slug(p)
        print(f"  {p:70s} -> {s}")