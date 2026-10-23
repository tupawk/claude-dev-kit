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

For the Stop hook (see "the Stop hook's test runs" below):

    stop-run <profile> <path> <scope> <deadline> <bash> <hook>
                                run one package's profile stop hook: one run at a time, skipped when
                                this tree was already proven green, killed with its children at the
                                deadline (epoch seconds). Exits as the hook did, or 124 out of time
    lf-files                    the files holding a failure in pytest's last-failed record, dropping
                                entries whose file is gone; exits 1 when there is no record here
    lf-passed <path>...         drop the record's entries under these paths after a green run

The three guards read the hook's JSON on stdin and print why the call is blocked, or nothing when
it is allowed. They exit 3 when the input cannot be read, and the hook then blocks: a guard that
cannot read its input must not wave the call through.

    guard-bash                  destructive git and shell commands, commits on a protected branch,
                                judged where the command runs: the payload's `cwd`, then `cd`,
                                `git -C` and an earlier checkout
    guard-secrets               credentials in what an edit writes, writes to .env files
    guard-colours               hex colour literals written into frontend files

Missing file: one package, profile "" at ".", no exemptions, protected ["main", "master"]. Every
hook that used to assume a single-package project keeps working.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
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
# The git safety hook judges commands, not text. A command is read the way a shell reads it, in one
# linear pass (prepare): a comment only where a word starts, quotes, escapes and ANSI-C `$'...'`
# honoured, newlines ending a command, `((...))` arithmetic left alone. Heredoc and here-string bodies
# are data: they are read as commands only when a bare shell in the command reads its standard input
# (`| bash`, `sh <<EOF`, `. /dev/stdin`), but the substitutions inside an unquoted heredoc run and are
# read. The body of each `$(...)`, backtick and `<(...)`, inside double quotes too, is found with the
# same reader (so a heredoc or a `)` inside one does not end it early) and read as commands of its own;
# where its output becomes code (`eval`, `bash -c`, `source <(...)`), what it emits is read as commands
# too. Then shlex splits the rest into words, `( ... )` opening a subshell whose `cd` does not leak out.
# Shell keywords, assignments and wrappers (`env`, `nice`, `sudo`, `xargs`, `stdbuf`, `winpty`) are
# stepped over to reach the command they run, and `sh -c`, `eval`, `find -exec`, `git submodule foreach`,
# `git rebase -x`, interpreter one-liners and git aliases are read from the inside.
#
# Where the reader cannot be sure, it refuses rather than guesses: nesting past MAX_NESTING, a command
# longer than MAX_TEXT once heredoc bodies are dropped, more than MAX_GIT_CALLS git look-ups, and a line
# that cannot be split at all and mentions a dangerous git or rm command. Nothing is judged more
# leniently than the old text patterns judged it.

SEPARATOR_CHARS = set(";&|(){}")
OPERATOR_CHARS = set(" \t\r\n;&|()<>")
GIT_OPTIONS_WITH_A_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
GIT_OPTIONS_THAT_MOVE_THE_REPOSITORY = {"--git-dir", "--work-tree"}
GIT_REPOSITORY_VARIABLE = re.compile(r"(GIT_DIR|GIT_WORK_TREE|GIT_COMMON_DIR)(=|$)")
# What walk yields in place of a command that aims git somewhere `cd` and `git -C` do not say.
GIT_ELSEWHERE = "\x02git-elsewhere"
CD_OPTIONS = {"-L", "-P", "-e", "-@"}  # how the path is resolved; the directory still changes
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
LOOKS_LIKE_A_COMMIT = re.compile(r"\bgit\b[^;&|\n]*\bcommit\b(?!-)")
MARK = "\x01"  # brackets the index of a substitution in prepared text: \x01<n>\x01
MARKS = re.compile("\x01(\\d+)\x01")
NEWLINE = "\n"
BACKSLASH = "\\"
GIT_TIMEOUT_SECONDS = 10
DETACHED_HEAD = 1  # `git symbolic-ref --quiet HEAD` exits 1 on a detached HEAD, 128 outside a repository
# A commit the hook cannot place is refused: a guard that cannot tell where a commit lands must not
# wave it through, and judging the project instead let one through whenever the project was elsewhere.
UNKNOWN_TARGET = (
    "could not work out which branch this commit lands on (for example a directory that cannot be "
    "found, a variable, `cd -`, `--git-dir`, `GIT_DIR`, or no repository git could read there). Run it "
    "from that repository with a literal path, or use `git -C <path> commit`"
)
GIT_BASH_DRIVE = re.compile(r"^/(?:cygdrive/)?([A-Za-z])(?:/|$)")
MAX_NESTING = 4
MAX_READER_DEPTH = 32  # substitutions inside substitutions
MAX_SUBSHELLS = 64
MAX_TEXT = 100_000
MAX_GIT_CALLS = 40
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
STDIN_SCRIPTS = {"/dev/stdin", "-", "/proc/self/fd/0"}
SHELL_OPTIONS_WITH_A_VALUE = {"-o", "-O", "+o", "+O", "--rcfile", "--init-file"}
LEADING_KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "time", "coproc"}
# A wrapper runs the command after it; the set is its options that take a separate value.
WRAPPERS: dict[str, set[str]] = {
    "command": set(), "exec": set(), "nohup": set(), "time": set(), "timeout": {"-s", "-k"},
    "nice": {"-n"}, "ionice": {"-c", "-n", "-p"}, "env": {"-u", "-C", "-S"},
    "sudo": {"-u", "-g", "-h", "-p", "-C"}, "doas": {"-u", "-C"},
    "xargs": {"-I", "-n", "-L", "-P", "-d", "-E", "-s", "-a"}, "stdbuf": {"-i", "-o", "-e"},
    "winpty": set(), "setsid": set(), "unbuffer": set(), "chronic": set(),
}
# Interpreters whose one-liner is code this cannot read: it is held to the old text patterns.
INTERPRETER = re.compile(r"^(?:python[\d.]*|py|node|perl|ruby|php)(?:\.exe)?$")
INTERPRETER_CODE_FLAGS = {"-c", "-e", "-E", "-r", "-p", "--eval", "--print"}
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
# Short options that take a value, by subcommand: in `-Xignore-space-change` the rest of the
# cluster is the value, so its `i` is not --interactive.
SHORT_VALUE_OPTIONS = {"push": "o", "rebase": "XsxSC", "clean": "e", "restore": "s", "commit": "mFCcm"}
ANSI_C_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v", "e": "\x1b",
                  BACKSLASH: BACKSLASH, "'": "'", '"': '"', "?": "?"}


class TooDeep(Exception):
    """Nesting this reader will not follow: refused rather than read partly."""


class TooLong(Exception):
    """A command too long to read in the time a hook has."""


class TooManyGitCalls(Exception):
    """More git look-ups than one hook call should make."""


_git_calls: dict[tuple[str, tuple[str, ...]], subprocess.CompletedProcess[str] | None] = {}


def run_git(directory: str, *args: str) -> subprocess.CompletedProcess[str] | None:
    """`git -C directory args`, remembered for the rest of this hook call."""
    key = (directory, args)
    if key in _git_calls:
        return _git_calls[key]
    if len(_git_calls) >= MAX_GIT_CALLS:
        raise TooManyGitCalls
    try:
        out: subprocess.CompletedProcess[str] | None = subprocess.run(
            ["git", "-C", directory, *args],
            capture_output=True, text=True, check=False, timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, ValueError, subprocess.SubprocessError):  # ValueError: a NUL in an argument
        out = None
    _git_calls[key] = out
    return out


def head_branch(directory: str | None) -> str | None:
    """The branch checked out in `directory`: "" when HEAD is detached, None when it cannot be read.

    None covers no directory, no repository, and git missing or too slow. `symbolic-ref` rather
    than `rev-parse --abbrev-ref HEAD`, which fails on a branch with no commits yet and prints
    "HEAD" for a detached one; `--quiet` makes a detached HEAD exit 1 and anything worse 128.
    """
    if directory is None:
        return None
    out = run_git(directory, "symbolic-ref", "--quiet", "--short", "HEAD")
    if out is None:
        return None
    if out.returncode == 0:
        return out.stdout.strip()
    return "" if out.returncode == DETACHED_HEAD else None


def is_branch(directory: str, name: str) -> bool:
    """Whether `git checkout <name>` there would put HEAD on a branch called `name`."""
    for ref in (f"refs/heads/{name}", f"refs/remotes/origin/{name}"):
        out = run_git(directory, "show-ref", "--verify", "--quiet", ref)
        if out is not None and out.returncode == 0:
            return True
    return False


def ansi_c(s: str, j: int) -> tuple[str, int]:
    """The text of a `$'...'` string whose body starts at `j`, and the index after it."""
    out: list[str] = []
    while j < len(s):
        c = s[j]
        if c == "'":
            return "".join(out), j + 1
        if c == BACKSLASH and j + 1 < len(s):
            e = s[j + 1]
            if e in ANSI_C_ESCAPES:
                out.append(ANSI_C_ESCAPES[e])
                j += 2
            elif e == "x":
                digits = re.match(r"[0-9a-fA-F]{1,2}", s[j + 2 :])
                out.append(chr(int(digits.group(), 16)) if digits else "x")
                j += 2 + (len(digits.group()) if digits else 0)
            elif e in "01234567":
                digits = re.match(r"[0-7]{1,3}", s[j + 1 :])
                assert digits is not None
                out.append(chr(int(digits.group(), 8)))
                j += 1 + len(digits.group())
            else:
                out.append(c + e)
                j += 2
            continue
        out.append(c)
        j += 1
    raise ValueError("unclosed $'...'")


def read_word(s: str, j: int) -> tuple[str, int]:
    """The shell word starting at or after `j`, with its quotes and escapes resolved, and the index
    after it. Used for here-string words and heredoc delimiters."""
    while j < len(s) and s[j] in " \t":
        j += 1
    out: list[str] = []
    while j < len(s) and s[j] not in OPERATOR_CHARS:
        c = s[j]
        if c == "'":
            end = s.find("'", j + 1)
            end = len(s) if end == -1 else end
            out.append(s[j + 1 : end])
            j = end + 1
        elif c == "$" and s[j + 1 : j + 2] == "'":
            text, j = ansi_c(s, j + 2)
            out.append(text)
        elif c == '"':
            j += 1
            while j < len(s) and s[j] != '"':
                if s[j] == BACKSLASH and j + 1 < len(s) and s[j + 1] in '\\"$`':
                    j += 1
                out.append(s[j])
                j += 1
            j += 1
        elif c == BACKSLASH and j + 1 < len(s):
            out.append(s[j + 1])
            j += 2
        else:
            out.append(c)
            j += 1
    return "".join(out), j


def backtick_body(s: str, i: int) -> tuple[str, int]:
    j = i + 1
    while j < len(s):
        if s[j] == BACKSLASH:
            j += 2
            continue
        if s[j] == "`":
            return s[i + 1 : j], j + 1
        j += 1
    raise ValueError("unclosed backtick")


def arithmetic_end(s: str, j: int, depth: int) -> int:
    """The index after the `))` closing arithmetic opened before `j` with `depth` parens, or -1."""
    while j < len(s):
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return -1


class Prepared:
    """`text` ready for shlex with each substitution replaced by a mark; `subs` the substitution bodies
    (marked ones first, then those found in unquoted heredoc bodies); `data` the heredoc and here-string
    bodies; `end` the index after a substitution body when reading one."""

    def __init__(self, text: str, subs: list[str], data: list[str], end: int) -> None:
        self.text, self.subs, self.data, self.end = text, subs, data, end


def substitutions_in(body: str, level: int) -> list[str]:
    """The `$(...)` and backtick bodies an unquoted heredoc body runs (quotes are text there)."""
    found: list[str] = []
    i = 0
    while i < len(body):
        if body[i] == BACKSLASH:
            i += 2
            continue
        if body.startswith("$((", i):
            end = arithmetic_end(body, i + 3, 2)
            if end != -1:
                i = end
                continue
        if body.startswith("$(", i):
            inner = prepare(body, i + 2, closing=True, level=level + 1)
            found.append(body[i + 2 : inner.end - 1])
            i = inner.end
            continue
        if body[i] == "`":
            text, i = backtick_body(body, i)
            found.append(text)
            continue
        i += 1
    return found


def prepare(command: str, start: int = 0, closing: bool = False, level: int = 0) -> Prepared:
    """Read `command` from `start` in one pass (see the section comment). With `closing`, read the body
    of a `$(...)` and stop at its `)`. ValueError on a substitution or `$'` that never closes."""
    if level > MAX_READER_DEPTH:
        raise TooDeep
    out: list[str] = []
    subs: list[str] = []
    late_subs: list[str] = []  # from unquoted heredoc bodies: commands, but not in the text
    data: list[str] = []
    heredocs: list[tuple[str, bool]] = []  # (delimiter, body expands) opened on this line
    quote = ""
    word_start = True
    depth = 0
    arithmetic_at = -1  # the depth `((` arithmetic opened at, while inside it
    i, n = start, len(command)
    while i < n:
        ch = command[i]
        nxt = command[i + 1] if i + 1 < n else ""
        if quote == "'":
            quote = "" if ch == "'" else quote
            out.append(ch)
            i += 1
            continue
        if command.startswith("$((", i):
            end = arithmetic_end(command, i + 3, 2)
            if end != -1:
                out.append("0")
                word_start = False
                i = end
                continue
        if ch == "`" or (ch == "$" and nxt == "(") or (not quote and ch in "<>" and nxt == "("):
            if ch == "`":
                body, i = backtick_body(command, i)
            else:
                inner = prepare(command, i + 2, closing=True, level=level + 1)
                body, i = command[i + 2 : inner.end - 1], inner.end
            out.append(f"{MARK}{len(subs)}{MARK}")
            subs.append(body)
            word_start = False
            continue
        if quote == '"':
            if ch == BACKSLASH and nxt:
                out.append(ch + nxt)
                i += 2
                continue
            quote = "" if ch == '"' else quote
            out.append(ch)
            i += 1
            continue
        # outside quotes from here on
        if closing and depth == 0 and ch == ")":
            return Prepared("".join(out), subs + late_subs, data, i + 1)
        if ch == "$" and nxt == "'":
            text, i = ansi_c(command, i + 2)
            out.append(shlex.quote(text))
            word_start = False
            continue
        if ch in ("'", '"'):
            quote = ch
            word_start = False
        elif ch == BACKSLASH and nxt:
            if nxt != NEWLINE:
                out.append(ch + nxt)
                word_start = False
            i += 2
            continue
        elif ch == "#" and word_start:
            while i < n and command[i] != NEWLINE:  # a comment runs to the end of the line
                i += 1
            continue
        elif command.startswith("<<<", i):
            word, i = read_word(command, i + 3)
            data.append(word)
            out.append(" ")
            word_start = True
            continue
        elif ch == "<" and nxt == "<" and arithmetic_at < 0:
            j = i + 2 + (command[i + 2 : i + 3] == "-")
            raw_start = j
            delimiter, j = read_word(command, j)
            if delimiter:
                quoted = any(c in command[raw_start:j] for c in "'\"\\")
                heredocs.append((delimiter, not quoted))
                out.append(" ")
                word_start = True
                i = j
                continue
        elif ch == "(" and nxt == "(" and word_start and arithmetic_at < 0:
            arithmetic_at = depth
        elif ch == NEWLINE:
            out.append(" ; ")
            word_start = True
            i += 1
            for delimiter, expands in heredocs:  # the bodies follow this line, one after another
                lines: list[str] = []
                while i < n:
                    end = command.find(NEWLINE, i)
                    end = n if end == -1 else end
                    line, i = command[i:end], end + 1
                    if line.rstrip("\r").strip() == delimiter:
                        break
                    lines.append(line)
                body = NEWLINE.join(lines)
                data.append(body)
                if expands:
                    late_subs.extend(substitutions_in(body, level))
            heredocs = []
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth <= arithmetic_at:
                arithmetic_at = -1
        out.append(ch)
        word_start = ch in OPERATOR_CHARS
        i += 1
    if closing:
        raise ValueError("unclosed $(")
    return Prepared("".join(out), subs + late_subs, data, n)


def unmark(text: str) -> str:
    return MARKS.sub(" ", text)


def marks_in(words: list[str]) -> set[int]:
    return {int(k) for w in words for k in MARKS.findall(w)}


def parse_commands(text: str, scope: tuple[int, ...], ids: list[int]) -> list[tuple[tuple[int, ...], list[str]]]:
    """The simple commands in prepared `text` with the subshells each runs in. ValueError on bad quoting."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""  # prepare() has dropped the real comments; `${#x}` and `a#b` are not ones
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
                if len(stack) > MAX_SUBSHELLS:
                    raise TooDeep
            elif ch == ")" and len(stack) > len(scope):
                stack.pop()
    if words:
        out.append((tuple(stack), words))
    return out


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


def shell_script(words: list[str]) -> str | None:
    """The script a `sh -c '...'` runs, or None when these words are not one."""
    for k, w in enumerate(words[1:], 1):
        if re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", w):
            rest = words[k + 1 :]
            if rest and rest[0] == "--":
                rest = rest[1:]
            return rest[0] if rest else None
    return None


def points_git_elsewhere(raw: list[str], words: list[str]) -> bool:
    """Whether this command aims git somewhere `cd` and `git -C` do not say.

    GIT_DIR, GIT_WORK_TREE or GIT_COMMON_DIR assigned (in front of a command, alone, or through `env`)
    or named (`export`, `declare`, `unset`), or `env -C` / `--chdir` running the command elsewhere.
    """
    if any(GIT_REPOSITORY_VARIABLE.match(w) for w in raw):
        return True
    prefix = raw[: len(raw) - len(words)]
    return "env" in (os.path.basename(w) for w in prefix) and any(
        w == "-C" or w.startswith("--chdir") for w in prefix
    )


def walk(command: str, scope: tuple[int, ...] = (), ids: list[int] | None = None, depth: int = 0,
         data: list[str] | None = None, emits_code: bool = False) -> Iterator[tuple[tuple[int, ...], list[str]]]:
    """(subshells, words) for each command `command` runs. Heredoc and here-string bodies go to `data`.
    With `emits_code`, what this text writes (its heredocs, here-strings, echo and printf arguments) is
    run as code by whoever reads it, so it is read as commands too. A command that points git
    elsewhere (`points_git_elsewhere`) is preceded by [GIT_ELSEWHERE], a bare assignment included."""
    if depth > MAX_NESTING:
        raise TooDeep
    ids = ids if ids is not None else [0]
    data = data if data is not None else []
    prepared = prepare(command)
    if len(prepared.text) > MAX_TEXT:
        raise TooLong
    data.extend(prepared.data)
    code: set[int] = set()
    for where, raw in parse_commands(prepared.text, scope, ids):
        words = simple_command(raw)
        if points_git_elsewhere(raw, words):
            yield where, [GIT_ELSEWHERE]
        if not words:
            continue
        name = os.path.basename(words[0])
        if name == "eval":
            code |= marks_in(words[1:])
            yield from walk(unmark(" ".join(words[1:])), where, ids, depth + 1, data)
            continue
        if name in SHELLS:
            script = shell_script(words)
            if script is not None:
                code |= marks_in([script])
                ids[0] += 1
                yield from walk(unmark(script), where + (ids[0],), ids, depth + 1, data)
                continue
            code |= marks_in(words[1:])  # bash <(curl ...): the substitution's output is the script
        if name in ("source", "."):
            code |= marks_in(words[1:])
        if emits_code and name in ("echo", "printf"):
            yield from walk(unmark(" ".join(w for w in words[1:] if not w.startswith("-"))), where, ids, depth + 1, data)
        yield where, words
    if emits_code:
        for body in prepared.data:
            ids[0] += 1
            yield from walk(body, scope + (ids[0],), ids, depth + 1, data)
    for k, body in enumerate(prepared.subs):
        ids[0] += 1
        yield from walk(body, scope + (ids[0],), ids, depth + 1, data, emits_code=k in code)


def bare_shell(words: list[str]) -> bool:
    """A shell with no script, or `source /dev/stdin`: it runs whatever arrives on its standard input."""
    name = os.path.basename(words[0])
    if name in ("source", "."):
        return len(words) > 1 and words[1] in STDIN_SCRIPTS
    if name not in SHELLS or shell_script(words) is not None:
        return False
    skip = False
    for w in words[1:]:
        if skip:
            skip = False
        elif set(w) <= set("<>&0123456789"):
            skip = True  # a redirection and its target
        elif w in SHELL_OPTIONS_WITH_A_VALUE:
            skip = True
        elif re.fullmatch(r"-[a-zA-Z]*s[a-zA-Z]*", w):
            return True  # -s: commands from standard input, the rest are its arguments
        elif w == "-" or w.startswith(("-", "+")):
            continue
        else:
            return False  # a script file
    return True


def split_args(args: list[str], takes_value: str = "") -> tuple[set[str], set[str], list[str]]:
    """Long options, the letters of short options (`-uf` gives u and f) and the positional words.

    A letter in `takes_value` ends its cluster: the rest, or the next word, is its value.
    """
    longs: set[str] = set()
    shorts: set[str] = set()
    positional: list[str] = []
    rest_positional = skip_value = False
    for a in args:
        if skip_value:
            skip_value = False
        elif rest_positional or a == "-" or not a.startswith("-"):
            positional.append(a)
        elif a == "--":
            rest_positional = True
        elif a.startswith("--"):
            longs.add(a.split("=", 1)[0])
        else:
            letters = a[1:]
            for k, c in enumerate(letters):
                shorts.add(c)
                if c in takes_value:
                    skip_value = k == len(letters) - 1
                    break
    return longs, shorts, positional


def option_values(args: list[str], short: str, long: str) -> list[str]:
    """Every value given to `-x VALUE`, `-xVALUE`, `--long VALUE` or `--long=VALUE`."""
    out: list[str] = []
    for k, a in enumerate(args):
        if a in (short, long) and k + 1 < len(args):
            out.append(args[k + 1])
        elif a.startswith(long + "="):
            out.append(a.split("=", 1)[1])
        elif a.startswith(short) and len(a) > len(short) and not a.startswith("--"):
            out.append(a[len(short) :])
    return out


def has_long(longs: set[str], name: str) -> bool:
    """Whether `name` was given: git and GNU tools take any unambiguous prefix of a long option."""
    return any(g == name or (len(g) >= 3 and name.startswith(g)) for g in longs)


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


def resolve_dir(base: str | None, path: str) -> str | None:
    """`path` as a directory relative to `base`, or None when it cannot be found.

    `base` is None when the directory the command is in is itself unknown; then only a path that
    names its own root (`/x`, `C:/x`, `~/x`) can be found.
    """
    try:
        path = os.path.expanduser(native_path(path))
        if base is None:
            # Not os.path.isabs: from Python 3.13 it says False for "/x" on Windows, a path bash roots.
            if not (os.path.splitdrive(path)[0] or path.startswith(("/", BACKSLASH))):
                return None
            base = os.getcwd()  # only lends a drive letter on Windows; a rooted path ignores the rest
        target = os.path.normpath(os.path.join(base, path))
        return target if os.path.isdir(target) else None
    except ValueError:  # a NUL in the path
        return None


def changed_dir(name: str, here: str | None, args: list[str]) -> str | None:
    """Where `cd` or `pushd` with these arguments goes; None when this cannot say.

    `cd` alone goes home. `cd -`, and `pushd` alone or with `+N`/`-N`, move along the shell's directory
    stack, which a single command arrives without. Options other than the ones that only say how to
    resolve the path are not followed either (`pushd -n` does not move at all).
    """
    names: list[str] = []
    for i, a in enumerate(args):
        if a == "--":
            names += args[i + 1:]
            break
        if a == "-" or not a.startswith("-"):
            names.append(a)
        elif a not in CD_OPTIONS:
            return None
    if not names:
        return None if name == "pushd" else resolve_dir(None, "~")
    return None if names[0] == "-" else resolve_dir(here, names[0])


def scoped(values: dict[tuple[int, ...], str | None], scope: tuple[int, ...]) -> str | None:
    """The value set in `scope` or the nearest subshell around it."""
    for k in range(len(scope), -1, -1):
        if scope[:k] in values:
            return values[scope[:k]]
    return None


def git_target(here: str | None, args: list[str], aliases: dict[str, str]) -> tuple[str | None, list[str]]:
    """The directory a git invocation works in (None when unknown) and its words from the subcommand on.
    An alias set with `-c alias.x=...` is added to `aliases`."""
    directory, rest, elsewhere = here, args, False
    while rest and rest[0].startswith("-"):
        option, rest = rest[0], rest[1:]
        if option == "-C" and rest:
            directory = resolve_dir(directory, rest[0])
        if option == "-c" and rest and rest[0].startswith("alias.") and "=" in rest[0]:
            name, value = rest[0][len("alias."):].split("=", 1)
            aliases[name] = value
        # Another repository, named in a way this does not follow; a later -C does not undo it.
        elsewhere = elsewhere or option.split("=", 1)[0] in GIT_OPTIONS_THAT_MOVE_THE_REPOSITORY
        if option in GIT_OPTIONS_WITH_A_VALUE and rest:
            rest = rest[1:]
    return (None if elsewhere else directory), rest


def expand_alias(directory: str, rest: list[str], aliases: dict[str, str]) -> list[str]:
    """`rest` with a git alias in front replaced by what it stands for; a shell alias becomes ["!", text]."""
    if not rest or rest[0] in GIT_BUILTINS:
        return rest
    value = aliases.get(rest[0], "")
    if not value:
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
FORCE_OPTIONS = ("--force", "--force-with-lease", "--force-if-includes", "--mirror")


def protected_ref(word: str, protected: list[str]) -> str:
    """The protected branch `word` names (`main`, `refs/heads/main`), or ""."""
    name = word.removeprefix("refs/heads/")
    return name if name in protected else ""


def git_danger(sub: str, args: list[str], protected: list[str]) -> str:
    """Why this git subcommand is refused, or ""."""
    longs, shorts, positional = split_args(args, SHORT_VALUE_OPTIONS.get(sub, ""))
    if sub == "push":
        if any(has_long(longs, o) for o in FORCE_OPTIONS) or "f" in shorts:
            return "force push"
        if any(p.startswith("+") for p in positional):
            return "force push"
        deleting = has_long(longs, "--delete") or "d" in shorts
        for p in positional[1:]:
            target = protected_ref(p[1:], protected) if p.startswith(":") else (protected_ref(p, protected) if deleting else "")
            if target:
                return f"deleting {target}"
    elif sub == "branch":
        if has_long(longs, "--delete") or shorts & {"d", "D"}:
            for p in positional:
                if protected_ref(p, protected):
                    return f"deleting {protected_ref(p, protected)}"
    elif sub == "reset":
        if has_long(longs, "--hard"):
            return "git reset --hard"
    elif sub == "checkout":
        if any(p in DISCARD_ALL for p in positional):
            return "discarding all working changes"
    elif sub == "restore":
        staged_only = (has_long(longs, "--staged") or "S" in shorts) and not (has_long(longs, "--worktree") or "W" in shorts)
        if not staged_only and any(p in DISCARD_ALL for p in positional):
            return "discarding all working changes"
    elif sub == "clean":
        dry_run = has_long(longs, "--dry-run") or "n" in shorts
        if (has_long(longs, "--force") or "f" in shorts) and not dry_run:
            return "git clean -f"
    elif sub == "rebase":
        if has_long(longs, "--interactive") or "i" in shorts:
            return "interactive rebase (do it manually if needed)"
    return ""


def rm_danger(args: list[str]) -> str:
    longs, shorts, positional = split_args(args)
    if not (has_long(longs, "--recursive") or shorts & {"r", "R"}):
        return ""
    for target in positional:
        bare = target.rstrip("/") or "/"
        if bare in ROOT_TARGETS or DRIVE_ROOT.fullmatch(bare):
            return "recursive delete of a root, home, or parent directory"
    return ""


LEGACY_PATTERNS = [
    (re.compile(r"git\s+push\b.*\s(--force\S*|-f\b|\+\S+)"), "force push"),
    (re.compile(r"git\s+reset\s+.*--hard"), "git reset --hard"),
    (re.compile(r"git\s+checkout\s+--\s+\."), "discarding all working changes"),
    (re.compile(r"git\s+clean\s+-[a-zA-Z]*f"), "git clean -f"),
    (re.compile(r"git\s+rebase\s+.*(\s-i\b|--interactive)"), "interactive rebase (do it manually if needed)"),
    (re.compile(r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(/|~|\$HOME|\.\.)(\s|$)"), "recursive delete of a root, home, or parent directory"),
]
RISKY_MENTION = re.compile(r"\bgit\b.*\b(push|reset|clean|checkout|restore|branch|rebase|commit)\b|\brm\b.*\s-[a-zA-Z]*[rR]", re.S)


def text_danger(text: str, protected: list[str]) -> str:
    """The old text patterns, and deletes of protected branches: for code this cannot read."""
    for pattern, reason in LEGACY_PATTERNS:
        if pattern.search(text):
            return reason
    names = "|".join(re.escape(b) for b in protected)
    if names:
        for deleting in (
            rf"git\s+(?:branch|push)\b[^\n;&|]*\s(?:-[a-zA-Z]*[dD][a-zA-Z]*|--delete)\b[^\n;&|]*?\s(?:refs/heads/)?({names})(?![\w./-])",
            rf"git\s+push\b[^\n;&|]*\s:(?:refs/heads/)?({names})(?![\w./-])",
        ):
            m = re.search(deleting, text)
            if m:
                return f"deleting {m.group(1)}"
    return ""


def commit_verdict(branch: str | None, protected: list[str]) -> str:
    """Why a commit landing on `branch` (None: unknown, "": detached HEAD) is refused, or ""."""
    if not protected:
        return ""
    if branch is None:
        return UNKNOWN_TARGET
    return f"committing directly to {branch}. Create a feature branch first" if branch in protected else ""


def unreadable(command: str, start: str | None, protected: list[str], depth: int) -> str:
    """Judge a command that cannot be split. Bash still runs the lines before a broken quote, so each
    line is judged on its own; a line that cannot be split either is held to the old text patterns, and
    refused outright if it mentions a git or rm command that could do damage."""
    if NEWLINE in command and depth < MAX_NESTING:
        for line in command.split(NEWLINE):
            reason = check_bash(line, start, protected, depth + 1)
            if reason:
                return reason
        return ""
    reason = text_danger(command, protected)
    if reason:
        return reason
    if RISKY_MENTION.search(command):
        return "could not read this command reliably; run it as simpler, separate commands"
    return commit_verdict(head_branch(start), protected) if LOOKS_LIKE_A_COMMIT.search(command) else ""


def check_bash(command: str, start: str | None, protected: list[str], depth: int = 0) -> str:
    """Why `command` is refused, or "". `start` is the directory it runs in, None when unknown.

    Commits are judged on the branch they will land on, in the repository they will land in.
    """
    data: list[str] = []
    try:
        commands = list(walk(command, depth=depth, data=data))
        if any(bare_shell(words) for _, words in commands):
            # A shell reading its standard input runs what is piped or fed to it: every other command's
            # arguments, and every heredoc and here-string body.
            fed = [" ".join(ws[1:]) for _, ws in commands if not bare_shell(ws) and len(ws) > 1] + data
            for text in fed:
                commands.extend(walk(unmark(text), (-1,), depth=depth + 1))
        return judge(commands, start, protected, depth)
    except TooDeep:
        return "command nested too deeply to check; run it as simpler, separate commands"
    except TooLong:
        return "command too long to check; split it into smaller commands"
    except TooManyGitCalls:
        return "too many git commands to check in one go; run them in smaller groups"
    except ValueError:
        return unreadable(command, start, protected, depth)


def judge(commands: list[tuple[tuple[int, ...], list[str]]], start: str | None, protected: list[str], depth: int) -> str:
    """Why the commands `walk` found are refused, or ""."""
    heres: dict[tuple[int, ...], str | None] = {(): start}  # None: somewhere this cannot follow
    pushed: dict[tuple[int, ...], list[str | None]] = {}
    moved: dict[str, str] = {}  # repository directory -> branch an earlier checkout put it on
    aliases: dict[str, str] = {}  # set earlier in this same command
    lost = False  # git was aimed or switched somewhere this cannot name: no later commit can be placed
    for scope, words in commands:
        if words[0] == GIT_ELSEWHERE:
            lost = True
            continue
        here = scoped(heres, scope)
        name = os.path.basename(words[0])
        if MARK in words[0]:
            # A command name computed at run time: judge the rest as git and as rm would be judged.
            reason = (git_danger(words[1], words[2:], protected) if len(words) > 1 else "") or rm_danger(words[1:])
            if reason:
                return reason
            continue
        if name in ("cd", "pushd"):
            if name == "pushd":
                pushed.setdefault(scope, []).append(here)
            heres[scope] = changed_dir(name, here, words[1:])
            continue
        if name == "popd":
            stack = pushed.get(scope)
            heres[scope] = stack.pop() if stack else None
            continue
        if name == "rm":
            reason = rm_danger(words[1:])
            if reason:
                return reason
            continue
        if name == "find":
            for k, w in enumerate(words):
                if w in ("-exec", "-execdir", "-ok", "-okdir"):
                    run = []
                    for x in words[k + 1 :]:
                        if x in (";", "+"):
                            break
                        run.append(x)
                    reason = check_bash(shlex.join(run), here, protected, depth + 1) if run else ""
                    if reason:
                        return reason
            continue
        if INTERPRETER.match(name):
            for k, w in enumerate(words[1:-1], 1):
                if w in INTERPRETER_CODE_FLAGS or re.fullmatch(r"-[a-zA-Z]*[ce]", w):
                    reason = text_danger(words[k + 1], protected)
                    if reason:
                        return reason
            continue
        if name not in ("git", "git.exe"):
            continue
        where, rest = git_target(here, words[1:], aliases)
        rest = expand_alias(where or os.getcwd(), rest, aliases)  # unknown target: the project's and global aliases
        if not rest:
            continue
        if rest[0] == "!" and len(rest) > 1:
            if depth >= MAX_NESTING:
                return "command nested too deeply to check; run it as simpler, separate commands"
            reason = check_bash(rest[1], where, protected, depth + 1)
            if reason:
                return reason
            continue
        sub, args = rest[0], rest[1:]
        reason = git_danger(sub, args, protected)
        if reason:
            return reason
        nested = []
        if sub == "submodule" and "foreach" in args:
            run = [a for a in args[args.index("foreach") + 1 :] if a not in ("--recursive", "-q", "--quiet")]
            nested = [run[0] if len(run) == 1 else shlex.join(run)] if run else []
        elif sub == "rebase":
            nested = option_values(args, "-x", "--exec")
        for text in nested:
            reason = check_bash(text, where, protected, depth + 1)
            if reason:
                return reason
        if sub == "config":
            _, _, positional = split_args(args)
            if len(positional) >= 2 and positional[0].startswith("alias."):
                aliases[positional[0][len("alias."):]] = positional[1]
        elif sub in ("checkout", "switch"):
            switched = switched_to(args, where) if where is not None else None
            if switched is None:
                lost = True
            elif switched:
                moved[where] = switched
        elif sub == "commit":
            branch = (moved.get(where) or head_branch(where)) if where is not None and not lost else None
            reason = commit_verdict(branch, protected)
            if reason:
                return reason
    return ""


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
# No word boundary in front: DB_PASSWORD, dbPassword and AUTH0_CLIENT_SECRET are credential names too.
CREDENTIAL = re.compile(
    r"""(password|passwd|client[_-]?secret|secret|api[_-]?key|access[_-]?token|auth[_-]?token|token)["']?"""
    r"""\s*[:=]\s*(["'])([^"'\s$<{]{12,})\2""",
    re.I,
)
PLACEHOLDER = re.compile(r"example|placeholder|changeme|change[_-]me|your[_-]|dummy|xxxx|redacted|fake", re.I)


def env_file(path: str) -> bool:
    """Whether a write to `path` writes an env file. Names are compared as Windows and macOS open
    them: case-insensitively, and on Windows without trailing spaces or dots or an `::$DATA` stream."""
    name = path.replace(BACKSLASH, "/").rsplit("/", 1)[-1].split(":", 1)[0].rstrip(" .").lower()
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
URL_ATTRIBUTES = ("href", "src", "action")
COMMENT_START = ("//", "/*", "*", "<!--", "#")
CONTEXT_WINDOW = 200  # how far back from a match its context is read; keeps a long line linear
COLOUR_CONTEXT = set(":,(=\"'")
COLOUR_SCOPE_EXT = (".css", ".scss", ".tsx", ".jsx", ".vue", ".svelte", ".html")
COLOUR_SCOPE_DIRS = ("src/components/", "src/app/", "src/pages/", "src/ui/", "templates/")
MAX_HITS_SHOWN = 6


def after_url_attribute(before: str) -> bool:
    """Whether `before` ends inside `href="`, `src=` or `action='`: what follows is an anchor."""
    head = before.rstrip().rstrip("\"'").rstrip()
    return head.endswith("=") and head[:-1].rstrip().lower().endswith(URL_ATTRIBUTES)


def in_css_value(before: str) -> bool:
    """Whether `before` ends inside a CSS declaration's value (`border: 1px solid `)."""
    declaration = max(before.rfind(";"), before.rfind("{"), before.rfind("}"))
    head, colon, _ = before[declaration + 1 :].rpartition(":")
    name = head.rstrip()
    return bool(colon) and bool(name) and (name[-1].isalpha() or name[-1] == "-")


def is_colour(line: str, m: re.Match[str], comment: bool) -> bool:
    """Whether a `#xxx` match is a colour. An anchor (`href="#add"`) is not; an all-digit short one
    (`#123`, `#1001`) is an issue or order number unless it sits where a CSS value goes. Only the
    CONTEXT_WINDOW characters before the match are read, so a long line stays linear."""
    before = line[max(0, m.start() - CONTEXT_WINDOW) : m.start()]
    if after_url_attribute(before):
        return False
    digits = m.group(1)
    if len(digits) > 4 or not digits.isdigit():
        return True
    if before.rstrip()[-1:] in COLOUR_CONTEXT:
        return True
    return in_css_value(before) and not comment


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
            if "brand-exception:" in line:
                continue
            comment = line.lstrip().startswith(COMMENT_START)
            if any(is_colour(line, m, comment) for m in HEX_COLOUR.finditer(line)):
                hits.append(f"  line {n}: {line.strip()[:110]}")
    if not hits:
        return ""
    more = [f"  ... and {len(hits) - MAX_HITS_SHOWN} more"] if len(hits) > MAX_HITS_SHOWN else []
    return "\n".join([f"hardcoded colour in {relpath}.", *hits[:MAX_HITS_SHOWN], *more])


# --- the Stop hook's test runs -------------------------------------------------------------------
#
# stop-tests.sh hands each package's profile hook to stop-run, which does three things bash cannot do
# well on all three platforms:
#   - One run at a time per package and worktree. The lock is an OS file lock, freed when this process
#     ends however it ends, so a killed hook never leaves it held.
#   - A tree already proven green in this scope is not tested again. The proof is a hash of HEAD, the
#     package's diff and untracked files, the scope, the profile hook, and the files outside git that
#     decide what the default scope runs (SCOPE_STATE). Another session ending a turn on the same
#     checkout, a reviewer that edits nothing, waits for the run in progress and uses its result.
#   - A deadline. Claude Code abandons a hook at its timeout without stopping what it started, and on
#     Windows a killed bash leaves its pytest running, so runs stacked up for an hour. At the deadline
#     the hook and every process under it are killed and the run is reported as not proven.
#
# lf-files and lf-passed bound the python profile's last-failed scope. When none of the recorded
# failures is collected (the failing test was renamed or deleted), `pytest --lf` runs the whole suite,
# and an entry it never collects is never cleared, so one stale entry made every Stop a full run.

LASTFAILED = os.path.join(".pytest_cache", "v", "cache", "lastfailed")
SCOPE_STATE = {"python": [LASTFAILED]}
OUT_OF_TIME = 124  # as timeout(1)
LOCK_POLL_SECONDS = 0.2
TERM_GRACE_SECONDS = 3
HASH_CHUNK = 1 << 20
# Through a native Windows Python, Git Bash hands /c/... paths on as C:/..., and the profile hooks
# compare KIT_ROOT with `pwd -P`; the child bash re-reads it in its own spelling.
RUN_PROFILE_HOOK = 'KIT_ROOT="$(cd "$KIT_ROOT" && pwd -P)"; export KIT_ROOT; cd "$1" && exec bash "$2"'


def git_output(*args: str) -> bytes | None:
    """`git args` in the current directory as bytes, never cached: the tree may change between calls."""
    try:
        out = subprocess.run(["git", *args], capture_output=True, check=False, timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def file_digest(path: str) -> bytes | None:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(HASH_CHUNK), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.digest()


def tree_fingerprint(profile: str, pkgpath: str, scope: str, hook: str) -> str | None:
    """What a green run proves, as a hash; None when part of it cannot be read, so nothing is skipped."""
    h = hashlib.sha256()

    def part(label: str, data: bytes | None) -> bool:
        if data is None:
            return False
        h.update(f"{label}\0{len(data)}\0".encode() + data)
        return True

    diff = ["diff", "--binary", "--no-ext-diff", "--no-textconv"]
    head = git_output("rev-parse", "--verify", "--quiet", "HEAD") or b"unborn"
    if head == b"unborn":
        changes = [git_output(*diff, "--cached", "--", pkgpath), git_output(*diff, "--", pkgpath)]
    else:
        changes = [git_output(*diff, "HEAD", "--", pkgpath)]
    untracked = git_output("ls-files", "--others", "--exclude-standard", "-z", "--", pkgpath)
    readable = (
        part("scope", scope.encode())
        and part("hook", file_digest(hook))
        and part("head", head)
        and all(part("diff", c) for c in changes)
        and part("untracked", untracked)
    )
    for name in (untracked or b"").split(b"\0"):
        if name and readable:
            readable = part(name.decode("utf-8", "replace"), file_digest(os.fsdecode(name)))
    for state in SCOPE_STATE.get(profile, []):
        if readable:
            readable = part(state, file_digest(os.path.join(pkgpath, state)) or b"absent")
    return h.hexdigest() if readable else None


def stop_state(pkgpath: str) -> str | None:
    """Where this package's lock and proof live: inside this worktree's git directory, never committed."""
    gitdir = git_output("rev-parse", "--absolute-git-dir")
    if gitdir is None:
        return None
    directory = os.path.join(gitdir.decode().strip(), "kit")
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError:
        return None
    return os.path.join(directory, "stop-" + hashlib.sha256(norm(pkgpath).encode()).hexdigest()[:16])


def try_lock(f: io.BufferedRandom) -> bool:
    try:
        if os.name == "nt":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Stop proc and everything under it: its process group, or on Windows its tree by parent id."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)
    else:
        for sig, grace in ((signal.SIGTERM, TERM_GRACE_SECONDS), (signal.SIGKILL, None)):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                break
            if grace:
                try:
                    proc.wait(grace)
                except subprocess.TimeoutExpired:
                    pass
    proc.wait()


def run_until(command: list[str], deadline: float) -> int | None:
    """Run command; its exit code, or None when the deadline came first and it was killed."""
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, start_new_session=os.name != "nt")
    try:
        return proc.wait(timeout=max(0.0, deadline - time.time()))
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        return None


def read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def stop_run(profile: str, pkgpath: str, scope: str, deadline: float, bash: str, hook: str) -> int:
    command = [bash, "-c", RUN_PROFILE_HOOK, "kit-stop", pkgpath, hook]
    state = stop_state(pkgpath)
    if state is None:
        rc = run_until(command, deadline)
        return OUT_OF_TIME if rc is None else rc
    with open(state + ".lock", "a+b") as lock:
        while not try_lock(lock):
            if time.time() >= deadline:
                print(f"Another Stop hook was still testing {pkgpath}.", file=sys.stderr)
                return OUT_OF_TIME
            time.sleep(LOCK_POLL_SECONDS)
        before = tree_fingerprint(profile, pkgpath, scope, hook)
        if before is not None and read_text(state + ".proven") == before:
            return 0
        rc = run_until(command, deadline)
        if rc is None:
            return OUT_OF_TIME
        # Recorded only if nothing changed while it ran: a mid-run edit was not what it tested.
        if rc == 0 and before is not None and tree_fingerprint(profile, pkgpath, scope, hook) == before:
            with open(state + ".proven", "w", encoding="utf-8") as f:
                f.write(before + "\n")
        return rc


def failed_path(nodeid: str) -> str:
    """The file or directory a pytest node id lives in: "tests/test_a.py::test_x[1]" -> "tests/test_a.py"."""
    return nodeid.split("::", 1)[0] or "."


def read_lastfailed() -> dict | None:
    try:
        with open(LASTFAILED, encoding="utf-8") as f:
            record = json.load(f)
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def write_lastfailed(record: dict) -> None:
    """Rewrite the record as pytest writes it, through a temporary file so a reader never sees half."""
    tmp = LASTFAILED + ".kit-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    os.replace(tmp, LASTFAILED)


def lf_files() -> int:
    record = read_lastfailed()
    if record is None:
        return 1
    kept = {k: v for k, v in record.items() if os.path.exists(failed_path(k))}
    if len(kept) != len(record):
        write_lastfailed(kept)
    for path in dict.fromkeys(failed_path(k) for k in kept):
        print(path)
    return 0


def lf_passed(paths: list[str]) -> int:
    """After a green run over `paths`, every recorded failure there that still exists ran and passed,
    and pytest cleared it; what is left was never collected, so it is stale."""
    record = read_lastfailed()
    if record is None:
        return 0

    def ran(nodeid: str) -> bool:
        where = failed_path(nodeid)
        return any(p == "." or where == p or where.startswith(p.rstrip("/") + "/") for p in paths)

    kept = {k: v for k, v in record.items() if not ran(k)}
    if len(kept) != len(record):
        write_lastfailed(kept)
    return 0


def read_payload() -> dict:
    """The hook's JSON from stdin. Exits BAD_INPUT when it is not an object."""
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        sys.exit(BAD_INPUT)
    if not isinstance(payload, dict):
        sys.exit(BAD_INPUT)
    return payload


def bash_cwd(payload: dict) -> str | None:
    """The directory the Bash tool runs the command in; None when it cannot be found.

    lib.sh moves to CLAUDE_PROJECT_DIR before this runs, while Claude Code reports the Bash tool's
    own working directory as `cwd`. They differ whenever a session works in a worktree, so
    `os.getcwd()` named the primary checkout, often on main. A payload without `cwd` is judged in
    the project, as it was before the field was read. Exits BAD_INPUT when `cwd` is not text.
    """
    cwd = payload.get("cwd")
    if cwd is None:
        return os.getcwd()
    if not isinstance(cwd, str):
        sys.exit(BAD_INPUT)
    return resolve_dir(os.getcwd(), cwd) if cwd else None


def read_tool_input(payload: dict) -> dict:
    """The payload's tool_input. Exits BAD_INPUT when it is not an object or a text field is not text."""
    tool_input = payload.get("tool_input")
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
    elif cmd == "tool-input":
        data = json.load(sys.stdin)
        value = data.get("tool_input", {}).get(args[0], "")
        print(value if isinstance(value, str) else json.dumps(value))
    elif cmd == "guard-bash":
        payload = read_payload()
        reason = check_bash(read_tool_input(payload).get("command") or "", bash_cwd(payload), protected)
        if reason:
            print(reason)
    elif cmd == "guard-secrets":
        reason = check_secrets(read_tool_input(read_payload()))
        if reason:
            print(reason)
    elif cmd == "guard-colours":
        reason = check_colours(read_tool_input(read_payload()), cfg)
        if reason:
            print(reason)
    elif cmd == "stop-run":
        profile, pkgpath, scope, deadline, bash, hook = args
        return stop_run(profile, pkgpath, scope, float(deadline), bash, hook)
    elif cmd == "lf-files":
        return lf_files()
    elif cmd == "lf-passed":
        return lf_passed(args)
    else:
        print(f"kit.py: unknown command {cmd}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
