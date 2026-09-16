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
# Safe to re-run. The kit owns and refreshes .claude/ (agents, skills, rules, hooks), design/ (tokens,
# README, image checker, any pack files), docs/STACK.md and the PR template. It never touches
# CLAUDE.md, README.md, .claude/kit.json, .github/workflows/ci.yml, docs/PLAN.md, docs/ARCHITECTURE.md
# or code once they exist. Project settings in .claude/kit.json (packages, design pack, design
# exemptions, protected branches) are read on every run; edit that file, then run `update`.
set -euo pipefail

KIT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-}"
TARGET="${2:-}"

usage() { sed -n '2,16p' "$0"; exit 1; }
[ -z "$MODE" ] || [ -z "$TARGET" ] && usage

PY=""; for c in python3 python "py -3"; do case "$(command -v "${c%% *}" 2>/dev/null)" in *WindowsApps*) continue;; esac; $c -c "import sys; sys.exit(sys.version_info[0] != 3)" >/dev/null 2>&1 && { PY="$c"; break; }; done  # skip the slow, non-functional Windows Store stubs
[ -n "$PY" ] || { echo "Error: no working Python 3 found (tried python3, python, py -3). Install Python 3 or fix the PATH." >&2; exit 1; }

mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"
KIT_JSON="$TARGET/.claude/kit.json"
UPDATE=0; [ -f "$TARGET/CLAUDE.md" ] && UPDATE=1                # an existing project, not a blank directory
FIRST_APPLY=1; [ -f "$TARGET/.claude/KIT_VERSION" ] && FIRST_APPLY=0   # the kit has been here before

# ---- Resolve the package list: "<profile>\t<path>" per line -------------------------------------
if [ "$MODE" = "update" ]; then
  [ -f "$KIT_JSON" ] || { echo "Error: $KIT_JSON not found. Run with a <spec> the first time." >&2; exit 1; }
  NAME="${3:-$(basename "$TARGET")}"
  PACKAGES=$(cd "$TARGET" && $PY "$KIT_DIR/core/.claude/hooks/kit.py" packages)
else
  [ -f "$KIT_JSON" ] && { echo "Error: $KIT_JSON already exists. Edit it and run: $0 update $TARGET" >&2; exit 1; }
  NAME="${3:-$(basename "$TARGET")}"
  PACKAGES=""
  IFS=',' read -ra SPECS <<< "$MODE"
  for s in "${SPECS[@]}"; do
    p="${s%%=*}"; d="${s#*=}"; [ "$d" = "$s" ] && d="."
    [ -d "$KIT_DIR/profiles/$p" ] || { echo "Unknown profile: $p" >&2; usage; }
    d="${d#./}"; d="${d%/}"; [ -z "$d" ] && d="."
    LINE=$(printf '%s\t%s' "$p" "$d")
    PACKAGES="${PACKAGES}${PACKAGES:+
}${LINE}"
  done
fi
PROFILES=$(printf '%s\n' "$PACKAGES" | cut -f1 | awk '!seen[$0]++')
ONLY_SCRIPTS=1; for p in $PROFILES; do [ "$p" = "scripts" ] || ONLY_SCRIPTS=0; done

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

echo "Assembling $NAME in $TARGET"
printf '%s\n' "$PACKAGES" | while IFS=$'\t' read -r p d; do echo "  package: $p at $d"; done

# ---- 1. Standards that the kit owns: always refreshed --------------------------------------------
echo "Standards (kit-owned, refreshed):"
rm -rf "$TARGET/.claude/agents" "$TARGET/.claude/skills" "$TARGET/.claude/rules" "$TARGET/.claude/hooks"
( cd "$KIT_DIR/core" && find .claude -type f ! -name settings.json ! -path '*/__pycache__/*' ) | while read -r f; do
  copy_always "$KIT_DIR/core/$f" "$TARGET/$f"
done
for p in $PROFILES; do
  ( cd "$KIT_DIR/profiles/$p" && find .claude -type f ! -path '*/__pycache__/*' ) | while read -r f; do
    copy_always "$KIT_DIR/profiles/$p/$f" "$TARGET/$f"
  done
done
find "$TARGET/.claude/hooks" -name '*.sh' -exec chmod +x {} +

# ---- 2. Design: kit defaults, then the project's design pack on top ------------------------------
( cd "$KIT_DIR/core" && find design -type f ) | while read -r f; do
  copy_always "$KIT_DIR/core/$f" "$TARGET/$f"
done
PACK=""
[ -f "$KIT_JSON" ] && PACK=$($PY -c 'import json,sys; print(json.load(open(sys.argv[1])).get("design",{}).get("pack",""))' "$KIT_JSON")
if [ -n "$PACK" ]; then
  case "$PACK" in
    http://*|https://*|git@*|ssh://*)
      PACK_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/claude-dev-kit/packs/$(basename "${PACK%.git}")"
      if [ -d "$PACK_DIR/.git" ]; then git -C "$PACK_DIR" pull -q --ff-only; else mkdir -p "$(dirname "$PACK_DIR")"; git clone -q "$PACK" "$PACK_DIR"; fi ;;
    *) PACK_DIR="$(cd "$TARGET" && cd "$PACK" 2>/dev/null && pwd)" || { echo "Error: design pack '$PACK' (from .claude/kit.json) not found relative to $TARGET" >&2; exit 1; } ;;
  esac
  echo "Design pack: $PACK"
  # A pack is a directory of files that land in design/, with two special cases:
  #   brand.css          appended to design/tokens.css as an override block (the usual case)
  #   design-system.md   replaces .claude/rules/design-system.md (the hex table for non-web output)
  # A pack that ships a full tokens.css replaces the kit's wholesale.
  ( cd "$PACK_DIR" && find . -type f ! -path './.git/*' ! -name 'brand.css' ! -name 'design-system.md' ! -name '.gitignore' ! -name '.gitattributes' ) | sed 's|^\./||' | while read -r f; do
    copy_always "$PACK_DIR/$f" "$TARGET/design/$f"
  done
  if [ -f "$PACK_DIR/brand.css" ]; then
    { echo; echo "/* ---- Brand overrides from design pack: $PACK ---- */"; cat "$PACK_DIR/brand.css"; } >> "$TARGET/design/tokens.css"
    echo "  ~ design/tokens.css (+ brand.css from pack)"
  fi
  [ -f "$PACK_DIR/design-system.md" ] && copy_always "$PACK_DIR/design-system.md" "$TARGET/.claude/rules/design-system.md"
  PACK_REV=$(git -C "$PACK_DIR" describe --tags --always --dirty 2>/dev/null || echo "unversioned")
  printf '%s %s\n' "$PACK" "$PACK_REV" > "$TARGET/.claude/DESIGN_PACK"
fi

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

# ---- 4. Merge settings.json. Preserves an existing project's extra keys; the kit owns hooks. ------
$PY - "$KIT_DIR/core/.claude/settings.json" "$TARGET/.claude/settings.json" <<'PY'
import json, sys, os
core, out = sys.argv[1:3]
def load(p): return json.load(open(p)) if os.path.exists(p) else {}
existing = load(out)
merged = {}
for src in (existing, load(core)):
    for k, v in src.items():
        if k == "hooks":
            merged.setdefault("hooks", {})
            for ev, entries in v.items():
                if src is existing: continue          # kit owns hooks; drop stale ones
                merged["hooks"].setdefault(ev, []).extend(entries)
        elif k == "permissions":
            merged.setdefault("permissions", {})
            for kind, rules in v.items():
                cur = merged["permissions"].setdefault(kind, [])
                for r in rules:
                    if r not in cur: cur.append(r)
        else:
            merged[k] = v
os.makedirs(os.path.dirname(out), exist_ok=True)
# newline="\n": a Windows Python writes CRLF in text mode, and this file lives in LF projects.
with open(out, "w", newline="\n") as f:
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
printf '%s\n' "$PACKAGES" | while IFS=$'\t' read -r p d; do
  for f in .nvmrc .python-version; do
    [ -f "$KIT_DIR/profiles/$p/$f" ] && copy_if_missing "$KIT_DIR/profiles/$p/$f" "$TARGET/$d/$f"
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
KIT_IGNORE_MARK="# --- claude-dev-kit ---"
if [ ! -f "$TARGET/.gitignore" ]; then
  cat "$KIT_DIR/core/.gitignore" > "$TARGET/.gitignore"
  for p in $PROFILES; do [ -f "$KIT_DIR/profiles/$p/.gitignore.append" ] && { echo; cat "$KIT_DIR/profiles/$p/.gitignore.append"; } >> "$TARGET/.gitignore"; done
  echo "  + .gitignore"
elif ! grep -qF "$KIT_IGNORE_MARK" "$TARGET/.gitignore"; then
  printf '\n%s\n# Per-person settings and the /tdd full scope marker; both local only.\n.claude/settings.local.json\n.claude/test-scope\n.claude/agent-memory-local/\n' "$KIT_IGNORE_MARK" >> "$TARGET/.gitignore"
  echo "  ~ .gitignore (+ kit entries)"
fi

# ---- 6. Fill in name and profiles on first creation ----------------------------------------------
if [ "$UPDATE" -eq 0 ]; then
  PROFILE_LIST=$(echo $PROFILES | tr ' ' ',')
  sed -i.bak "s/<project name>/$NAME/; s/<typescript | python | scripts>/$PROFILE_LIST/" "$TARGET/CLAUDE.md" && rm -f "$TARGET/CLAUDE.md.bak"
  sed -i.bak "s/<Project name>/$NAME/" "$TARGET/README.md" && rm -f "$TARGET/README.md.bak"
  [ "$ONLY_SCRIPTS" -eq 1 ] && sed -i.bak 's/^- \*\*project_size:\*\* full/- **project_size:** small/' "$TARGET/CLAUDE.md" && rm -f "$TARGET/CLAUDE.md.bak"
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
