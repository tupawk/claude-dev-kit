#!/usr/bin/env bash
# PreToolUse hook for Edit and Write. Blocks hex colour literals written into frontend files.
# Colours come from design/tokens.css (var(--brand-*), var(--color-*)); the frontend rule says so and
# this hook makes it deterministic. Exit 2 blocks the write and returns stderr to Claude.
#
# In scope:  *.css *.scss *.tsx *.jsx *.vue *.svelte *.html, and anything under src/components, src/app,
#            src/pages, src/ui, templates.
# Exempt:    design/ (tokens.css is where hex belongs), *.svg, node_modules, .claude/, any line carrying a
#            "brand-exception:" comment with a reason, and every path matched by a glob in
#            "design.exempt" in .claude/kit.json (a vendored theme, a third-party stylesheet, a legacy
#            token file that is itself the source of truth for its app).
INPUT=$(cat)
. "$(dirname "$0")/lib.sh"
if [ -z "$KIT_PY" ]; then
  echo "Blocked by the design-token hook: no working Python 3 on PATH, so the tool input cannot be parsed. Fix the environment; do not bypass the hook." >&2; exit 2
fi
RESULT=$(printf '%s' "$INPUT" | $KIT_PY -c '
import sys, json, os, re
sys.path.insert(0, os.environ.get("KIT_LIB_DIR") or os.path.join(".claude", "hooks"))
import kit
d = json.load(sys.stdin)
ti = d.get("tool_input", {})
path = ti.get("file_path", "")
content = ti.get("content", "") or ti.get("new_string", "") or ""
if not path or not content:
    print("OK"); sys.exit(0)
rel = kit.rel(path)
low = rel.lower()
exempt_dirs = ("design/", "node_modules/", ".claude/")
if low.startswith(exempt_dirs) or any("/" + e in low for e in exempt_dirs) or low.endswith(".svg"):
    print("OK"); sys.exit(0)
if kit.design_exempt(kit.load(), rel):
    print("OK"); sys.exit(0)
in_scope_ext = (".css", ".scss", ".tsx", ".jsx", ".vue", ".svelte", ".html")
in_scope_dirs = ("src/components/", "src/app/", "src/pages/", "src/ui/", "templates/")
if not (low.endswith(in_scope_ext) or any(low.startswith(p) or "/" + p in low for p in in_scope_dirs)):
    print("OK"); sys.exit(0)
# A hex colour: # followed by 3, 4, 6, or 8 hex digits and then a non-word character.
hex_re = re.compile(r"(?<![\w&])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])")
hits = []
for n, line in enumerate(content.splitlines(), 1):
    if "brand-exception:" in line:
        continue
    if hex_re.findall(line):
        hits.append(f"  line {n}: {line.strip()[:110]}")
if hits:
    print("HIT " + rel); print("\n".join(hits[:6]))
    if len(hits) > 6: print(f"  ... and {len(hits) - 6} more")
else:
    print("OK")
' 2>/dev/null) || RESULT="__KIT_PARSE_ERROR__"

if [ "$RESULT" = "__KIT_PARSE_ERROR__" ]; then
  echo "Blocked by the design-token hook: could not parse the tool input (is a working Python 3 on PATH?). Fix the environment; do not bypass the hook." >&2; exit 2
fi
case "$RESULT" in
  OK) exit 0 ;;
  HIT*)
    FILE=${RESULT%%$'\n'*}; FILE=${FILE#HIT }
    {
      echo "Blocked by the design-token hook: hardcoded colour in $FILE."
      echo "${RESULT#*$'\n'}"
      echo "Use the tokens in design/tokens.css: var(--brand-dark), var(--brand-primary), var(--brand-accent), var(--brand-highlight), var(--brand-gray-700), var(--brand-gray-500), or a semantic role such as var(--color-primary). New colours are a design decision and go into tokens.css, not into a component."
      echo "If this exact literal is genuinely required (a third-party embed, an email client that ignores variables), add a comment on the same line: /* brand-exception: <reason> */ and mention it in the PR."
      echo "If the whole file is legitimately outside the design system (a vendored theme, a stylesheet that is itself a token source), add its path to design.exempt in .claude/kit.json and say why in the PR."
    } >&2
    exit 2 ;;
  *) exit 0 ;;
esac
