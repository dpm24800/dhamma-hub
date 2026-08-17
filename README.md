# DhammaSubtitles

A library of refined Dhamma transcripts and articles, published as a static site on GitHub Pages with Jekyll.

Live site: https://dpm24800.github.io/dhamma-hub/

## Overview

DhammaSubtitles stores raw Markdown transcripts (subtitle extractions, refinements, summaries, and point-summaries) organized by source channel, and renders them as a clean reading-friendly website using a minimal Jekyll build. Every transcript is a self-contained `.md` file under `subtitles/`; `autoindex.py` scans the whole library and regenerates the browsable index.

## Repository Layout

```
.
├── _config.yml          # Jekyll configuration
├── _layouts/
│   └── reader.html      # Reading layout applied to every subtitle page
├── subtitles/           # Markdown library, organized by channel
│   ├── dhamma-hub/
│   ├── hillside-hermitage/
│   └── perfect-life-seven-gn/
├── autoindex.py         # Index generator (see Flags below)
├── index.html           # Generated browsable index (HTML)
├── index.md             # Generated browsable index (Markdown)
└── index.json           # Generated machine-readable index (only with --json)
```

## How Rendering Works

Jekyll only converts `.md` files that contain YAML front matter. Files without front matter are copied verbatim as static files and served as raw Markdown — which is why a raw `.md` URL showed up as plain text on devices without a Markdown viewer.

So every transcript under `subtitles/` must begin with front matter:

```markdown
---
---

# Title of the transcript
...
```

Once present, Jekyll converts `subtitles/<channel>/<name>.md` into `subtitles/<channel>/<name>.html`, wrapped in the `reader` layout. The layout assignment is configured via `defaults` in `_config.yml`, so the front matter can be empty:

```yaml
defaults:
  - scope:
      path: "subtitles"
    values:
      layout: reader
```

**Important:** the front matter block must have no leading byte-order mark (BOM) and no leading blank line — a BOM breaks Jekyll's front-matter detection and the file silently falls back to raw serving.

## Index Generation (autoindex.py)

`autoindex.py` recursively scans the library, extracts titles from the first `# H1` heading, computes file sizes, groups files by directory category, and regenerates `index.html` and `index.md`. Links are written with a configurable extension — `html` (default) for Jekyll/GitHub Pages, since that is the URL of the rendered page rather than the raw Markdown.

### Flags

| Flag            | Default               | Description                                                                 |
| --------------- | --------------------- | --------------------------------------------------------------------------- |
| `--docs`        | `subtitles`           | Target root directory containing the Markdown documentation to index.       |
| `--title`       | `Documentation Index` | Title used as the main heading in the generated index.                      |
| `--json`        | *(store_true)*        | Additionally export a flat machine-readable `index.json` manifest.          |
| `--dry-run`     | *(store_true)*        | Scan and generate content in memory without deleting or writing any files.  |
| `--verbose`     | *(store_true)*        | Print detailed per-file processing output.                                  |
| `--link-ext`    | `html`                | File extension used in generated links. `html` for Jekyll/GitHub Pages, `md` for raw Markdown serving. |

### Examples

```sh
# Default build with .html links (recommended for Jekyll/GitHub Pages)
python autoindex.py

# Preview what would be generated, without touching files
python autoindex.py --dry-run

# Index a different folder as "My Library" and also emit index.json
python autoindex.py --docs transcripts --title "My Library" --json

# Verbose run to inspect per-file classification and stage grouping
python autoindex.py --verbose
```

### Sorting

Files are grouped and sorted by base name and stage in the order: `refined` → `article` → `summary` → `points` → `other`, using the filename suffixes `-refined`, `-article`, `-summary`, `-summary-points`.

## Workflow

1. Add or update transcript files under `subtitles/<channel>/<name>.md`, each starting with `---\n---\n` front matter.
2. Regenerate the index: `python autoindex.py`.
3. Commit and push. GitHub Pages runs the Jekyll build automatically; the rendered pages appear at `subtitles/<channel>/<name>.html`.

## Local Preview

Requires Ruby + the Jekyll gem. From the repository root:

```sh
jekyll serve
```

Then open http://localhost:4000/dhamma-hub/.