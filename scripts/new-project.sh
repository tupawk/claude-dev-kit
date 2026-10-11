#!/usr/bin/env bash
# Assemble a project from core + one stack profile per package, or refresh one that already has the kit.
#
#   scripts/new-project.sh <spec> <target-dir> [project-name]     new project, or first apply to an existing one
#   scripts/new-project.sh update <target-dir>                     refresh a project that has .claude/kit.json
#
#   <spec> is profile[=path][,profile[=path]...]. Profiles: typescript | python | scripts.
#     typescript                              one package at the project root
#     typescript=services/api,python=workers/agent   a polyglot repo: one package per directory
#
# Safe to re-run. The kit refreshes the files it installed under .claude/ (agents, skills, rules, hooks;
# listed in .claude/KIT_FILES), design/ (tokens, README, image checker, any pack files), docs/STACK.md
# and the PR template. A project's own agents, skills, rules and hooks beside them are kept, and so are
# its own settings and hooks in settings.json. It never touches CLAUDE.md, README.md, .claude/kit.json,
# .github/workflows/ci.yml, docs/PLAN.md, docs/ARCHITECTURE.md or code once they exist. Everything it
# needs (profiles, package paths, the design pack) is checked before it writes anything, so a refused
# run leaves the project as it was. Project settings in .claude/kit.json (packages, design pack, design
# exemptions, protected branches) are read on every run; edit that file, then run `update`.
set -euo pipefail

KIT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-}"
TARGET="${2:-}"

usage() { sed -n '2,19p' "$0"; exit 1; }
die() { echo "Error: $*" >&2; exit 1; }
[ -z "$MODE" ] || [ -z "$TARGET" ] && usage

# Escape &, /, and \ so sed treats a value literally in the replacement side of s///
# (an unescaped & would expand to the matched text).
sed_escape() { printf '%s' "$1" | sed 's/[&/\]/\\&/g'; }

PY=""; for c in python3 python "py -3"; do case "$(command -v "${c%% *}" 2>/dev/null)" in *WindowsApps*) continue;; esac; $c -c "import sys; sys.exit(sys.version_info[0] != 3)" >/dev/null 2>&1 && { PY="$c"; break; }; done  # skip the slow, non-functional Windows Store stubs
[ -n "$PY" ] || die "no working Python 3 found (tried python3, python, py -3). Install Python 3 or fix the PATH."

# The target is created only after step 0 has checked everything, so a refused new project leaves no
# empty directory behind. `update` needs it to exist already.
if [ "$MODE" = "update" ] && [ ! -d "$TARGET" ]; then die "$TARGET is not a directory"; fi
if [ -d "$TARGET" ]; then TARGET="$(cd "$TARGET" && pwd)"; fi
KIT_JSON="$TARGET/.claude/kit.json"
MANIFEST="$TARGET/.claude/KIT_FILES"
UPDATE=0; [ -f "$TARGET/CLAUDE.md" ] && UPDATE=1                # an existing project, not a blank directory
FIRST_APPLY=1; [ -f "$TARGET/.claude/KIT_VERSION" ] && FIRST_APPLY=0   # the kit has been here before

# ---- Resolve the package list: "<profile>\t<path>" per line -------------------------------------
if [ "$MODE" = "update" ]; then
  [ -f "$KIT_JSON" ] || die "$KIT_JSON not found. Run with a <spec> the first time."
  NAME="${3:-$(basename "$TARGET")}"
  PACKAGES=$(cd "$TARGET" && $PY "$KIT_DIR/core/.claude/hooks/kit.py" packages)
else
  case "${3:-}" in *[$'\n\r']*) die "Project name must not contain newlines";; esac
  [ -f "$KIT_JSON" ] && die "$KIT_JSON already exists. Edit it and run: $0 update $TARGET"
  NAME="${3:-$(basename "$TARGET")}"
  PACKAGES=""
  IFS=',' read -ra SPECS <<< "$MODE"
  for s in "${SPECS[@]}"; do
    p="${s%%=*}"; d="${s#*=}"; [ "$d" = "$s" ] && d="."
    d="${d#./}"; d="${d%/}"; [ -z "$d" ] && d="."
    LINE=$(printf '%s\t%s' "$p" "$d")
    PACKAGES="${PACKAGES}${PACKAGES:+
}${LINE}"
  done
fi
PROFILES=$(printf '%s\n' "$PACKAGES" | cut -f1 | awk '!seen[$0]++')
ONLY_SCRIPTS=1; for p in $PROFILES; do [ "$p" = "scripts" ] || ONLY_SCRIPTS=0; done

# ---- 0. Check everything before writing anything --------------------------------------------------
# A refusal found halfway through used to leave the project with kit files deleted, the brand reset
# to the kit's neutral palette and settings unmerged. Every input is validated here, and a git pack is
# fetched into the cache, before the first write to the project.
while IFS=$'\t' read -r p d; do
  case "$p" in
    typescript|python|scripts) ;;
    *) [ "$MODE" = "update" ] && die "unknown profile '$p' for package '$d' in .claude/kit.json (expected typescript, python or scripts)"
       echo "Unknown profile: $p" >&2; usage ;;
  esac
  case "$d" in
    /*|[A-Za-z]:*|..|../*|*/..|*/../*) die "package path '$d' must be inside the project: no absolute path and no '..'" ;;
  esac
  if [ "$MODE" = "update" ] && [ ! -d "$TARGET/$d" ]; then
    die "package path '$d' in .claude/kit.json does not exist under $TARGET"
  fi
done <<< "$PACKAGES"

# settings.json is merged in step 4, after kit files are rewritten; a file the merge cannot read must be
# refused here, not discovered there. A list the kit adds to (permissions.deny) must be a list.
if [ -f "$TARGET/.claude/settings.json" ]; then
  $PY - "$KIT_DIR/core/.claude/settings.json" "$TARGET/.claude/settings.json" <<'PY' || exit 1
import json, sys
kit = json.load(open(sys.argv[1], encoding="utf-8"))
def refuse(problem):
    print(f"Error: .claude/settings.json {problem}. Fix it by hand; nothing was changed.", file=sys.stderr)
    sys.exit(1)
try:
    project = json.load(open(sys.argv[2], encoding="utf-8"))
except ValueError as e:
    refuse(f"is not valid JSON ({e})")
if not isinstance(project, dict):
    refuse("must be a JSON object")
for key in ("permissions", "hooks"):
    if key in project and not isinstance(project[key], dict):
        refuse(f'has "{key}" that is not an object')
for event, entries in project.get("hooks", {}).items():
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        refuse(f'has hooks."{event}" that is not a list of objects')
for kind, value in kit.get("permissions", {}).items():
    current = project.get("permissions", {}).get(kind)
    if isinstance(value, list) and current is not None and not isinstance(current, list):
        refuse(f'has permissions."{kind}" that is not a list')
PY
fi

# The hook scripts the kit installed last time, read before step 1 replaces the manifest: a settings
# entry running one of them is the kit's even when the kit has since stopped shipping that script.
OLD_KIT_HOOK_PATHS=""
if [ -f "$MANIFEST" ]; then OLD_KIT_HOOK_PATHS=$(tr -d '\r' < "$MANIFEST" | grep '^\.claude/hooks/' || true); fi

PACK=""
[ -f "$KIT_JSON" ] && PACK=$($PY -c 'import json,sys; print(json.load(open(sys.argv[1])).get("design",{}).get("pack",""))' "$KIT_JSON")
PACK_DIR=""
if [ -n "$PACK" ]; then
  case "$PACK" in
    http://*|https://*|git@*|ssh://*|file://*)
      # Keyed on the whole URL, not the repo name: two organisations' "design" repos are two packs.
      KEY=$(printf '%s' "$PACK" | $PY -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.read().encode()).hexdigest()[:16])')
      PACK_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/claude-dev-kit/packs/$(basename "${PACK%.git}")-$KEY"
      if [ -d "$PACK_DIR/.git" ] && [ "$(git -C "$PACK_DIR" remote get-url origin 2>/dev/null)" != "$PACK" ]; then
        rm -rf "$PACK_DIR"                                  # the cache is the kit's; a stranger's clone goes
      fi
      # core.longpaths: the cache path plus a pack's own paths can pass Windows' 260-character limit.
      if [ -d "$PACK_DIR/.git" ]; then
        # fetch + detached checkout, not pull: a pack whose history was rewritten is followed, not refused.
        git -c core.longpaths=true -C "$PACK_DIR" fetch -q origin HEAD || die "could not fetch design pack $PACK"
        git -c core.longpaths=true -C "$PACK_DIR" checkout -q -f --detach FETCH_HEAD || die "could not check out design pack $PACK"
      else
        mkdir -p "$(dirname "$PACK_DIR")"
        git -c core.longpaths=true clone -q "$PACK" "$PACK_DIR" || die "could not clone design pack $PACK"
      fi ;;
    *) PACK_DIR="$(cd "$TARGET" && cd "$PACK" 2>/dev/null && pwd)" || die "design pack '$PACK' (from .claude/kit.json) not found relative to $TARGET" ;;
  esac
fi

# Everything checks out: from here on the script writes.
mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"
KIT_JSON="$TARGET/.claude/kit.json"
MANIFEST="$TARGET/.claude/KIT_FILES"

# Text files are written LF whatever the kit or pack checkout has: a CRLF copy into a project that
# normalises to LF shows every kit file as modified until git renormalises it, and a CRLF hook breaks bash.
is_text() { case "$1" in *.png|*.jpg|*.jpeg|*.gif|*.webp|*.ico|*.woff|*.woff2|*.ttf|*.otf|*.pdf|*.pyc) return 1;; *) return 0;; esac; }
copy_file() { # src dst
  mkdir -p "$(dirname "$2")"
  if is_text "$1"; then tr -d '\r' < "$1" > "$2"; else cp "$1" "$2"; fi
}
copy_if_missing() { # src dst
  if [ ! -e "$2" ]; then copy_file "$1" "$2"; echo "  + ${2#"$TARGET"/}"; fi
}
copy_always() {
  copy_file "$1" "$2"; echo "  ~ ${2#"$TARGET"/}"
}
NEW_MANIFEST="$MANIFEST.new"
trap 'rm -f "$NEW_MANIFEST"' EXIT                          # never leave a half-built manifest behind
kit_install() { # src dst: a kit-owned file under .claude/, recorded so the next update can remove it
  copy_always "$1" "$2"; printf '%s\n' "${2#"$TARGET"/}" >> "$NEW_MANIFEST"
}

echo "Assembling $NAME in $TARGET"
printf '%s\n' "$PACKAGES" | while IFS=$'\t' read -r p d; do echo "  package: $p at $d"; done

# ---- 1. Standards that the kit owns: always refreshed --------------------------------------------
# Only the files the kit installed last time are removed (so one the kit has stopped shipping goes);
# a project's own agents, skills, rules and hooks in the same directories stay. A project from before
# the manifest existed has nothing removed; its kit files are simply overwritten.
echo "Standards (kit-owned, refreshed):"
mkdir -p "$TARGET/.claude"
: > "$NEW_MANIFEST"
if [ -f "$MANIFEST" ]; then
  while IFS= read -r f; do
    f="${f%$'\r'}"                                           # a manifest saved on Windows ends lines in CR
    case "$f" in
      *..*) continue ;;                                      # never follow a path out of .claude/
      .claude/agents/*|.claude/skills/*|.claude/rules/*|.claude/hooks/*) ;;
      *) continue ;;
    esac
    [ -f "$TARGET/$f" ] || [ -L "$TARGET/$f" ] || continue   # a directory or a missing file is left alone
    rm -f "$TARGET/$f"
  done < "$MANIFEST"
fi
rm -rf "$TARGET/.claude/hooks/__pycache__"
for dir in agents skills rules hooks; do
  [ -d "$TARGET/.claude/$dir" ] || continue
  find "$TARGET/.claude/$dir" -mindepth 1 -depth -type d -empty -exec rmdir {} \;
done
( cd "$KIT_DIR/core" && find .claude -type f ! -name settings.json ! -path '*/__pycache__/*' ) | while read -r f; do
  kit_install "$KIT_DIR/core/$f" "$TARGET/$f"
done
for p in $PROFILES; do
  ( cd "$KIT_DIR/profiles/$p" && find .claude -type f ! -path '*/__pycache__/*' ) | while read -r f; do
    kit_install "$KIT_DIR/profiles/$p/$f" "$TARGET/$f"
  done
done
find "$TARGET/.claude/hooks" -name '*.sh' -exec chmod +x {} +

# ---- 2. Design: kit defaults, then the project's design pack on top ------------------------------
( cd "$KIT_DIR/core" && find design -type f ) | while read -r f; do
  copy_always "$KIT_DIR/core/$f" "$TARGET/$f"
done
if [ -n "$PACK" ]; then
  echo "Design pack: $PACK"
  # A pack is a directory of files that land in design/, with two special cases:
  #   brand.css          appended to design/tokens.css as an override block (the usual case)
  #   design-system.md   replaces .claude/rules/design-system.md (the hex table for non-web output)
  # A pack that ships a full tokens.css replaces the kit's wholesale.
  ( cd "$PACK_DIR" && find . -type f ! -path './.git/*' ! -name 'brand.css' ! -name 'design-system.md' ! -name '.gitignore' ! -name '.gitattributes' ) | sed 's|^\./||' | while read -r f; do
    copy_always "$PACK_DIR/$f" "$TARGET/design/$f"
  done
  if [ -f "$PACK_DIR/brand.css" ]; then
    { echo; echo "/* ---- Brand overrides from design pack: $PACK ---- */"; tr -d '\r' < "$PACK_DIR/brand.css"; } >> "$TARGET/design/tokens.css"
    echo "  ~ design/tokens.css (+ brand.css from pack)"
  fi
  if [ -f "$PACK_DIR/design-system.md" ]; then
    kit_install "$PACK_DIR/design-system.md" "$TARGET/.claude/rules/design-system.md"
  fi
  PACK_REV=$(git -C "$PACK_DIR" describe --tags --always --dirty 2>/dev/null || echo "unversioned")
  printf '%s %s\n' "$PACK" "$PACK_REV" > "$TARGET/.claude/DESIGN_PACK"
fi
sort -u "$NEW_MANIFEST" > "$MANIFEST"; rm -f "$NEW_MANIFEST"

# ---- 3. STACK.md: one profile as-is, several stitched under one heading --------------------------
mkdir -p "$TARGET/docs"
if [ "$(printf '%s\n' "$PROFILES" | wc -l)" -eq 1 ]; then
  copy_always "$KIT_DIR/profiles/$PROFILES/docs/STACK.md" "$TARGET/docs/STACK.md"
else
  {
    echo "# Stack"
    echo
    echo "This project has more than one package, each on its own kit profile. The hooks run each package's"
    echo "tools from that package's directory (see \`.claude/kit.json\`). Sections below are the kit's profile"
    echo "notes; where a section's commands (uv, pnpm) differ from what a package actually uses, CLAUDE.md wins."
    echo
    echo "| Package | Profile |"
    echo "|---|---|"
    printf '%s\n' "$PACKAGES" | while IFS=$'\t' read -r p d; do echo "| \`$d\` | $p |"; done
    for p in $PROFILES; do echo; sed 's/^#/##/' "$KIT_DIR/profiles/$p/docs/STACK.md"; done
  } > "$TARGET/docs/STACK.md"
  echo "  ~ docs/STACK.md (combined: $(echo $PROFILES | tr ' ' ','))"
fi
copy_always "$KIT_DIR/core/.github/PULL_REQUEST_TEMPLATE.md" "$TARGET/.github/PULL_REQUEST_TEMPLATE.md"

# ---- 4. Merge settings.json ---------------------------------------------------------------------
# Permission lists are unioned, the project's scalar settings are kept as they are, and hooks are the
# kit's entries plus every entry the project wrote itself. A hook entry is the kit's when each of its
# commands runs a script the kit installs under .claude/hooks/; those are dropped from the project's
# side and re-added from core, so a refresh never duplicates them and a renamed kit hook goes away.
KIT_HOOK_PATHS="$OLD_KIT_HOOK_PATHS $(grep '^\.claude/hooks/' "$MANIFEST" || true)"
$PY - "$KIT_DIR/core/.claude/settings.json" "$TARGET/.claude/settings.json" "$KIT_HOOK_PATHS" <<'PY'
import json, os, re, sys
core, out, kit_hook_paths = sys.argv[1], sys.argv[2], set(sys.argv[3].split())
def load(p): return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
existing, kit = load(out), load(core)

# Rules the kit used to ship and has since replaced. The merge keeps a project's own rules, so without
# this list a retired kit rule would survive every refresh. Read(./.env.*) also matched .env.example,
# which the secrets rule tells Claude to read; the length-based .env patterns in core replace it.
RETIRED = {"Read(./.env.*)"}
# `bash .claude/hooks/x.sh`, or the form Claude Code's docs recommend, `bash "$CLAUDE_PROJECT_DIR"/.claude/...`.
KIT_COMMAND = re.compile(r'bash\s+"?(?:\$\{?CLAUDE_PROJECT_DIR\}?"?/)?(\.claude/hooks/[^"\s]+)"?')

def kit_authored(entry):
    commands = [h.get("command", "") for h in entry.get("hooks", [])]
    for c in commands:
        m = KIT_COMMAND.fullmatch(c.strip())
        if not m or m.group(1) not in kit_hook_paths:
            return False
    return bool(commands)

merged = {k: v for k, v in existing.items() if k not in ("permissions", "hooks")}
merged.update({k: v for k, v in kit.items() if k not in ("permissions", "hooks")})

permissions = dict(existing.get("permissions", {}))
for kind, value in kit.get("permissions", {}).items():
    current = permissions.get(kind)
    if isinstance(value, list) and (current is None or isinstance(current, list)):
        permissions[kind] = list(current or []) + [r for r in value if r not in (current or [])]
    elif current is None:
        permissions[kind] = value
for kind, value in permissions.items():
    if isinstance(value, list):
        permissions[kind] = [r for r in value if r not in RETIRED]
if permissions:
    merged["permissions"] = permissions

hooks = {event: list(entries) for event, entries in kit.get("hooks", {}).items()}
for event, entries in existing.get("hooks", {}).items():
    for entry in entries:
        if not kit_authored(entry) and entry not in hooks.setdefault(event, []):
            hooks[event].append(entry)
merged["hooks"] = hooks

os.makedirs(os.path.dirname(out), exist_ok=True)
# newline="\n": a Windows Python writes CRLF in text mode, and this file lives in LF projects.
with open(out, "w", encoding="utf-8", newline="\n") as f:
    json.dump(merged, f, indent=2); f.write("\n")
print("  ~ .claude/settings.json (merged)")
PY

# ---- 5. Project-owned files: offered on the first apply, then never touched again -------------------
# Templates a project deletes (say, docs/DECISIONS/ when it keeps ADRs in docs/adr/) must stay deleted,
# so everything in this section except kit.json and the per-package version pins is skipped once
# .claude/KIT_VERSION exists.
echo "Project files (created if missing):"
if [ ! -f "$KIT_JSON" ]; then
  printf '%s\n' "$PACKAGES" | $PY -c '
import json, sys
pk = [dict(zip(("profile", "path"), line.split("\t"))) for line in sys.stdin.read().splitlines() if line]
cfg = {"packages": pk, "design": {"pack": "", "exempt": []}, "protected_branches": ["main", "master"]}
with open(sys.argv[1], "w", newline="\n") as f:
    json.dump(cfg, f, indent=2); f.write("\n")' "$KIT_JSON"
  echo "  + .claude/kit.json"
fi
if [ "$FIRST_APPLY" -eq 1 ]; then
  copy_if_missing "$KIT_DIR/core/CLAUDE.md"      "$TARGET/CLAUDE.md"
  copy_if_missing "$KIT_DIR/core/README.md"      "$TARGET/README.md"
  copy_if_missing "$KIT_DIR/core/.env.example"   "$TARGET/.env.example"
  copy_if_missing "$KIT_DIR/core/.gitattributes" "$TARGET/.gitattributes"
  for f in ARCHITECTURE.md PLAN.md CHANGELOG.md DECISIONS/README.md DECISIONS/0000-template.md; do
    copy_if_missing "$KIT_DIR/core/docs/$f" "$TARGET/docs/$f"
  done
fi
# `|| continue`, never `[ -f ] && copy` as the last command of a loop body: under set -e and pipefail a
# false test there ends the loop non-zero, and a profile without .python-version (typescript) last in
# the spec used to stop the whole script here with no message.
printf '%s\n' "$PACKAGES" | while IFS=$'\t' read -r p d; do
  for f in .nvmrc .python-version; do
    [ -f "$KIT_DIR/profiles/$p/$f" ] || continue
    copy_if_missing "$KIT_DIR/profiles/$p/$f" "$TARGET/$d/$f"
  done
done
# CI is generated once from the profiles' job fragments and is the project's from then on.
if [ "$FIRST_APPLY" -eq 1 ] && [ ! -f "$TARGET/.github/workflows/ci.yml" ]; then
  mkdir -p "$TARGET/.github/workflows"
  {
    printf 'name: CI\non:\n  pull_request:\n  push:\n    branches: [main]\njobs:\n'
    printf '%s\n' "$PACKAGES" | while IFS=$'\t' read -r p d; do
      job="$p"; [ "$d" != "." ] && job="$p-$(echo "$d" | tr -c 'A-Za-z0-9\n' '-')"
      sed "s|__JOB__|$job|g; s|__PATH__|$d|g" "$KIT_DIR/profiles/$p/ci-job.yml"
    done
  } > "$TARGET/.github/workflows/ci.yml"
  echo "  + .github/workflows/ci.yml"
fi
# .gitignore: created whole on a new project; on an existing one the kit's own entries are appended once.
# core/.gitignore carries the same marker, so a project created whole is not appended to on update.
KIT_IGNORE_MARK="# --- claude-dev-kit ---"
if [ ! -f "$TARGET/.gitignore" ]; then
  tr -d '\r' < "$KIT_DIR/core/.gitignore" > "$TARGET/.gitignore"
  for p in $PROFILES; do
    [ -f "$KIT_DIR/profiles/$p/.gitignore.append" ] || continue
    { echo; tr -d '\r' < "$KIT_DIR/profiles/$p/.gitignore.append"; } >> "$TARGET/.gitignore"
  done
  echo "  + .gitignore"
elif ! grep -qF "$KIT_IGNORE_MARK" "$TARGET/.gitignore"; then
  printf '\n%s\n# Per-person settings and the /tdd full scope marker; both local only.\n.claude/settings.local.json\n.claude/test-scope\n.claude/agent-memory-local/\n' "$KIT_IGNORE_MARK" >> "$TARGET/.gitignore"
  echo "  ~ .gitignore (+ kit entries)"
fi

# ---- 6. Fill in name and profiles on first creation ----------------------------------------------
if [ "$UPDATE" -eq 0 ]; then
  PROFILE_LIST=$(echo $PROFILES | tr ' ' ',')
  ESCAPED_NAME=$(sed_escape "$NAME")
  sed -i.bak "s/<project name>/$ESCAPED_NAME/; s/<typescript | python | scripts>/$PROFILE_LIST/" "$TARGET/CLAUDE.md" && rm -f "$TARGET/CLAUDE.md.bak"
  sed -i.bak "s/<Project name>/$ESCAPED_NAME/" "$TARGET/README.md" && rm -f "$TARGET/README.md.bak"
  if [ "$ONLY_SCRIPTS" -eq 1 ]; then
    sed -i.bak 's/^- \*\*project_size:\*\* full/- **project_size:** small/' "$TARGET/CLAUDE.md" && rm -f "$TARGET/CLAUDE.md.bak"
  fi
  [ -d "$TARGET/.git" ] || (cd "$TARGET" && git init -q -b main && echo "  + git init (main)")
fi

# ---- 7. Record kit version -----------------------------------------------------------------------
KIT_VERSION=$(cd "$KIT_DIR" && git describe --tags --always --dirty 2>/dev/null || echo "unversioned")
echo "$KIT_VERSION" > "$TARGET/.claude/KIT_VERSION"

echo
if [ "$UPDATE" -eq 1 ]; then
  echo "Updated standards to kit $KIT_VERSION. Review 'git diff .claude/ design/ docs/STACK.md' and commit."
else
  echo "Created. Next:"
  echo "  1. cd $TARGET && open CLAUDE.md, fill in Purpose and Owner"
  echo "  2. Set up each package per docs/STACK.md (pnpm init / uv init)"
  echo "  3. git add -A && git commit -m 'chore: scaffold from claude-dev-kit $KIT_VERSION'"
  echo "  4. Start Claude Code and run /plan-project"
fi
