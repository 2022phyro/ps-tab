"""Dynamic, self-updating Documentation Engine with mtime-based in-memory caching."""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
import markdown
import frontmatter

# Locate the root documentation directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
DOCS_DIR = BASE_DIR / "documentation"


@dataclass
class DocItem:
    """An individual markdown document entry in the navigation tree."""
    title: str
    slug: str
    file_path: Path
    badge: Optional[str] = None


@dataclass
class FolderSection:
    """A directory section containing documents and nested subfolders."""
    title: str
    folder_name: str
    items: List[DocItem] = field(default_factory=list)
    subsections: List["FolderSection"] = field(default_factory=list)


@dataclass
class TocHeading:
    """A heading for the floating outline tracker."""
    level: int  # 2 for h2, 3 for h3
    title: str
    anchor: str


@dataclass
class ParsedDoc:
    """A parsed and cached markdown document with metadata and outline."""
    slug: str
    title: str
    html_content: str
    toc: List[TocHeading]
    metadata: Dict[str, Any]
    breadcrumbs: List[Tuple[str, Optional[str]]]
    prev_item: Optional[DocItem] = None
    next_item: Optional[DocItem] = None


# In-memory document cache: slug -> (mtime, ParsedDoc)
_doc_cache: Dict[str, Tuple[float, ParsedDoc]] = {}
# In-memory navigation tree cache: (last_check_time, tree, flat_list)
_tree_cache: Optional[Tuple[float, List[FolderSection], List[DocItem]]] = None
TREE_CACHE_TTL_SECONDS = 1.0  # Check directory structure at most once per second


def _clean_title_from_name(name: str) -> str:
    """Convert filename or folder name to clean title (e.g. '01-getting-started' -> 'Getting Started')."""
    # Strip leading numbers like 01-, 02_
    cleaned = re.sub(r"^\d+[-_]", "", name)
    cleaned = cleaned.replace("-", " ").replace("_", " ")
    return cleaned.title()


def _slugify(text: str) -> str:
    """Create a URL-safe anchor slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def _get_folder_title(folder: Path) -> str:
    """Read folder title from header.txt if present, or fallback to cleaned name."""
    header_file = folder / "header.txt"
    if header_file.is_file():
        try:
            title = header_file.read_text(encoding="utf-8").strip()
            if title:
                return title
        except Exception:
            pass
    return _clean_title_from_name(folder.name)


def _get_doc_title_and_badge(file_path: Path) -> Tuple[str, Optional[str]]:
    """Extract document title and optional badge from frontmatter or first # Heading."""
    try:
        post = frontmatter.load(file_path)
        if post.metadata.get("title"):
            return str(post.metadata["title"]), post.metadata.get("badge")

        # Fallback to first # Heading
        for line in post.content.splitlines():
            line_s = line.strip()
            if line_s.startswith("# "):
                return line_s[2:].strip(), post.metadata.get("badge")
    except Exception:
        pass

    return _clean_title_from_name(file_path.stem), None


def _format_github_alerts(html: str) -> str:
    """Transform GitHub-style blockquote alerts (> [!NOTE], etc.) into styled callout HTML."""
    alert_types = {
        "NOTE": ("bg-blue-50/70 dark:bg-blue-950/30 border-blue-500/80 text-blue-900 dark:text-blue-200", "ℹ️ Note"),
        "TIP": ("bg-emerald-50/70 dark:bg-emerald-950/30 border-emerald-500/80 text-emerald-900 dark:text-emerald-200", "💡 Tip"),
        "IMPORTANT": ("bg-amber-50/70 dark:bg-amber-950/30 border-[#995F2F] text-amber-900 dark:text-[#E4D6A9]", "⚠️ Important"),
        "WARNING": ("bg-orange-50/70 dark:bg-orange-950/30 border-orange-500/80 text-orange-900 dark:text-orange-200", "⚡ Warning"),
        "CAUTION": ("bg-rose-50/70 dark:bg-rose-950/30 border-rose-500/80 text-rose-900 dark:text-rose-200", "🛑 Caution"),
    }

    for alert_key, (css_classes, label) in alert_types.items():
        pattern = re.compile(
            rf'<blockquote>\s*<p>\s*\[!{alert_key}\]\s*(.*?)</p>\s*</blockquote>',
            re.DOTALL | re.IGNORECASE,
        )
        replacement = (
            rf'<div class="my-5 rounded-xl border-l-4 p-4 text-sm shadow-sm {css_classes}">'
            rf'<div class="font-bold font-heading mb-1">{label}</div>'
            rf'<div>\1</div>'
            rf'</div>'
        )
        html = pattern.sub(replacement, html)

    return html


def _extract_headings(markdown_text: str) -> List[TocHeading]:
    """Scan markdown for ## and ### headings to build the outline tracker."""
    headings: List[TocHeading] = []
    seen_anchors: Dict[str, int] = {}

    for line in markdown_text.splitlines():
        line_s = line.strip()
        if line_s.startswith("## ") and not line_s.startswith("### "):
            title = line_s[3:].strip()
            anchor = _slugify(title)
            if anchor in seen_anchors:
                seen_anchors[anchor] += 1
                anchor = f"{anchor}-{seen_anchors[anchor]}"
            else:
                seen_anchors[anchor] = 0
            headings.append(TocHeading(level=2, title=title, anchor=anchor))
        elif line_s.startswith("### "):
            title = line_s[4:].strip()
            anchor = _slugify(title)
            if anchor in seen_anchors:
                seen_anchors[anchor] += 1
                anchor = f"{anchor}-{seen_anchors[anchor]}"
            else:
                seen_anchors[anchor] = 0
            headings.append(TocHeading(level=3, title=title, anchor=anchor))

    return headings


def _build_tree_recursive(dir_path: Path, relative_prefix: str = "") -> FolderSection:
    """Recursively scan a directory to build navigation sections."""
    section_title = _get_folder_title(dir_path)
    section = FolderSection(
        title=section_title,
        folder_name=dir_path.name,
    )

    entries = sorted(dir_path.iterdir(), key=lambda p: p.name.lower())

    for entry in entries:
        if entry.name.startswith((".", "_")) or entry.name == "header.txt":
            continue

        if entry.is_dir():
            sub_prefix = f"{relative_prefix}/{entry.name}" if relative_prefix else entry.name
            subsection = _build_tree_recursive(entry, sub_prefix)
            if subsection.items or subsection.subsections:
                section.subsections.append(subsection)

        elif entry.is_file() and entry.suffix.lower() == ".md":
            doc_slug = f"{relative_prefix}/{entry.stem}" if relative_prefix else entry.stem
            # Clean numeric prefixes from slug for clean URLs
            clean_slug_parts = [re.sub(r"^\d+[-_]", "", part) for part in doc_slug.split("/")]
            clean_slug = "/".join(clean_slug_parts)

            title, badge = _get_doc_title_and_badge(entry)
            section.items.append(DocItem(
                title=title,
                slug=clean_slug,
                file_path=entry,
                badge=badge,
            ))

    return section


def get_documentation_tree() -> Tuple[List[FolderSection], List[DocItem]]:
    """Get the full navigation tree and flat list of documents with caching."""
    import time
    global _tree_cache

    now = time.time()
    if _tree_cache and (now - _tree_cache[0]) < TREE_CACHE_TTL_SECONDS:
        return _tree_cache[1], _tree_cache[2]

    if not DOCS_DIR.exists():
        DOCS_DIR.mkdir(parents=True, exist_ok=True)

    tree: List[FolderSection] = []
    flat_docs: List[DocItem] = []

    # Iterate through top-level directories in documentation/
    entries = sorted(DOCS_DIR.iterdir(), key=lambda p: p.name.lower())
    for entry in entries:
        if entry.is_dir() and not entry.name.startswith((".", "_")):
            sec = _build_tree_recursive(entry, entry.name)
            if sec.items or sec.subsections:
                tree.append(sec)

    # Flatten docs for prev/next link computation
    def _collect_flat(sec: FolderSection):
        for item in sec.items:
            flat_docs.append(item)
        for sub in sec.subsections:
            _collect_flat(sub)

    for sec in tree:
        _collect_flat(sec)

    _tree_cache = (now, tree, flat_docs)
    return tree, flat_docs


def get_document(slug: str) -> Optional[ParsedDoc]:
    """Retrieve and parse a document by its clean URL slug, with mtime caching."""
    tree, flat_docs = get_documentation_tree()
    if not flat_docs:
        return None

    slug_clean = slug.strip("/").lower()

    # Find the target item in flat_docs
    target_idx: Optional[int] = None
    target_item: Optional[DocItem] = None

    for i, item in enumerate(flat_docs):
        if item.slug.lower() == slug_clean:
            target_idx = i
            target_item = item
            break

    if target_item is None or not target_item.file_path.exists():
        return None

    # Check mtime cache
    file_path = target_item.file_path
    current_mtime = file_path.stat().st_mtime

    if target_item.slug in _doc_cache:
        cached_mtime, cached_doc = _doc_cache[target_item.slug]
        if cached_mtime == current_mtime:
            # Update prev/next in case tree changed
            cached_doc.prev_item = flat_docs[target_idx - 1] if target_idx > 0 else None
            cached_doc.next_item = flat_docs[target_idx + 1] if target_idx < len(flat_docs) - 1 else None
            return cached_doc

    # Parse document
    post = frontmatter.load(file_path)
    title, _ = _get_doc_title_and_badge(file_path)
    headings = _extract_headings(post.content)

    # Convert Markdown to HTML
    md_parser = markdown.Markdown(extensions=[
        "fenced_code",
        "tables",
        "codehilite",
        "toc",
        "nl2br",
        "sane_lists",
    ])
    raw_html = md_parser.convert(post.content)
    formatted_html = _format_github_alerts(raw_html)

    # Compute breadcrumbs
    parts = target_item.slug.split("/")
    breadcrumbs: List[Tuple[str, Optional[str]]] = [("Documentation", "/documentation")]
    running_path = ""
    for part in parts[:-1]:
        running_path = f"{running_path}/{part}" if running_path else part
        breadcrumbs.append((_clean_title_from_name(part), None))
    breadcrumbs.append((title, None))

    prev_item = flat_docs[target_idx - 1] if target_idx > 0 else None
    next_item = flat_docs[target_idx + 1] if target_idx < len(flat_docs) - 1 else None

    parsed = ParsedDoc(
        slug=target_item.slug,
        title=title,
        html_content=formatted_html,
        toc=headings,
        metadata=post.metadata,
        breadcrumbs=breadcrumbs,
        prev_item=prev_item,
        next_item=next_item,
    )

    _doc_cache[target_item.slug] = (current_mtime, parsed)
    return parsed
