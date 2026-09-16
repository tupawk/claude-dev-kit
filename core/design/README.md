# Design system

`tokens.css` is the only place colors, type, spacing, radii, and shadows are defined. Components consume the semantic variables (`--color-primary`, `--space-4`), not the raw palette (`--brand-primary`).

Rules of use are in `.claude/rules/frontend.md`, loaded automatically when frontend files are touched. A PreToolUse hook blocks hex colour literals written anywhere outside this directory.

## Making it yours

The palette that ships with the kit is a neutral placeholder. To adopt your own colours:

1. Edit the `--brand-*` values at the top of `tokens.css`. Keep the roles (dark, primary, accent, highlight, two grays); change the hex.
2. Re-measure contrast (see below) and adjust the notes in this file and in `.claude/rules/design-system.md`.
3. If you have a logo, drop the files into `design/logo/` and write a short `design/logo/README.md` saying which file goes on which background and the native aspect ratio of each.
4. Change `--font-sans` if you use a different typeface.

Everything else (hook, frontend rule, Definition of Done) reads from these files and needs no change.

## Framework integration

- Plain CSS: `@import "./design/tokens.css";` at the root stylesheet.
- Tailwind: map `theme.extend.colors` and `spacing` to the variables (`primary: "var(--color-primary)"`) so utility classes stay on-token.
- Component libraries (shadcn, MUI, etc.): configure the theme from these variables at setup. Do not override per component.

## Logo

If the project has a logo, its files live in `design/logo/`. Use SVG where the medium allows, set width only (`height: auto`), no effects, never recreate it from text or shapes. `design/check_logo_aspect.py` flags any stretched image in a `.pptx` or `.docx`; run it before delivering a document or deck.

## Colour and contrast

Not every colour works as text on every surface. Measured WCAG contrast ratios for the placeholder palette (recompute after you change it):

| Colour | On white | On `#F5F7FA` | On dark `#1F2933` |
|---|---|---|---|
| Primary `#2F6FED` | 4.5 (AA for normal text, borderline) | 4.2 (large text and UI) | 3.2 (UI only; `.inverse` swaps in a lighter primary at 6.1) |
| Accent `#D9480F` | 4.3 (large text and UI only) | 4.0 (large text only) | 3.4 (UI only) |
| Highlight `#F5B942` | 1.8 (never as text) | 1.6 (never as text) | 8.4 (fine) |
| Gray 700 `#52606D` | 6.5 (body text) | 6.0 (body text) | 2.3 (never) |
| Gray 500 `#9AA5B1` | 2.5 (decorative only) | 2.3 (decorative only) | 5.9 (secondary text) |

Body copy on light surfaces uses `--color-text-body` (`#212121`) and headings `--color-text-heading`. Primary and accent are for interactive elements, big stats, and headings at 24px or larger. Highlight is a dark-surface colour.

To measure a new pair, use any WCAG contrast checker, or this snippet (Python 3):

```python
def luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4))
    lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

print(round(contrast("#2F6FED", "#FFFFFF"), 2))  # 4.5
```

## Non-web deliverables

Documents, decks, spreadsheets, PDFs, and emails produced by a project follow the same palette, type, and logo rules. `.claude/rules/design-system.md` carries the hex values and code patterns for tools that cannot read CSS variables.

## Typography

Inter by default, with a system-font fallback. Load weights 300, 400, 500, and 700 (variable font preferred). Display type is light, headings are bold.
