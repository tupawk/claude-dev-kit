# Design system: anything a user will see

Applies to every user-facing output a project produces, not only web UI: Word and PDF documents, PowerPoint decks, Excel workbooks, HTML or email reports, charts, CLI banners, and generated images. Web components additionally follow `.claude/rules/frontend.md`.

## Palette (hex, for tools that cannot read `design/tokens.css`)

These values mirror the `--brand-*` tokens in `design/tokens.css`. If the tokens change, update this table in the same commit.

| Role | Token | Hex |
|---|---|---|
| Dominant dark: headers, title slides, footers, table header rows | `--brand-dark` | `#1F2933` |
| Interactive, links, icons, chart series 1 | `--brand-primary` | `#2F6FED` |
| Emphasis and the one call to action per view; big stat numbers | `--brand-accent` | `#D9480F` |
| Callouts and emphasized words on dark surfaces only | `--brand-highlight` | `#F5B942` |
| Secondary text, dividers | `--brand-gray-700` | `#52606D` |
| Borders, tertiary, muted labels | `--brand-gray-500` | `#9AA5B1` |
| Light section background | `--brand-gray-100` | `#F5F7FA` |
| Headings on light surfaces | `--brand-ink-heading` | `#1F2933` |
| Body copy on light surfaces | `--brand-ink-body` | `#212121` |

The dark colour dominates. The accent is scarce on purpose. Never pair the accent against the highlight. No colours outside this table; if a chart needs more series, use tints of the primary and the grays, never new hues.

## Type

The face named in `--font-sans` (Inter by default): light (300) for display headlines and big numbers, bold (700) for working headings, regular (400) for body. In Office files, set the face and accept the fallback (Arial) on machines without it; do not substitute another display face.

## Logo and images

If the project has a logo, its files live in `design/logo/` with a README that says which file goes on which background. One dimension only, never both, so the aspect ratio is preserved. No effects, rotation, recolouring, cropping, or recreation from text or shapes.

```python
# python-pptx / python-docx: width only, height follows
slide.shapes.add_picture("design/logo/logo-full.png", Inches(8.0), Inches(0.35), width=Inches(1.5))
doc.sections[0].header.paragraphs[0].add_run().add_picture("design/logo/logo-full.png", width=Inches(2.0))
# openpyxl: anchor the image and set width, then derive height from the file's real dimensions
img = Image("design/logo/logo-full.png"); img.width = 180; img.height = round(180 * native_h / native_w)
```

```html
<img class="logo" src="design/logo/logo-full.svg" alt="<Project name>" style="width:180px;height:auto">
```

Before any `.pptx` or `.docx` is delivered, run the checker and fix anything it reports:

```bash
uv run --no-project --with pillow python design/check_logo_aspect.py <file>
```

## Voice in user-facing text

Headings and empty states are claims, not labels ("Your report is ready to share", not "Overview"). Lead with the insight. Quantify. Active voice. Never: synergize, leverage (as a verb), paradigm shift, best-in-class, value-add, next-generation, cutting-edge, robust, seamless, holistic.

## When unsure

If a deliverable needs an asset that is not in `design/`, or a colour or layout the tokens do not cover, stop and ask the owner. Do not improvise design assets.
