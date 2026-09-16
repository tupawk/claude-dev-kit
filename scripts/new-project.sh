#!/usr/bin/env bash
# Assemble a new project from core + one stack profile.
#
#   scripts/new-project.sh <profile> <target-dir> [project-name]
#   scripts/new-project.sh typescript ../my-app "My App"
#
# Profiles: typescript | python | scripts
# Safe to re-run on an existing project to pull in updated standards:
# it overwrites .claude/, design/ (tokens, README, image checker, any logo files), and docs/STACK.md, and never
# touches CLAUDE.md, README.md, docs/PLAN.md, docs/ARCHITECTURE.md, or code
# once they exist.
set -euo pipefail

KIT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="${1:-}"
TARGET="${2:-}"
NAME="${3:-$(basename "${TARGET:-project}")}"

usage() { sed -n '2,12p' "$0"; exit 1; }
[ -z "$PROFILE" ] || [ -z "$TARGET" ] && usage
[ -d "$KIT_DIR/profiles/$PROFILE" ] || { echo "Unknown profile: $PROFILE"; usage; }

mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"
UPDATE=0
[ -f "$TARGET/CLAUDE.md" ] && UPDATE=1

copy_if_missing() { # src dst
  if [ ! -e "$2" ]; then mkdir -p "$(dirname "$2")"; cp "$1" "$2"; echo "  + ${2#$TARGET/}"; fi
}
copy_always() {
  mkdir -p "$(dirname "$2")"; cp "$1" "$2"; echo "  ~ ${2#$TARGET/}"
}

echo "Assembling $NAME ($PROFILE) in $TARGET"

# 1. Standards that the kit owns: always refreshed
echo "Standards (kit-owned, refreshed):"
rm -rf "$TARGET/.claude/agents" "$TARGET/.claude/skills" "$TARGET/.claude/rules" "$TARGET/.claude/hooks"
for src in "$KIT_DIR/core" "$KIT_DIR/profiles/$PROFILE"; do
  ( cd "$src" && find .claude -type f ! -name settings.json ) | while read -r f; do
    copy_always "$src/$f" "$TARGET/$f"
  done
done
( cd "$KIT_DIR/core" && find design -type f ) | while read -r f; do
  copy_always "$KIT_DIR/core/$f" "$TARGET/$f"
done
copy_always "$KIT_DIR/profiles/$PROFILE/docs/STACK.md" "$TARGET/docs/STACK.md"
copy_always "$KIT_DIR/core/.github/PULL_REQUEST_TEMPLATE.md" "$TARGET/.github/PULL_REQUEST_TEMPLATE.md"
copy_always "$KIT_DIR/profiles/$PROFILE/.github/workflows/ci.yml" "$TARGET/.github/workflows/ci.yml"
chmod +x "$TARGET"/.claude/hooks/*.sh

# 2. Merge settings.json (core + profile). Preserves an existing project's extra keys.
PY=""; for c in python3 python "py -3"; do case "$(command -v "${c%% *}" 2>/dev/null)" in *WindowsApps*) continue;; esac; $c -c "import sys; sys.exit(sys.version_info[0] != 3)" >/dev/null 2>&1 && { PY="$c"; break; }; done  # skip the slow, non-functional Windows Store stubs
[ -n "$PY" ] || { echo "Error: no working Python 3 found (tried python3, python, py -3). Install Python 3 or fix the PATH." >&2; exit 1; }
$PY - "$KIT_DIR/core/.claude/settings.json" "$KIT_DIR/profiles/$PROFILE/.claude/settings.json" "$TARGET/.claude/settings.json" <<'PY'
import json, sys, os
core, prof, out = sys.argv[1:4]
def load(p): return json.load(open(p)) if os.path.exists(p) else {}
existing = load(out)
merged = {}
for src in (existing, load(core), load(prof)):
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
json.dump(merged, open(out, "w"), indent=2); open(out, "a").write("\n")
print("  ~ .claude/settings.json (merged)")
PY

# 3. Project-owned files: created once, never overwritten
echo "Project files (created if missing):"
copy_if_missing "$KIT_DIR/core/CLAUDE.md"   "$TARGET/CLAUDE.md"
copy_if_missing "$KIT_DIR/core/README.md"   "$TARGET/README.md"
copy_if_missing "$KIT_DIR/core/.env.example" "$TARGET/.env.example"
copy_if_missing "$KIT_DIR/core/.gitattributes" "$TARGET/.gitattributes"
for f in ARCHITECTURE.md PLAN.md CHANGELOG.md DECISIONS/README.md DECISIONS/0000-template.md; do
  copy_if_missing "$KIT_DIR/core/docs/$f" "$TARGET/docs/$f"
done
for f in .nvmrc .python-version; do
  [ -f "$KIT_DIR/profiles/$PROFILE/$f" ] && copy_if_missing "$KIT_DIR/profiles/$PROFILE/$f" "$TARGET/$f"
done
if [ ! -f "$TARGET/.gitignore" ]; then
  cat "$KIT_DIR/core/.gitignore" > "$TARGET/.gitignore"
  [ -f "$KIT_DIR/profiles/$PROFILE/.gitignore.append" ] && { echo; cat "$KIT_DIR/profiles/$PROFILE/.gitignore.append"; } >> "$TARGET/.gitignore"
  echo "  + .gitignore"
fi

# 4. Fill in name and profile on first creation
if [ "$UPDATE" -eq 0 ]; then
  sed -i.bak "s/<project name>/$NAME/; s/<typescript | python | scripts>/$PROFILE/" "$TARGET/CLAUDE.md" && rm -f "$TARGET/CLAUDE.md.bak"
  sed -i.bak "s/<Project name>/$NAME/" "$TARGET/README.md" && rm -f "$TARGET/README.md.bak"
  [ "$PROFILE" = "scripts" ] && sed -i.bak 's/^- \*\*project_size:\*\* full/- **project_size:** small/' "$TARGET/CLAUDE.md" && rm -f "$TARGET/CLAUDE.md.bak"
  [ -d "$TARGET/.git" ] || (cd "$TARGET" && git init -q -b main && echo "  + git init (main)")
fi

# 5. Record kit version
KIT_VERSION=$(cd "$KIT_DIR" && git describe --tags --always 2>/dev/null || echo "unversioned")
echo "$KIT_VERSION" > "$TARGET/.claude/KIT_VERSION"

echo
if [ "$UPDATE" -eq 1 ]; then
  echo "Updated standards to kit $KIT_VERSION. Review 'git diff .claude/ design/ docs/STACK.md' and commit."
else
  echo "Created. Next:"
  echo "  1. cd $TARGET && open CLAUDE.md, fill in Purpose and Owner"
  echo "  2. Set up the stack per docs/STACK.md (pnpm init / uv init)"
  echo "  3. git add -A && git commit -m 'chore: scaffold from claude-dev-kit $KIT_VERSION'"
  echo "  4. Start Claude Code and run /plan-project"
fi
