"""
Markdown parser for Obsidian-style vault notes.

Extracts:
- Frontmatter (via python-frontmatter)
- Title (from H1 heading or frontmatter)
- Headings
- Obsidian wiki-links: [[Target]] and [[Target|Alias]]
- Plain text content
- Metadata
"""
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import frontmatter  # python-frontmatter

logger = logging.getLogger(__name__)

# Regex patterns
_WIKI_LINK_RE = re.compile(r"\[\[([^\]|#]+?)(?:\|[^\]]+?)?\]\]")
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_FRONTMATTER_FENCE_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)


@dataclass
class ParsedNote:
    """Structured representation of a parsed Obsidian markdown note."""

    filename: str           # e.g. "03_RAG.md"
    filepath: str           # absolute or relative path
    title: str              # from H1 or frontmatter
    content: str            # full raw markdown
    body: str               # markdown without frontmatter
    headings: list[str]     # list of heading texts
    wiki_links: list[str]   # target names from [[links]]
    tags: list[str]         # from frontmatter tags
    frontmatter_meta: dict  # parsed frontmatter dict


def parse_note(path: Path) -> ParsedNote:
    """Parse a single Obsidian markdown file into a ParsedNote."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise IOError(f"Cannot read {path}: {e}") from e

    # Parse frontmatter
    try:
        post = frontmatter.loads(raw)
        meta: dict = dict(post.metadata)
        body: str = post.content
    except Exception as e:
        logger.warning("Could not parse frontmatter for %s: %s", path.name, e)
        meta = {}
        body = raw

    # Title: prefer frontmatter 'title', fall back to first H1
    title: str = str(meta.get("title", ""))
    if not title:
        h1_match = _H1_RE.search(body)
        title = h1_match.group(1).strip() if h1_match else path.stem

    # Headings
    headings = [m.group(2).strip() for m in _HEADING_RE.finditer(body)]

    # Wiki-links — normalise: strip underscores → spaces, strip aliases
    raw_links = _WIKI_LINK_RE.findall(body)
    wiki_links = list(dict.fromkeys(  # deduplicated, order-preserved
        link.strip().replace("_", " ")
        for link in raw_links
    ))

    # Tags
    raw_tags = meta.get("tags", [])
    if isinstance(raw_tags, str):
        raw_tags = [t.strip() for t in raw_tags.split(",")]
    tags = [str(t) for t in raw_tags]

    return ParsedNote(
        filename=path.name,
        filepath=str(path),
        title=title,
        content=raw,
        body=body,
        headings=headings,
        wiki_links=wiki_links,
        tags=tags,
        frontmatter_meta=meta,
    )


def parse_vault(vault_path: Path) -> list[ParsedNote]:
    """Parse all .md files in the vault directory."""
    notes = []
    md_files = sorted(vault_path.glob("*.md"))
    if not md_files:
        logger.warning("No .md files found in %s", vault_path)
        return notes

    for md_file in md_files:
        try:
            note = parse_note(md_file)
            notes.append(note)
            logger.debug("Parsed: %s  (links: %s)", note.filename, note.wiki_links)
        except Exception as e:
            logger.error("Failed to parse %s: %s", md_file.name, e)

    logger.info("Parsed %d notes from vault: %s", len(notes), vault_path)
    return notes


def chunk_note(note: ParsedNote, max_chars: int = 1000, overlap: int = 100) -> list[str]:
    """
    Split a note's body into overlapping text chunks.

    Strategy:
    1. Split on paragraph breaks (double newline).
    2. Merge paragraphs into chunks up to max_chars.
    3. Add overlap from the previous chunk.

    Returns a list of non-empty chunk strings.
    """
    body = note.body.strip()
    if not body:
        return []

    # Split into paragraphs
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", body) if p.strip()]

    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current_len + para_len > max_chars and current_parts:
            chunk_text = "\n\n".join(current_parts)
            chunks.append(chunk_text)
            # Overlap: keep last paragraph(s) up to `overlap` chars
            overlap_parts = []
            overlap_len = 0
            for p in reversed(current_parts):
                if overlap_len + len(p) > overlap:
                    break
                overlap_parts.insert(0, p)
                overlap_len += len(p)
            current_parts = overlap_parts
            current_len = overlap_len

        current_parts.append(para)
        current_len += para_len

    # Flush remaining
    if current_parts:
        chunks.append("\n\n".join(current_parts))

    # Filter out trivially short chunks (e.g. just a heading)
    return [c for c in chunks if len(c.strip()) > 40]


def extract_concept_name(wiki_link: str) -> str:
    """Normalise a wiki-link target to a canonical concept name."""
    # Spaces and underscores are equivalent in Obsidian
    return wiki_link.strip().replace("_", " ")
