---
paths:
  - "src/components/**"
  - "src/app/**"
  - "src/pages/**"
  - "src/ui/**"
  - "**/*.tsx"
  - "**/*.vue"
  - "**/*.svelte"
  - "**/*.css"
  - "**/*.scss"
  - "templates/**"
---
# Frontend and design-system rules

- Import `design/tokens.css` once at the root. Reference colors, spacing, radii, and type only through CSS variables or the framework theme built from them. No hex values, px font sizes, or ad hoc spacing in components. A PreToolUse hook blocks any hex colour literal written into a frontend file; `design/tokens.css` is the only place hex belongs. If a literal is genuinely unavoidable (third-party embed, email client), put `/* brand-exception: <reason> */` on the same line and call it out in the PR.
- Palette roles: `--brand-dark` for dominant dark surfaces and headers, `--brand-primary` for links, buttons, focus rings, and other interactive elements, `--brand-accent` for emphasis and primary CTAs only (one per view), `--brand-highlight` for callouts on dark surfaces, grays for secondary text, borders, and dividers. Never pair the accent against the highlight as a primary combination. Prefer the semantic roles (`--color-primary`, `--color-text-body`) over the raw palette.
- White text on the dark surface (`.inverse`) is the signature look for hero sections and headers.
- Logo: only the files in `design/logo/` (read its README if one exists). `<img class="logo" alt="<name>">`, width only (`height: auto`), never both dimensions, no effects, rotation, recoloring, or CSS filters. Never rebuild a logo from text or shapes, and never `preserveAspectRatio="none"` or `background-size: 100% 100%`.
- Contrast: the primary and accent sit near 4.5:1 and 4.3:1 on white, so use them for interactive elements, stats, and headings of 24px or more, not paragraphs. The highlight is never text on a light surface. Body copy uses `--color-text-body`. The table in `design/README.md` has the measured ratios.
- Type: the face in `--font-sans` with light (300) display headlines and bold (700) working headings, pill outline buttons (`.btn`), thin single-colour line icons in the primary colour, images with one rounded corner (`.img-rounded`), sections alternating dark / white / light gray. Headings on light backgrounds use `--color-text-heading`, body uses `--color-text-body`.
- Modern and restrained: generous whitespace, a clear type hierarchy, consistent 4px or 8px spacing grid, no card shadows heavier than `--shadow-sm`, no gradients or decorative shapes unless the plan calls for them.
- Accessibility: WCAG AA contrast, visible focus states, keyboard reachable controls, semantic elements, labels on every input, `alt` on every image, `prefers-reduced-motion` respected.
- Responsive by default. Mobile layout is designed, not an afterthought.
- Components are small, composable, and documented with a usage example. Shared components live in one place; do not fork a component to change a color.
