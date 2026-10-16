#!/usr/bin/env bash
# PreToolUse hook for Edit, Write, MultiEdit and NotebookEdit. Blocks hex colour literals written into
# frontend files. Colours come from design/tokens.css (var(--brand-*), var(--color-*)); the frontend rule
# says so and this hook makes it deterministic. Exit 2 blocks the write and returns stderr to Claude.
#
# The decision is kit.py's `guard-colours`.
# In scope:  *.css *.scss *.tsx *.jsx *.vue *.svelte *.html, and anything under src/components, src/app,
#            src/pages, src/ui, templates.
# Exempt:    the top-level design/ (tokens.css is where hex belongs) and .claude/, node_modules anywhere,
#            *.svg, any line carrying a "brand-exception:" comment with a reason, and every path matched by
#            "design.exempt" in .claude/kit.json (a vendored theme, a stylesheet that is itself a token
#            source). Not colours: anchors (href="#add") and an all-digit #123 or #1001 outside a CSS value.
INPUT=$(cat)
. "$(dirname "$0")/lib.sh"
if [ -z "$KIT_PY" ] || [ ! -f "$KIT_LIB_DIR/kit.py" ]; then
  echo "Blocked by the design-token hook: no working Python 3 on PATH, or kit.py missing beside lib.sh, so the tool input cannot be parsed. Fix the environment; do not bypass the hook." >&2; exit 2
fi
RESULT=$(printf '%s' "$INPUT" | kit guard-colours 2>/dev/null) || {
  echo "Blocked by the design-token hook: could not parse the tool input. Fix the environment; do not bypass the hook." >&2; exit 2
}
[ -z "$RESULT" ] && exit 0
{
  echo "Blocked by the design-token hook: $RESULT"
  echo "Use the tokens in design/tokens.css: var(--brand-dark), var(--brand-primary), var(--brand-accent), var(--brand-highlight), var(--brand-gray-700), var(--brand-gray-500), or a semantic role such as var(--color-primary). New colours are a design decision and go into tokens.css, not into a component."
  echo "If this exact literal is genuinely required (a third-party embed, an email client that ignores variables), add a comment on the same line: /* brand-exception: <reason> */ and mention it in the PR."
  echo "If the whole file is legitimately outside the design system (a vendored theme, a stylesheet that is itself a token source), add its path to design.exempt in .claude/kit.json and say why in the PR."
} >&2
exit 2
