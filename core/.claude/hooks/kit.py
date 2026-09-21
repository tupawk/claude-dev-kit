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
    commit-branches             the branch each `git commit` in the hook's command (stdin JSON)
                                would land on: follows `cd`, `git -C` and an earlier checkout

Missing file: one package, profile "" at ".", no exemptions, protected ["main", "master"]. Every
hook that used to assume a single-package project keeps working.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
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


# --- where a commit would land -------------------------------------------------------------
#
# The git safety hook refuses a commit on a protected branch. Which branch is a question about
# the command, not about the session: `git -C ../pack commit` and `cd ../pack && git commit`
# land in another repository, and `git checkout -b x && git commit` lands on a branch that does
# not exist yet when the hook runs. So the command is read the way a shell would read it, far
# enough to follow those three things and no further. Anything this cannot follow falls back to
# the project's own HEAD, which is what the hook checked before it could follow anything.

SEPARATOR_CHARS = set(";&|(){}")
GIT_OPTIONS_WITH_A_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?^\s*\2\s*$", re.S | re.M)
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
LOOKS_LIKE_A_COMMIT = re.compile(r"\bgit\b[^;&|\n]*\bcommit\b(?!-)")
NEWLINE = "\n"
BACKSLASH = "\\"
GIT_TIMEOUT_SECONDS = 10
GIT_BASH_DRIVE = re.compile(r"^/(?:cygdrive/)?([A-Za-z])(?:/|$)")


def run_git(directory: str, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", directory, *args],
            capture_output=True, text=True, check=False, timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def head_branch(directory: str) -> str:
    """The branch checked out in `directory`; "" if it is no repository or HEAD is detached."""
    out = run_git(directory, "symbolic-ref", "--quiet", "--short", "HEAD")
    return out.stdout.strip() if out is not None and out.returncode == 0 else ""


def is_branch(directory: str, name: str) -> bool:
    """Whether `git checkout <name>` there would put HEAD on a branch called `name`."""
    for ref in (f"refs/heads/{name}", f"refs/remotes/origin/{name}"):
        out = run_git(directory, "show-ref", "--verify", "--quiet", ref)
        if out is not None and out.returncode == 0:
            return True
    return False


def newlines_end_commands(command: str) -> str:
    """`command` with each newline outside quotes turned into `;`, and line continuations joined.

    shlex has no notion of a newline ending a command, and a quoted newline (a commit message
    with a body) has to stay inside its word, so the quoting is walked by hand first.
    """
    out: list[str] = []
    quote = ""
    i = 0
    while i < len(command):
        ch = command[i]
        nxt = command[i + 1] if i + 1 < len(command) else ""
        if quote:
            if ch == BACKSLASH and quote == '"' and nxt:
                out.append(ch + nxt)
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in ("'", '"'):
            quote = ch
        elif ch == BACKSLASH and nxt:
            if nxt != NEWLINE:
                out.append(ch + nxt)
            i += 2
            continue
        elif ch == NEWLINE:
            ch = " ; "
        out.append(ch)
        i += 1
    return "".join(out)


def segments(command: str) -> list[list[str]]:
    """The simple commands in `command`, each as its words. Raises ValueError on bad quoting."""
    text = newlines_end_commands(HEREDOC.sub(NEWLINE, command))
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    out: list[list[str]] = [[]]
    for token in lexer:
        if token and set(token) <= SEPARATOR_CHARS:
            out.append([])
        else:
            out[-1].append(token)
    return [words for words in out if words]


def switched_to(args: list[str], directory: str) -> str:
    """The branch a `checkout` or `switch` with these arguments moves HEAD to, or ""."""
    if "--" in args or "--detach" in args:
        return ""
    for flag in ("-b", "-B", "-c", "-C", "--orphan"):
        if flag in args and args.index(flag) + 1 < len(args):
            return args[args.index(flag) + 1]
    names = [a for a in args if not a.startswith("-")]
    return names[0] if names and is_branch(directory, names[0]) else ""


def native_path(path: str) -> str:
    """`path` as this Python spells it. Git Bash writes C:\\Users as /c/Users (Cygwin: /cygdrive/c).

    A command arrives in the shell's spelling and native Windows Python does not know it, so a
    `cd /c/Users/x` looked like a directory that does not exist. Elsewhere this changes nothing.
    """
    drive = GIT_BASH_DRIVE.match(path) if os.name == "nt" else None
    return f"{drive.group(1)}:/{path[drive.end():]}" if drive else path


def resolve_dir(base: str, path: str) -> str | None:
    """`path` as a directory relative to `base`, or None when it cannot be found."""
    target = os.path.normpath(os.path.join(base, os.path.expanduser(native_path(path))))
    return target if os.path.isdir(target) else None


def commit_branches(command: str, project: str) -> list[str]:
    """The branch each `git commit` in `command` would land on, in order."""
    try:
        commands = segments(command)
    except ValueError:
        return [head_branch(project)] if LOOKS_LIKE_A_COMMIT.search(command) else []
    here: str | None = project  # None once a `cd` has gone somewhere this cannot follow
    moved: dict[str, str] = {}  # repository directory -> branch an earlier checkout put it on
    found: list[str] = []
    for words in commands:
        while words and ASSIGNMENT.match(words[0]):
            words = words[1:]
        if words and words[0] in ("command", "exec", "sudo", "time"):
            words = words[1:]
        if not words:
            continue
        if words[0] == "cd":
            here = resolve_dir(here or project, words[1]) if len(words) > 1 else None
            continue
        if os.path.basename(words[0]) not in ("git", "git.exe"):
            continue
        directory, rest = here, words[1:]
        while rest and rest[0].startswith("-"):
            option, rest = rest[0], rest[1:]
            if option == "-C" and rest:
                directory = resolve_dir(directory or project, rest[0])
            if option in GIT_OPTIONS_WITH_A_VALUE and rest:
                rest = rest[1:]
        if not rest:
            continue
        where = directory or project  # a target this cannot follow: judge the project, as before
        if rest[0] in ("checkout", "switch"):
            branch = switched_to(rest[1:], where)
            if branch:
                moved[where] = branch
        elif rest[0] == "commit":
            found.append(moved.get(where) or head_branch(where))
    return found


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
    elif cmd == "commit-branches":
        command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
        for branch in commit_branches(command if isinstance(command, str) else "", os.getcwd()):
            print(branch)
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
