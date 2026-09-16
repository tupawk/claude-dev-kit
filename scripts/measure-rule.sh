#!/usr/bin/env bash
# Measure whether a standards change actually changes what Claude Code produces.
#
#   scripts/measure-rule.sh <project-dir> <task-file> [--overlay DIR] [--runs N] [--model M]
#
#   project-dir  a git repo scaffolded with the kit (a real project or a throwaway one)
#   task-file    a text file with one ticket, e.g. "Add a date picker to the item form"
#   --overlay    directory copied over the candidate arm's fresh copy before it runs,
#                e.g. a folder holding a new .claude/rules/engineering-principles.md.
#                Without it the baseline arm runs with .claude/ and CLAUDE.md removed,
#                so the comparison is "bare Claude Code" vs "the kit as-is".
#   --runs       runs per arm (default 2). Each run is a fresh clone and a fresh session.
#   --model      model alias or id passed to claude -p (default haiku, the cheap one)
#
# Each run: clone the project into a temp dir, apply the arm, run `claude -p` headless with
# only project settings loaded (no user-level plugins or settings can leak in), then count the
# added lines in `git diff`, and read cost, turns, and wall time from the JSON result.
# Prints per-run rows and a per-arm mean. Nothing is written to the project itself.
#
# Runs cost real money. Start with --runs 1 and haiku. The temp dirs are left in place
# (path printed) so the diffs can be read; delete them when done.
set -euo pipefail

PROJECT="${1:-}"; TASK="${2:-}"; shift 2 2>/dev/null || true
OVERLAY=""; RUNS=2; MODEL="haiku"
while [ $# -gt 0 ]; do
  case "$1" in
    --overlay) OVERLAY="$2"; shift 2;;
    --runs) RUNS="$2"; shift 2;;
    --model) MODEL="$2"; shift 2;;
    *) echo "Unknown argument: $1" >&2; exit 1;;
  esac
done
usage() { sed -n '2,20p' "$0"; exit 1; }
[ -d "$PROJECT/.git" ] && [ -f "$TASK" ] || usage
[ -z "$OVERLAY" ] || [ -d "$OVERLAY" ] || { echo "Overlay dir not found: $OVERLAY" >&2; exit 1; }
case "$RUNS" in ''|*[!0-9]*) echo "--runs must be a positive integer" >&2; exit 1;; esac
command -v claude >/dev/null 2>&1 || { echo "Error: claude CLI not on PATH" >&2; exit 1; }
PY=""; for c in python3 python "py -3"; do case "$(command -v "${c%% *}" 2>/dev/null)" in *WindowsApps*) continue;; esac; $c -c "import sys; sys.exit(sys.version_info[0] != 3)" >/dev/null 2>&1 && { PY="$c"; break; }; done  # skip the slow, non-functional Windows Store stubs
[ -n "$PY" ] || { echo "Error: no working Python 3 found (tried python3, python, py -3)." >&2; exit 1; }

PROJECT="$(cd "$PROJECT" && pwd)"
PROMPT="$(cat "$TASK")"
WORK="$(mktemp -d)"
RESULTS="$WORK/results.tsv"
printf 'arm\trun\tloc_added\tfiles\tcost_usd\tturns\tseconds\tdir\n' > "$RESULTS"

run_arm() { # arm run
  local arm="$1" n="$2" dir="$WORK/$1-$2"
  git clone -q --no-hardlinks "$PROJECT" "$dir"
  case "$arm" in
    baseline) [ -n "$OVERLAY" ] || rm -rf "$dir/.claude" "$dir/CLAUDE.md";;
    candidate) [ -n "$OVERLAY" ] && cp -R "$OVERLAY"/. "$dir/";;
  esac
  ( cd "$dir" && git add -A && git -c user.name=measure -c user.email=measure@local commit -qm "arm: $arm" --allow-empty )
  local start end json
  start=$(date +%s)
  # --setting-sources project: nothing from ~/.claude (plugins, user hooks) reaches the run.
  # --dangerously-skip-permissions is acceptable only because the clone is disposable;
  # the project's own PreToolUse hooks still run and still block destructive git.
  json=$( cd "$dir" && claude -p "$PROMPT" --model "$MODEL" --output-format json \
            --setting-sources project --dangerously-skip-permissions 2>"$dir/.stderr.log" || true )
  end=$(date +%s)
  printf '%s' "$json" > "$dir/.result.json"
  local stats
  stats=$( cd "$dir" && git add -A && git diff --cached --numstat -- . ':!.result.json' ':!.stderr.log' \
           | $PY -c 'import sys
add=files=0
for line in sys.stdin:
    a,_,_=line.split("\t",2)
    if a.isdigit(): add+=int(a); files+=1
print(f"{add}\t{files}")' )
  local meta
  meta=$( printf '%s' "$json" | $PY -c 'import sys, json
try: d=json.load(sys.stdin)
except Exception: d={}
cost = d.get("total_cost_usd", 0) or 0; turns = d.get("num_turns", 0) or 0
print("%.4f\t%s" % (cost, turns))' )
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$arm" "$n" "$stats" "$meta" "$((end-start))" "$dir" >> "$RESULTS"
  echo "  $arm run $n: loc=+${stats%%$'	'*} cost=\$${meta%%$'	'*} $((end-start))s"
}

echo "Task: $PROMPT"
echo "Model: $MODEL, runs per arm: $RUNS, work dir: $WORK"
[ -n "$OVERLAY" ] && echo "Candidate overlay: $OVERLAY" || echo "Baseline arm: project with .claude/ and CLAUDE.md removed"
for n in $(seq 1 "$RUNS"); do run_arm baseline "$n"; run_arm candidate "$n"; done

echo
$PY - "$RESULTS" <<'PY'
import sys, csv, statistics as st
rows = list(csv.DictReader(open(sys.argv[1]), delimiter="\t"))
print(f"{'arm':<10}{'runs':>5}{'loc_added':>11}{'files':>7}{'cost_usd':>10}{'turns':>7}{'seconds':>9}")
for arm in ("baseline", "candidate"):
    r = [x for x in rows if x["arm"] == arm]
    if not r: continue
    m = lambda k: st.mean(float(x[k]) for x in r)
    print(f"{arm:<10}{len(r):>5}{m('loc_added'):>11.1f}{m('files'):>7.1f}{m('cost_usd'):>10.4f}{m('turns'):>7.1f}{m('seconds'):>9.0f}")
print(f"\nPer-run rows and each run's clone are under: {sys.argv[1].rsplit('/',1)[0]}")
print("Read the diffs (git diff --cached in each clone) before trusting the numbers; LOC is a proxy, not the goal.")
PY
