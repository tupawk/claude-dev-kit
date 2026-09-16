"""Read the kit's project config, .claude/kit.json, for the hooks and the assembly script.

The file is project-owned: new-project.sh writes it once and never overwrites it. Shape:

    {
      "packages": [ { "profile": "python", "path": "workers/agent" }, ... ],
      "design":   { "pack": "../my-design", "exempt": ["theme/**", "vendor/*.css"] },
      "protected_branches": ["main", "master"]
    }

Subcommands (all print to stdout, one value per line):

    packages                    "<profile>\\t<path>" for every package
    package-for <relpath>       the package whose path is the longest prefix of relpath, same format
    design-exempt <relpath>     "yes" if a design.exempt glob matches, else "no"
    protected-branches          the branches commits are refused on
    rel <path>                  path relative to the project root, forward slashes
    tool-input <field>          that field of the hook's tool_input, read from stdin JSON

Missing file: one package, profile "" at ".", no exemptions, protected ["main", "master"]. Every
hook that used to assume a single-package project keeps working.
"""

from __future__ import annotations

import json
import os
import re
import sys

CONFIG = os.path.join(".claude", "kit.json")
DEFAULTS: dict = {
    "packages": [{"profile": "", "path": "."}],
    "design": {"pack": "", "exempt": []},
    "protected_branches": ["main", "master"],
}


def load() -> dict:
    if not os.path.exists(CONFIG):
        return DEFAULTS
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    out = dict(DEFAULTS)
    out.update(cfg)
    out["design"] = {**DEFAULTS["design"], **cfg.get("design", {})}
    return out


def norm(path: str) -> str:
    path = path.replace(os.sep, "/").strip("/")
    return path or "."


def rel(path: str) -> str:
    if not path:
        return ""
    try:
        return os.path.relpath(os.path.realpath(path), os.path.realpath(os.getcwd())).replace(os.sep, "/")
    except ValueError:  # a different drive on Windows
        return path.replace(os.sep, "/")


def packages(cfg: dict) -> list[tuple[str, str]]:
    return [(p.get("profile", ""), norm(p.get("path", "."))) for p in cfg["packages"]]


def package_for(cfg: dict, relpath: str) -> tuple[str, str] | None:
    """The package owning relpath: the one with the longest path prefix; "." matches everything."""
    relpath = norm(relpath)
    best: tuple[str, str] | None = None
    for profile, path in packages(cfg):
        if path == "." or relpath == path or relpath.startswith(path + "/"):
            depth = 0 if path == "." else len(path)
            if best is None or depth > (0 if best[1] == "." else len(best[1])):
                best = (profile, path)
    return best


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a path glob to a regex. ** spans directories, * and ? stay inside one segment.
    A pattern that names a directory ("theme/" or "theme") matches everything under it."""
    pattern = norm(pattern)
    looks_like_dir = "*" not in pattern and "?" not in pattern and "." not in os.path.basename(pattern)
    if looks_like_dir and pattern != ".":
        pattern += "/**"
    out = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
            continue
        if pattern.startswith("**", i):
            out += ".*"
            i += 2
            continue
        ch = pattern[i]
        if ch == "*":
            out += "[^/]*"
        elif ch == "?":
            out += "[^/]"
        else:
            out += re.escape(ch)
        i += 1
    return re.compile("^" + out + "$")


def design_exempt(cfg: dict, relpath: str) -> bool:
    relpath = norm(relpath)
    return any(glob_to_regex(g).match(relpath) for g in cfg["design"].get("exempt", []))


def main(argv: list[str]) -> int:
    # Bash `read` keeps a trailing \r, so a Windows Python must not emit CRLF here: a package path
    # ending in \r is a directory that does not exist.
    sys.stdout.reconfigure(newline="\n")
    if not argv:
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]
    cfg = load()
    if cmd == "packages":
        for profile, path in packages(cfg):
            print(f"{profile}\t{path}")
    elif cmd == "package-for":
        hit = package_for(cfg, args[0])
        if hit:
            print(f"{hit[0]}\t{hit[1]}")
    elif cmd == "design-exempt":
        print("yes" if design_exempt(cfg, args[0]) else "no")
    elif cmd == "protected-branches":
        for b in cfg["protected_branches"]:
            print(b)
    elif cmd == "rel":
        print(rel(args[0]))
    elif cmd == "tool-input":
        data = json.load(sys.stdin)
        value = data.get("tool_input", {}).get(args[0], "")
        print(value if isinstance(value, str) else json.dumps(value))
    else:
        print(f"kit.py: unknown command {cmd}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
