#!/usr/bin/env python3
"""
Build script for the Local Hustlers site.

Reads each page's content from content/<page>.json, feeds it into the
matching Jinja2 template in templates/<page>.html.j2, and writes the
finished HTML file into the site root (index.html, contestants.html,
etc.) — overwriting whatever was there before.

You normally don't need to run this by hand: editor_app.py (the
Streamlit editor) calls it automatically every time you hit "Save &
rebuild". It's here so you can also:
  - edit a content/*.json file directly in a text editor and regenerate
    the site without opening the visual editor, or
  - rebuild everything at once after pulling changes.

Usage:
    python3 build.py              # rebuild every page
    python3 build.py index        # rebuild just index.html
    python3 build.py index about  # rebuild a specific subset
"""
import json
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent
CONTENT_DIR = ROOT / "content"
TEMPLATES_DIR = ROOT / "templates"

# page key -> output filename in the site root
PAGES = {
    "index": "index.html",
    "contestants": "contestants.html",
    "episodes": "episodes.html",
    "about": "about.html",
    "sponsors": "sponsors.html",
    "contacts": "contacts.html",
}

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def load_content(page_key):
    """Read content/<page_key>.json into a dict."""
    path = CONTENT_DIR / f"{page_key}.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_content(page_key, data):
    """Write a dict back to content/<page_key>.json (used by the editor)."""
    path = CONTENT_DIR / f"{page_key}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def build_page(page_key):
    """Render one page's template with its content and write the HTML file."""
    if page_key not in PAGES:
        raise ValueError(f"Unknown page: {page_key!r}. Valid keys: {list(PAGES)}")
    content = load_content(page_key)
    template = _env.get_template(f"{page_key}.html.j2")
    html = template.render(**content)
    out_path = ROOT / PAGES[page_key]
    out_path.write_text(html, encoding="utf-8")
    return out_path


def build_all():
    """Rebuild every page. Returns the list of files written."""
    return [build_page(key) for key in PAGES]


if __name__ == "__main__":
    targets = sys.argv[1:] or list(PAGES.keys())
    for key in targets:
        try:
            path = build_page(key)
            print(f"built {path.name}")
        except Exception as exc:
            print(f"FAILED to build {key}: {exc}", file=sys.stderr)
            sys.exit(1)
