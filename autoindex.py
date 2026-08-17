#!/usr/bin/env python3
"""AutoIndex.md: Idempotent Hierarchical Markdown Documentation Index Generator.


Scans thousands of files, extracts titles from H1 markdown headers, tracks
duplicate filenames via lowercase slugs, calculates exact sizes, and generates
completely fresh index.md, index.html, and optional index.json files.
"""


import argparse
import collections
import dataclasses
import datetime
import html
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# --- Default Configurations ---
DEFAULT_DOCS_ROOT = Path("subtitles")
OUTPUT_MD = Path("index.md")
OUTPUT_HTML = Path("index.html")
OUTPUT_JSON = Path("index.json")


# Filenames to drop from parsing scans if located inside the target path
IGNORE_FILENAMES = {OUTPUT_MD.name, OUTPUT_HTML.name, OUTPUT_JSON.name}


# --- ANSI Terminal Color Configurations ---
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_GREEN = "\033[32m"
COLOR_YELLOW = "\033[33m"
COLOR_RED = "\033[31m"
COLOR_CYAN = "\033[36m"
COLOR_GRAY = "\033[90m"


logger = logging.getLogger("AutoIndex")




@dataclasses.dataclass(frozen=True)
class DocItem:
    """Immutable data record tracking parsed metadata for an individual Markdown file."""


    title: str
    slug: str
    category_path: Tuple[str, ...]  # Directory breadcrumbs, e.g., ("TypeScript", "Array")
    relative_path: str  # URL-safe web path relative to DOCS_ROOT, e.g., "subtitles/typescript/file.md"
    file_size_kb: float




def setup_logger(verbose: bool) -> None:
    """Sets up a clean stream console logger handling system levels gracefully."""
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)




def style(text: str, *ansi_codes: str) -> str:
    """Wraps text in terminal control strings safely when running in a supported TTY."""
    if not sys.stdout.isatty():
        return text
    return "".join(ansi_codes) + text + COLOR_RESET




def extract_title_and_size(file_path: Path) -> Tuple[str, float]:
    """Safely extracts the first structural H1 heading from a file and returns its size.


    Falls back to a Title-Cased string representation of the filename if missing.
    """
    title: Optional[str] = None
    try:
        with open(file_path, "r", encoding="utf-8", errors="strict") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("# "):
                    title = stripped[2:].strip()
                    break
                elif stripped and not stripped.startswith("#"):
                    # First non-empty block was regular text; stop scanning
                    break
    except (UnicodeDecodeError, PermissionError) as e:
        raise ValueError(f"Read error: {e}")


    if not title:
        title = file_path.stem.replace("-", " ").replace("_", " ").title()


    # Calculate direct file size statistics
    size_kb = round(file_path.stat().st_size / 1024.0, 1)
    # Ensure zero values show cleanly as 0.1 KB minimum if content exists
    if size_kb == 0.0 and file_path.stat().st_size > 0:
        size_kb = 0.1


    return title, size_kb




def get_hierarchy_tuple(file_path: Path, docs_root: Path) -> Tuple[str, ...]:
    """Computes categorical directory breadcrumbs capped strictly at three structural tiers."""
    try:
        relative_dir = file_path.relative_to(docs_root).parent
    except ValueError:
        return ("General",)


    if relative_dir == Path("."):
        return ("General",)


    # Convert folder naming steps up to a depth limit of 3 tiers
    parts = relative_dir.parts[:3]
    return tuple(part.title() for part in parts)




# Filesystem-aware stage ordering: refined -> article -> summary -> point summaries
_STAGE_ORDER = {"refined": 1, "article": 2, "summary": 3, "points": 4, "other": 5}


def parse_filename_stage(stem: str) -> Tuple[str, str]:
    """Splits a file stem into (base name, stage) for deterministic grouping."""
    lower = stem.lower()

    m = re.search(r"-(?:\d+-)?points?-summary$|-summary-points$", lower)
    if m:
        return stem[:m.start()], "points"

    m = re.search(r"-summary$", lower)
    if m:
        return stem[:m.start()], "summary"

    m = re.search(r"-article(?:-.+)?$", lower)
    if m:
        return stem[:m.start()], "article"

    m = re.search(r"-refined(?:-.+)?$", lower)
    if m:
        return stem[:m.start()], "refined"

    return stem, "other"




def get_display_label(item: "DocItem") -> str:
    """Returns the on-disk filename (without extension) as the human-readable label."""
    return Path(item.relative_path).stem




def item_sort_key(item: "DocItem") -> Tuple[str, int, str]:
    """Sorts items by base group, stage order (refined/article/summary/points), then name."""
    base, stage = parse_filename_stage(Path(item.slug).stem)
    return (base, _STAGE_ORDER.get(stage, _STAGE_ORDER["other"]), item.slug)




def scan_repository(
    docs_root: Path,
) -> Tuple[Dict[Tuple[str, ...], List[DocItem]], int, List[str]]:
    """Traverses the source workspace recursively, checking for overlaps and failures."""
    catalog: Dict[Tuple[str, ...], List[DocItem]] = collections.defaultdict(list)
    seen_slugs: Dict[str, str] = {}  # lowercase slug -> relative path string
    errors: List[str] = []
    duplicate_count = 0


    if not docs_root.exists() or not docs_root.is_dir():
        logger.error(style(f"Error: Target directory '{docs_root}' does not exist.", COLOR_RED))
        sys.exit(1)


    logger.info(style(f"Scanning documentation from '{docs_root}'...", COLOR_BOLD))


    for md_path in docs_root.rglob("*.md"):
        if md_path.name in IGNORE_FILENAMES:
            continue


        slug = md_path.name.lower()
        # Relative link structure relative to the execution root directory
        web_relative_path = md_path.as_posix()


        if slug in seen_slugs:
            duplicate_count += 1
            logger.warning(
                style(
                    f"\nDuplicate slug ignored:\n  {slug}\n"
                    f"  Used:    {seen_slugs[slug]}\n"
                    f"  Ignored: {web_relative_path}",
                    COLOR_YELLOW,
                )
            )
            continue


        try:
            title, size_kb = extract_title_and_size(md_path)
            category_path = get_hierarchy_tuple(md_path, docs_root)


            item = DocItem(
                title=title,
                slug=slug,
                category_path=category_path,
                relative_path=web_relative_path,
                file_size_kb=size_kb,
            )
            catalog[category_path].append(item)
            seen_slugs[slug] = web_relative_path
            logger.debug(style(f"Processed: {web_relative_path} -> [{title}]", COLOR_GRAY))


        except Exception as e:
            err_msg = f"Skipped file '{md_path}' due to error: {e}"
            errors.append(err_msg)
            logger.error(style(err_msg, COLOR_RED))


    # Sort each category by base group, then stage order, then filename
    for path_key in catalog:
        catalog[path_key].sort(key=item_sort_key)


    return catalog, duplicate_count, errors




def get_sorted_categories(
    catalog: Dict[Tuple[str, ...], List[DocItem]]
) -> List[Tuple[str, ...]]:
    """Sorts nested grouping tracks case-insensitively using joining strings."""
    return sorted(catalog.keys(), key=lambda t: " > ".join(t).lower())




def get_markdown_heading(category_path: Tuple[str, ...]) -> str:
    """Builds a formatted structural Markdown heading line based on nesting depth."""
    breadcrumb = " > ".join(category_path)
    if category_path == ("General",):
        return f"# {breadcrumb}"
    
    depth = len(category_path)
    if depth == 1:
        return f"# {breadcrumb}"
    elif depth == 2:
        return f"## {breadcrumb}"
    else:
        return f"### {breadcrumb}"




def generate_markdown(
    catalog: Dict[Tuple[str, ...], List[DocItem]],
    title: str,
    total_articles: int,
    counts: Tuple[int, int, int],
) -> str:
    """Builds a complete cleanly tabbed production standard index string in Markdown."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    d1, d2, d3 = counts


    lines = [
        f"# {title}",
        "",
        "Automatically generated index of documentation assets.",
        "",
        f"Total Articles: {total_articles}",
        "",
        f"Generated On: {timestamp}",
        "",
        f"Top-Level Categories (Depth 1): {d1}",
        "",
        f"Subcategories (Depth 2): {d2}",
        "",
        f"Sub-Subcategories (Depth 3): {d3}",
        "",
        "---",
        "",
    ]


    for cat_path in get_sorted_categories(catalog):
        lines.append(get_markdown_heading(cat_path))
        lines.append("")
        for item in catalog[cat_path]:
            lines.append(f"- [{html.escape(get_display_label(item))}]({html.escape(item.relative_path)}) ({item.file_size_kb:.1f} KB)")
        lines.append("")


    return "\n".join(lines)




def get_html_heading(category_path: Tuple[str, ...]) -> str:
    """Generates clean structural layout elements for matching web presentation depth levels."""
    label = html.escape(" > ".join(category_path))
    if category_path == ("General",):
        return f"<h2>{label}</h2>"
    
    depth = len(category_path)
    if depth == 1:
        return f"<h2>{label}</h2>"
    elif depth == 2:
        return f"<h3>{label}</h3>"
    else:
        return f"<h4>{label}</h4>"




def generate_html(
    catalog: Dict[Tuple[str, ...], List[DocItem]],
    title: str,
    total_articles: int,
    counts: Tuple[int, int, int],
) -> str:
    """Compiles a responsive and semantic HTML5 dashboard with embedded CSS and sticky TOC."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    escaped_title = html.escape(title)
    d1, d2, d3 = counts
    sorted_cats = get_sorted_categories(catalog)


    html_start = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escaped_title}</title>
    <style>
        :root {{
            --bg-color: #f8fafc;
            --text-main: #1e293b;
            --card-bg: #ffffff;
            --border: #e2e8f0;
            --primary: #2563eb;
            --secondary: #64748b;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            line-height: 1.6;
            margin: 0;
            padding: 0;
        }}
        .wrapper {{
            display: flex;
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem 1rem;
            gap: 2rem;
        }}
        .main-panel {{
            flex: 1;
            background: var(--card-bg);
            padding: 2.5rem;
            border-radius: 8px;
            border: 1px solid var(--border);
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            min-width: 0;
        }}
        .sidebar {{
            width: 280px;
            position: -webkit-sticky;
            position: sticky;
            top: 2rem;
            height: calc(100vh - 4rem);
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.5rem;
            overflow-y: auto;
            box-sizing: border-box;
        }}
        @media (max-width: 850px) {{
            .wrapper {{ flex-direction: column; }}
            .sidebar {{ width: 100%; position: static; height: auto; }}
        }}
        h1 {{ font-size: 2.25rem; margin-top: 0; margin-bottom: 1.5rem; color: #0f172a; }}
        h2 {{ font-size: 1.5rem; margin-top: 2.5rem; border-bottom: 2px solid var(--border); padding-bottom: 0.4rem; color: #0f172a; }}
        h3 {{ font-size: 1.25rem; margin-top: 2rem; color: #334155; }}
        h4 {{ font-size: 1.1rem; margin-top: 1.5rem; color: #475569; }}
        .meta-group {{
            background: var(--bg-color);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 1rem 1.25rem;
            margin-bottom: 2rem;
        }}
        .meta-group p {{ margin: 0.25rem 0; color: var(--secondary); font-size: 0.95rem; }}
        .meta-group strong {{ color: var(--text-main); }}
        ul {{ list-style: none; padding-left: 0; }}
        li {{ padding: 0.5rem 0; border-bottom: 1px dashed var(--border); display: flex; justify-content: space-between; align-items: center; gap: 1rem; }}
        li:last-child {{ border-bottom: none; }}
        a {{ color: var(--primary); text-decoration: none; font-weight: 500; word-break: break-all; }}
        a:hover {{ text-decoration: underline; }}
        .size-badge {{ font-size: 0.8rem; color: var(--secondary); white-space: nowrap; }}
        .toc-title {{ font-weight: 700; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--secondary); margin-bottom: 1rem; }}
        .toc-item {{ display: block; padding: 0.3rem 0; color: #475569; font-size: 0.9rem; text-overflow: ellipsis; overflow: hidden; white-space: nowrap; }}
        .toc-item:hover {{ color: var(--primary); }}
    </style>
</head>
<body>
<div class="wrapper">
    <nav class="sidebar">
        <div class="toc-title">Table of Contents</div>
"""
    toc_links = []
    for i, path_key in enumerate(sorted_cats):
        label = " &gt; ".join(path_key)
        toc_links.append(f'        <a class="toc-item" href="#sec-{i}" title="{html.escape(label)}">{html.escape(label)}</a>')


    html_middle = f"""    </nav>


    <main class="main-panel">
        <h1>{escaped_title}</h1>
        
        <div class="meta-group">
            <p>Automatically generated index of documentation assets.</p>
            <p><strong>Total Articles:</strong> {total_articles}</p>
            <p><strong>Generated On:</strong> {timestamp}</p>
            <p><strong>Top-Level Categories (Depth 1):</strong> {d1}</p>
            <p><strong>Subcategories (Depth 2):</strong> {d2}</p>
            <p><strong>Sub-Subcategories (Depth 3):</strong> {d3}</p>
        </div>
"""


    body_blocks = []
    for i, path_key in enumerate(sorted_cats):
        body_blocks.append(f'        <section id="sec-{i}" style="scroll-margin-top: 2rem;">')
        body_blocks.append(f"            {get_html_heading(path_key)}")
        body_blocks.append("            <ul>")
        for item in catalog[path_key]:
            body_blocks.append("                <li>")
            body_blocks.append(f'                    <a href="{html.escape(item.relative_path)}">{html.escape(get_display_label(item))}</a>')
            body_blocks.append(f'                    <span class="size-badge">({item.file_size_kb:.1f} KB)</span>')
            body_blocks.append("                </li>")
        body_blocks.append("            </ul>")
        body_blocks.append("        </section>")


    html_end = """    </main>
</div>
</body>
</html>
"""
    return (
        html_start
        + "\n".join(toc_links)
        + html_middle
        + "\n".join(body_blocks)
        + html_end
    )




def generate_json(catalog: Dict[Tuple[str, ...], List[DocItem]]) -> str:
    """Serializes compiled content into a clean raw structured JSON format string array."""
    json_array = []
    for cat_path in get_sorted_categories(catalog):
        category = cat_path[0]
        subcategory = cat_path[1] if len(cat_path) > 1 else ""
        for item in catalog[cat_path]:
            json_array.append(
                {
                    "title": item.title,
                    "slug": item.slug,
                    "category": category,
                    "subcategory": subcategory,
                    "path": item.relative_path,
                    "size_kb": item.file_size_kb,
                }
            )
    return json.dumps(json_array, indent=2)




def remove_stale_index_files(json_enabled: bool) -> None:
    """Guarantees strict fresh generation execution steps by removing old indexes."""
    targets = [OUTPUT_MD, OUTPUT_HTML]
    if json_enabled:
        targets.append(OUTPUT_JSON)


    for target in targets:
        if target.exists():
            try:
                target.unlink()
                logger.debug(style(f"Purged old file asset: {target}", COLOR_GRAY))
            except Exception as e:
                logger.error(style(f"Warning: Failed cleaning old asset {target}: {e}", COLOR_RED))




def calculate_tier_metrics(catalog: Dict[Tuple[str, ...], List[DocItem]]) -> Tuple[int, int, int]:
    """Calculates granular depth categorization counts across processed items."""
    d1: Set[str] = set()
    d2: Set[Tuple[str, str]] = set()
    d3: Set[Tuple[str, str, str]] = set()


    for k in catalog.keys():
        if k == ("General",):
            continue
        if len(k) >= 1:
            d1.add(k[0])
        if len(k) >= 2:
            d2.add((k[0], k[1]))
        if len(k) == 3:
            d3.add((k[0], k[1], k[2]))


    return len(d1), len(d2), len(d3)




def main() -> None:
    """Handles CLI parsing execution and manages target compilation orchestration workflows."""
    start_time = time.time()


    parser = argparse.ArgumentParser(
        description="AutoIndex.md: Fast production-grade recursive Markdown index builder."
    )
    parser.add_argument(
        "--docs",
        type=str,
        default=str(DEFAULT_DOCS_ROOT),
        help=f"Target root directory pathway containing Markdown documentation (default: '{DEFAULT_DOCS_ROOT}')",
    )
    parser.add_argument(
        "--title",
        type=str,
        default="Documentation Index",
        help="Custom primary layout dashboard title string configuration value",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Triggers an additional flat machine-readable index.json export manifest file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parses data files without deleting or writing files to the disk surface",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Outputs real-time operational streams during code processing runs",
    )


    args = parser.parse_args()
    setup_logger(args.verbose)


    docs_root = Path(args.docs)


    # 1. Processing Scans Loop Tree Traversal Steps
    catalog, duplicates, errors = scan_repository(docs_root)


    total_indexed_articles = sum(len(items) for items in catalog.values())
    total_scanned_files = total_indexed_articles + duplicates
    tier_counts = calculate_tier_metrics(catalog)


    # 2. String Composition Construction Steps
    logger.info(style("Generating index.md...", COLOR_BOLD))
    md_content = generate_markdown(catalog, args.title, total_indexed_articles, tier_counts)
    
    logger.info(style("Generating index.html...", COLOR_BOLD))
    html_content = generate_html(catalog, args.title, total_indexed_articles, tier_counts)
    
    json_content = generate_json(catalog) if args.json else ""


    # 3. File Commits IO Management Blocks
    if not args.dry_run:
        remove_stale_index_files(args.json)
        try:
            OUTPUT_MD.write_text(md_content, encoding="utf-8")
            OUTPUT_HTML.write_text(html_content, encoding="utf-8")
            if args.json:
                OUTPUT_JSON.write_text(json_content, encoding="utf-8")
        except Exception as e:
            logger.critical(style(f"Fatal execution crash writing files to target track: {e}", COLOR_RED))
            sys.exit(1)
    else:
        logger.info(style("\n[DRY RUN]: Simulation matches successful. File updates skipped.", COLOR_CYAN))


    duration = time.time() - start_time


    # 4. Terminal Performance Reporting Dashboard Interface
    logger.info("\n" + style("=" * 50, COLOR_GRAY))
    logger.info(style("              INDEXING METRICS REPORT             ", COLOR_BOLD))
    logger.info(style("=" * 50, COLOR_GRAY))
    logger.info(f"Total Markdown files scanned:   {total_scanned_files}")
    logger.info(f"Total indexed articles:         {style(str(total_indexed_articles), COLOR_GREEN)}")
    logger.info(f"Duplicate slugs ignored:        {style(str(duplicates), COLOR_YELLOW if duplicates > 0 else COLOR_GRAY)}")
    logger.info(f"Top-level category count (D1):  {tier_counts[0]}")
    logger.info(f"Depth-2 subcategory count (D2): {tier_counts[1]}")
    logger.info(f"Depth-3 subcategory count (D3): {tier_counts[2]}")
    logger.info(f"Total generation time:          {duration:.2f} seconds")
    logger.info(f"Total indexing errors:          {style(str(len(errors)), COLOR_RED if errors else COLOR_GRAY)}")


    if not args.dry_run:
        logger.info(style("\nFresh Index Files Generated Successfully:", COLOR_BOLD))
        logger.info(f"  - ./{OUTPUT_MD}")
        logger.info(f"  - ./{OUTPUT_HTML}")
        if args.json:
            logger.info(f"  - ./{OUTPUT_JSON}")


    if errors:
        logger.error(style(f"\nExecution finished with {len(errors)} handled issues logged.", COLOR_RED))
        sys.exit(1)
    else:
        logger.info(style("\nDone.", COLOR_GREEN))




if __name__ == "__main__":
    main()