"""Read the kit's project config, .claude/kit.json, and decide what the guard hooks block.

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

The three guards read the hook's JSON on stdin and print why the call is blocked, or nothing when
it is allowed. They exit 3 when the input cannot be read, and the hook then blocks: a guard that
cannot read its input must not wave the call through.

    guard-bash                  destructive git and shell commands, commits on a protected branch
    guard-secrets               credentials in what an edit writes, writes to .env files
    guard-colours               hex colour literals written into frontend files

Missing file: one package, profile "" at ".", no exemptions, protected ["main", "master"]. Every
hook that used to assume a single-package project keeps working.
"""

from __future__ import annotations

import io
import json
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Iterator

CONFIG = os.path.join(".claude", "kit.json")
DEFAULTS: dict = {
    "packages": [{"profile": "", "path": "."}],
    "design": {"pack": "", "exempt": []},
    "protected_branches": ["main", "master"],
}
BAD_INPUT = 3


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

    A pattern with no wildcard names a file or a directory and matches it and everything under it,
    so "theme", "theme/" and a directory with a dot in its name ("theme.v1") all work.
    """
    pattern = norm(pattern)
    if pattern == ".":
        return re.compile(r"^\.$")
    if "*" not in pattern and "?" not in pattern:
        return re.compile("^" + re.escape(pattern) + "(?:/.*)?$")
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


# --- reading a shell command ---------------------------------------------------------------------
#
# The git safety hook judges commands, not text. A command is split the way a shell would split
# it: heredoc bodies dropped (they are data), newlines and `;`, `&&`, `|` ending a command, quotes
# and backslashes honoured, `( ... )` opening a subshell whose `cd` does not leak out. Shell
# keywords (`if`, `then`, `do`, `!`), assignments and wrappers (`env`, `nice`, `sudo`, `xargs`) are
# stepped over to reach the command they run, and `sh -c '...'`, `bash -c "..."` and `eval` are
# read again from the inside. What cannot be read at all (an unbalanced quote) falls back to the
# old text patterns, so an unreadable command is judged no more leniently than before.

SEPARATOR_CHARS = set(";&|(){}")
GIT_OPTIONS_WITH_A_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1(?P<rest>[^\n]*)\n.*?^\s*\2\s*$", re.S | re.M)
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
LOOKS_LIKE_A_COMMIT = re.compile(r"\bgit\b[^;&|\n]*\bcommit\b(?!-)")
NEWLINE = "\n"
BACKSLASH = "\\"
GIT_TIMEOUT_SECONDS = 10
GIT_BASH_DRIVE = re.compile(r"^/(?:cygdrive/)?([A-Za-z])(?:/|$)")
MAX_NESTING = 4
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
LEADING_KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "time"}
# A wrapper runs the command after it; the set is its options that take a separate value.
WRAPPERS: dict[str, set[str]] = {
    "command": set(), "exec": set(), "nohup": set(), "time": set(), "timeout": {"-s", "-k"},
    "nice": {"-n"}, "env": {"-u", "-C", "-S"}, "sudo": {"-u", "-g", "-h", "-p", "-C"},
    "xargs": {"-I", "-n", "-L", "-P", "-d", "-E", "-s", "-a"},
}
GIT_BUILTINS = set(
    "add am annotate apply archive bisect blame branch bundle cat-file check-attr check-ignore "
    "check-ref-format checkout cherry cherry-pick citool clean clone column commit commit-graph "
    "commit-tree config count-objects credential describe diff diff-files diff-index diff-tree "
    "difftool fast-export fast-import fetch filter-branch for-each-ref format-patch fsck gc grep gui "
    "hash-object help init init-db instaweb interpret-trailers log ls-files ls-remote ls-tree "
    "maintenance merge merge-base mergetool mktag mktree mv name-rev notes pack-refs prune pull push "
    "range-diff read-tree rebase reflog remote repack replace request-pull reset restore rev-list "
    "rev-parse revert rm send-email shortlog show show-branch show-ref sparse-checkout stage stash "
    "status stripspace submodule switch symbolic-ref tag update-index update-ref var verify-commit "
    "verify-tag version whatchanged worktree write-tree".split()
)


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


def drop_heredoc_bodies(command: str) -> str:
    """Remove each heredoc's body and terminator, keeping the rest of the line that opened it.

    `cat <<'EOF' | git commit -F -` keeps `cat | git commit -F -`: the body is data, but the line
    that opened it is still a command.
    """
    return HEREDOC.sub(lambda m: m.group("rest"), command)


def parse_commands(command: str, scope: tuple[int, ...], ids: list[int]) -> list[tuple[tuple[int, ...], list[str]]]:
    """The simple commands in `command` with the subshells each runs in. ValueError on bad quoting."""
    lexer = shlex.shlex(newlines_end_commands(drop_heredoc_bodies(command)), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    stack = list(scope)
    out: list[tuple[tuple[int, ...], list[str]]] = []
    words: list[str] = []
    for token in lexer:
        if not (token and set(token) <= SEPARATOR_CHARS):
            words.append(token)
            continue
        if words:
            out.append((tuple(stack), words))
            words = []
        for ch in token:
            if ch == "(":
                ids[0] += 1
                stack.append(ids[0])
            elif ch == ")" and len(stack) > len(scope):
                stack.pop()
    if words:
        out.append((tuple(stack), words))
    return out


def segments(command: str) -> list[list[str]]:
    """The simple commands in `command`, each as its words. Raises ValueError on bad quoting."""
    return [words for _, words in parse_commands(command, (), [0])]


def simple_command(words: list[str]) -> list[str]:
    """`words` without leading keywords, assignments and wrappers: the command that actually runs."""
    i = 0
    while i < len(words):
        word = words[i]
        if ASSIGNMENT.match(word) or word in LEADING_KEYWORDS:
            i += 1
            continue
        name = os.path.basename(word)
        if name not in WRAPPERS:
            break
        i += 1
        while i < len(words) and (words[i].startswith("-") or (name == "env" and ASSIGNMENT.match(words[i]))):
            option = words[i]
            i += 1
            if option in WRAPPERS[name] and i < len(words):
                i += 1
        if name == "timeout" and i < len(words):
            i += 1  # the duration
    return words[i:]


def walk(command: str, scope: tuple[int, ...] = (), ids: list[int] | None = None, depth: int = 0) -> Iterator[tuple[tuple[int, ...], list[str]]]:
    """(subshells, words) for each command `command` runs, reading `sh -c` and `eval` from the inside."""
    ids = ids if ids is not None else [0]
    for where, raw in parse_commands(command, scope, ids):
        words = simple_command(raw)
        if not words:
            continue
        name = os.path.basename(words[0])
        if depth < MAX_NESTING and name in SHELLS:
            flag = next((i for i, w in enumerate(words[1:], 1) if re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", w)), 0)
            if flag and flag + 1 < len(words):
                ids[0] += 1
                yield from walk(words[flag + 1], where + (ids[0],), ids, depth + 1)
                continue
        if depth < MAX_NESTING and name == "eval":
            yield from walk(" ".join(words[1:]), where, ids, depth + 1)
            continue
        yield where, words


def split_args(args: list[str]) -> tuple[set[str], set[str], list[str]]:
    """Long options, the letters of short options (`-uf` gives u and f) and the positional words."""
    longs: set[str] = set()
    shorts: set[str] = set()
    positional: list[str] = []
    rest_positional = False
    for a in args:
        if rest_positional or a == "-" or not a.startswith("-"):
            positional.append(a)
        elif a == "--":
            rest_positional = True
        elif a.startswith("--"):
            longs.add(a.split("=", 1)[0])
        else:
            shorts.update(a[1:])
    return longs, shorts, positional


def switched_to(args: list[str], directory: str) -> str | None:
    """The branch a `checkout` or `switch` moves HEAD to; "" when HEAD stays, None when unknowable."""
    if "--" in args or "--detach" in args:
        return ""
    for flag in ("-b", "-B", "-c", "-C", "--orphan"):
        if flag in args and args.index(flag) + 1 < len(args):
            return args[args.index(flag) + 1]
    names = [a for a in args if a == "-" or not a.startswith("-")]
    if not names:
        return ""
    if names[0] == "-":
        return None  # the previous branch: somewhere, but not somewhere this can name
    return names[0] if is_branch(directory, names[0]) else ""


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


def scoped(values: dict[tuple[int, ...], str | None], scope: tuple[int, ...]) -> str | None:
    """The value set in `scope` or the nearest subshell around it."""
    for k in range(len(scope), -1, -1):
        if scope[:k] in values:
            return values[scope[:k]]
    return None


def git_target(here: str | None, args: list[str], project: str) -> tuple[str | None, list[str]]:
    """The directory a git invocation works in and its words from the subcommand on."""
    directory, rest = here, args
    while rest and rest[0].startswith("-"):
        option, rest = rest[0], rest[1:]
        if option == "-C" and rest:
            directory = resolve_dir(directory or project, rest[0])
        if option in GIT_OPTIONS_WITH_A_VALUE and rest:
            rest = rest[1:]
    return directory, rest


def expand_alias(directory: str, rest: list[str]) -> list[str]:
    """`rest` with a git alias in front replaced by what it stands for; a shell alias becomes ["!", text]."""
    if not rest or rest[0] in GIT_BUILTINS:
        return rest
    out = run_git(directory, "config", "--get", f"alias.{rest[0]}")
    value = out.stdout.strip() if out is not None and out.returncode == 0 else ""
    if not value:
        return rest
    if value.startswith("!"):
        return ["!", value[1:], *rest[1:]]
    try:
        return shlex.split(value) + rest[1:]
    except ValueError:
        return rest


DISCARD_ALL = {".", "./", ":/", ":/*", "*"}
ROOT_TARGETS = {"/", "~", "$HOME", "${HOME}", "..", ".", "/*", "~/*", "$HOME/*", "${HOME}/*", "../*"}
DRIVE_ROOT = re.compile(r"[A-Za-z]:[\\/]?|/[A-Za-z]|/cygdrive/[A-Za-z]")


def protected_ref(word: str, protected: list[str]) -> str:
    """The protected branch `word` names (`main`, `refs/heads/main`), or ""."""
    name = word.removeprefix("refs/heads/")
    return name if name in protected else ""


def git_danger(sub: str, args: list[str], protected: list[str]) -> str:
    """Why this git subcommand is refused, or ""."""
    longs, shorts, positional = split_args(args)
    if sub == "push":
        if longs & {"--force", "--force-with-lease", "--force-if-includes"} or "f" in shorts:
            return "force push"
        if any(p.startswith("+") for p in positional):
            return "force push"
        deleting = "--delete" in longs or "d" in shorts
        for p in positional[1:] if positional else []:
            target = protected_ref(p[1:], protected) if p.startswith(":") else (protected_ref(p, protected) if deleting else "")
            if target:
                return f"deleting {target}"
    elif sub == "branch":
        if "--delete" in longs or shorts & {"d", "D"}:
            for p in positional:
                if protected_ref(p, protected):
                    return f"deleting {protected_ref(p, protected)}"
    elif sub == "reset":
        if "--hard" in longs:
            return "git reset --hard"
    elif sub == "checkout":
        if any(p in DISCARD_ALL for p in positional):
            return "discarding all working changes"
    elif sub == "restore":
        staged_only = ("--staged" in longs or "S" in shorts) and not ("--worktree" in longs or "W" in shorts)
        if not staged_only and any(p in DISCARD_ALL for p in positional):
            return "discarding all working changes"
    elif sub == "clean":
        dry_run = "--dry-run" in longs or "n" in shorts
        if ("--force" in longs or "f" in shorts) and not dry_run:
            return "git clean -f"
    elif sub == "rebase":
        if "--interactive" in longs or "i" in shorts:
            return "interactive rebase (do it manually if needed)"
    return ""


def rm_danger(args: list[str]) -> str:
    longs, shorts, positional = split_args(args)
    if not ("--recursive" in longs or shorts & {"r", "R"}):
        return ""
    for target in positional:
        bare = target.rstrip("/") or "/"
        if bare in ROOT_TARGETS or DRIVE_ROOT.fullmatch(bare):
            return "recursive delete of a root, home, or parent directory"
    return ""


LEGACY_PATTERNS = [
    (re.compile(r"git\s+push\b.*\s(--force\S*|-f\b|\+\S+)"), "force push"),
    (re.compile(r"git\s+reset\s+--hard"), "git reset --hard"),
    (re.compile(r"git\s+checkout\s+--\s+\."), "discarding all working changes"),
    (re.compile(r"git\s+clean\s+-[a-zA-Z]*f"), "git clean -f"),
    (re.compile(r"git\s+rebase\s+.*(\s-i\b|--interactive)"), "interactive rebase (do it manually if needed)"),
    (re.compile(r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(/|~|\$HOME|\.\.)(\s|$)"), "recursive delete of a root, home, or parent directory"),
]


def check_bash(command: str, project: str, protected: list[str], depth: int = 0) -> str:
    """Why `command` is refused, or "". Commits are judged on the branch they will land on."""
    try:
        commands = list(walk(command))
    except ValueError:
        for pattern, reason in LEGACY_PATTERNS:
            if pattern.search(command):
                return reason
        branch = head_branch(project) if LOOKS_LIKE_A_COMMIT.search(command) else ""
        return f"committing directly to {branch}. Create a feature branch first" if branch in protected else ""
    heres: dict[tuple[int, ...], str | None] = {(): project}
    moved: dict[str, str] = {}  # repository directory -> branch an earlier checkout put it on
    for scope, words in commands:
        here = scoped(heres, scope)
        name = os.path.basename(words[0])
        if name in ("cd", "pushd"):
            heres[scope] = resolve_dir(here or project, words[1]) if len(words) > 1 else None
            continue
        if name == "rm":
            reason = rm_danger(words[1:])
            if reason:
                return reason
            continue
        if name not in ("git", "git.exe"):
            continue
        directory, rest = git_target(here, words[1:], project)
        where = directory or project  # a target this cannot follow: judge the project, as before
        rest = expand_alias(where, rest)
        if not rest:
            continue
        if rest[0] == "!" and len(rest) > 1 and depth < MAX_NESTING:
            reason = check_bash(rest[1], where, protected, depth + 1)
            if reason:
                return reason
            continue
        sub, args = rest[0], rest[1:]
        reason = git_danger(sub, args, protected)
        if reason:
            return reason
        if sub in ("checkout", "switch"):
            switched = switched_to(args, where)
            if switched is None:
                moved.pop(where, None)
            elif switched:
                moved[where] = switched
        elif sub == "commit":
            branch = moved.get(where) or head_branch(where)
            if branch in protected:
                return f"committing directly to {branch}. Create a feature branch first"
    return ""


def commit_branches(command: str, project: str) -> list[str]:
    """The branch each `git commit` in `command` would land on, in order."""
    found: list[str] = []
    try:
        commands = list(walk(command))
    except ValueError:
        return [head_branch(project)] if LOOKS_LIKE_A_COMMIT.search(command) else []
    heres: dict[tuple[int, ...], str | None] = {(): project}
    moved: dict[str, str] = {}
    for scope, words in commands:
        here = scoped(heres, scope)
        if words[0] in ("cd", "pushd"):
            heres[scope] = resolve_dir(here or project, words[1]) if len(words) > 1 else None
            continue
        if os.path.basename(words[0]) not in ("git", "git.exe"):
            continue
        directory, rest = git_target(here, words[1:], project)
        where = directory or project
        rest = expand_alias(where, rest)
        if not rest:
            continue
        if rest[0] in ("checkout", "switch"):
            switched = switched_to(rest[1:], where)
            if switched is None:
                moved.pop(where, None)
            elif switched:
                moved[where] = switched
        elif rest[0] == "commit":
            found.append(moved.get(where) or head_branch(where))
    return found


# --- what an edit writes -------------------------------------------------------------------------
#
# Edit, Write, MultiEdit and NotebookEdit put text in different fields: content, new_string,
# edits[].new_string, new_source. Every string in the tool input is read except the ones that are
# not written (the text being replaced, and the path), so a new tool or field is scanned by default.

NOT_WRITTEN = {"old_string", "file_path", "notebook_path", "cell_id", "cell_type", "edit_mode"}
TEXT_FIELDS = ("content", "new_string", "new_source")


def written_text(tool_input: object, key: str = "") -> list[str]:
    if isinstance(tool_input, str):
        return [] if key in NOT_WRITTEN else [tool_input]
    if isinstance(tool_input, dict):
        return [s for k, v in tool_input.items() for s in written_text(v, k)]
    if isinstance(tool_input, list):
        return [s for v in tool_input for s in written_text(v, key)]
    return []


def target_path(tool_input: dict) -> str:
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    return path if isinstance(path, str) else ""


SECRET_PATTERNS = [
    ("AWS access key pattern", re.compile(r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED |PGP )?PRIVATE KEY(?: BLOCK)?-----")),
    ("Stripe secret key", re.compile(r"(?<![A-Za-z0-9])[sr]k_live_[A-Za-z0-9]{16,}")),
    # A digit somewhere in the key: real keys have them, CSS class names like task-management-x do not.
    ("API secret key pattern", re.compile(r"(?<![A-Za-z0-9_-])sk-(?:ant-|proj-|live_|test_)?(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{20,}")),
    ("GitHub token", re.compile(r"(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("Slack token", re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{35}")),
]
# A credential-named key assigned a quoted value of 12+ characters with no spaces (prose has spaces)
# and no $, < or { (templates and placeholders). JSON's quoted key is allowed before the colon.
CREDENTIAL = re.compile(
    r"""\b(password|passwd|client[_-]?secret|secret|api[_-]?key|access[_-]?token|auth[_-]?token|token)["']?"""
    r"""\s*[:=]\s*(["'])([^"'\s$<{]{12,})\2""",
    re.I,
)
PLACEHOLDER = re.compile(r"example|placeholder|changeme|change[_-]me|your[_-]|dummy|xxxx|redacted|fake", re.I)


def env_file(path: str) -> bool:
    name = path.replace(BACKSLASH, "/").rsplit("/", 1)[-1]
    return name != ".env.example" and (name == ".env" or name.startswith(".env.") or name.endswith(".env"))


def check_secrets(tool_input: dict) -> str:
    """Why this edit is refused by the secrets hook, or ""."""
    path = target_path(tool_input)
    if env_file(path):
        return f"writing to {path}"
    for text in written_text(tool_input):
        for name, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                return name
        for m in CREDENTIAL.finditer(text):
            if not PLACEHOLDER.search(m.group(3)):
                return "hardcoded credential assignment"
    return ""


HEX_COLOUR = re.compile(r"(?<![\w&])#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])")
URL_ATTRIBUTE = re.compile(r"""(?:href|src|action|xlink:href)\s*=\s*["']?\s*$""", re.I)
CSS_VALUE = re.compile(r"[A-Za-z-]+\s*:\s*[^;{}]*$")
COMMENT_START = ("//", "/*", "*", "<!--", "#")
COLOUR_CONTEXT = set(":,(=\"'")
COLOUR_SCOPE_EXT = (".css", ".scss", ".tsx", ".jsx", ".vue", ".svelte", ".html")
COLOUR_SCOPE_DIRS = ("src/components/", "src/app/", "src/pages/", "src/ui/", "templates/")
MAX_HITS_SHOWN = 6


def is_colour(line: str, m: re.Match[str]) -> bool:
    """Whether a `#xxx` match is a colour. An anchor (`href="#add"`) is not; an all-digit short one
    (`#123`, `#1001`) is an issue or order number unless it sits where a CSS value goes."""
    before = line[: m.start()]
    if URL_ATTRIBUTE.search(before):
        return False
    digits = m.group(1)
    if len(digits) > 4 or not digits.isdigit():
        return True
    if before.rstrip()[-1:] in COLOUR_CONTEXT:
        return True
    return bool(CSS_VALUE.search(before)) and not before.lstrip().startswith(COMMENT_START)


def colour_in_scope(cfg: dict, relpath: str) -> bool:
    low = relpath.lower()
    if low.startswith(("design/", ".claude/", "node_modules/")) or "/node_modules/" in low:
        return False
    if low.endswith(".svg") or design_exempt(cfg, relpath):
        return False
    return low.endswith(COLOUR_SCOPE_EXT) or any(low.startswith(d) or "/" + d in low for d in COLOUR_SCOPE_DIRS)


def check_colours(tool_input: dict, cfg: dict) -> str:
    """Why this edit is refused by the design-token hook (the file and the lines), or ""."""
    path = target_path(tool_input)
    if not path:
        return ""
    relpath = rel(path)
    if not colour_in_scope(cfg, relpath):
        return ""
    hits: list[str] = []
    for text in written_text(tool_input):
        for n, line in enumerate(text.splitlines(), 1):
            if "brand-exception:" not in line and any(is_colour(line, m) for m in HEX_COLOUR.finditer(line)):
                hits.append(f"  line {n}: {line.strip()[:110]}")
    if not hits:
        return ""
    more = [f"  ... and {len(hits) - MAX_HITS_SHOWN} more"] if len(hits) > MAX_HITS_SHOWN else []
    return "\n".join([f"hardcoded colour in {relpath}.", *hits[:MAX_HITS_SHOWN], *more])


def read_tool_input() -> dict:
    """The hook's tool_input. Exits BAD_INPUT when it is not an object or a text field is not text."""
    try:
        tool_input = json.load(sys.stdin).get("tool_input")
    except (ValueError, AttributeError):
        sys.exit(BAD_INPUT)
    if not isinstance(tool_input, dict):
        sys.exit(BAD_INPUT)
    for key in (*TEXT_FIELDS, "command"):
        if tool_input.get(key) is not None and not isinstance(tool_input[key], str):
            sys.exit(BAD_INPUT)
    return tool_input


def main(argv: list[str]) -> int:
    # Hook payloads are UTF-8 whatever the Windows code page says, and a Windows Python must not emit
    # CRLF here: bash `read` keeps a trailing \r, and a package path ending in \r does not exist.
    for stream, newline in ((sys.stdin, None), (sys.stdout, "\n")):
        if isinstance(stream, io.TextIOWrapper):  # a test may swap in a StringIO
            stream.reconfigure(encoding="utf-8", errors="replace", newline=newline)
    if not argv:
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]
    cfg = load()
    protected = [b for b in cfg.get("protected_branches", []) if b]
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
        for b in protected:
            print(b)
    elif cmd == "rel":
        print(rel(args[0]))
    elif cmd == "commit-branches":
        command = read_tool_input().get("command") or ""
        for branch in commit_branches(command, os.getcwd()):
            print(branch)
    elif cmd == "tool-input":
        data = json.load(sys.stdin)
        value = data.get("tool_input", {}).get(args[0], "")
        print(value if isinstance(value, str) else json.dumps(value))
    elif cmd == "guard-bash":
        reason = check_bash(read_tool_input().get("command") or "", os.getcwd(), protected)
        if reason:
            print(reason)
    elif cmd == "guard-secrets":
        reason = check_secrets(read_tool_input())
        if reason:
            print(reason)
    elif cmd == "guard-colours":
        reason = check_colours(read_tool_input(), cfg)
        if reason:
            print(reason)
    else:
        print(f"kit.py: unknown command {cmd}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
