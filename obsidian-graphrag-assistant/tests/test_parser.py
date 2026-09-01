"""
Unit tests for the markdown parser.
No Neo4j or Gemini required.
"""
import pytest
from pathlib import Path
import tempfile
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.utils.markdown_parser import parse_note, parse_vault, chunk_note, extract_concept_name


SAMPLE_MD = """\
---
title: Test Note
tags: [test, sample]
---

# Test Note

This is a sample note about [[RAG]] and [[Embeddings]].

It also mentions [[Vector Database]] and [[Knowledge Graph|KG]].

## Section One

Some content here discussing [[Neo4j]] and [[GraphRAG]].
"""

SAMPLE_NO_FRONTMATTER = """\
# No Frontmatter

Just plain markdown with [[LLM]] and [[Python]] links.
"""

SAMPLE_EMPTY = ""


def _make_temp_note(content: str, filename: str = "test.md") -> Path:
    """Write content to a temp file and return the Path."""
    tmp = tempfile.mkdtemp()
    p = Path(tmp) / filename
    p.write_text(content, encoding="utf-8")
    return p


class TestParseNote:
    def test_basic_parse(self):
        p = _make_temp_note(SAMPLE_MD, "03_RAG.md")
        note = parse_note(p)
        assert note.filename == "03_RAG.md"
        assert note.title == "Test Note"
        assert "RAG" in note.wiki_links
        assert "Embeddings" in note.wiki_links
        assert "Vector Database" in note.wiki_links
        # Alias links: [[Knowledge Graph|KG]] → target is "Knowledge Graph"
        assert "Knowledge Graph" in note.wiki_links
        assert "Neo4j" in note.wiki_links
        assert "GraphRAG" in note.wiki_links

    def test_frontmatter_tags(self):
        p = _make_temp_note(SAMPLE_MD)
        note = parse_note(p)
        assert "test" in note.tags
        assert "sample" in note.tags

    def test_no_frontmatter(self):
        p = _make_temp_note(SAMPLE_NO_FRONTMATTER, "02_LLM.md")
        note = parse_note(p)
        assert note.title == "No Frontmatter"
        assert "LLM" in note.wiki_links
        assert "Python" in note.wiki_links
        assert note.tags == []

    def test_headings_extracted(self):
        p = _make_temp_note(SAMPLE_MD)
        note = parse_note(p)
        assert "Test Note" in note.headings
        assert "Section One" in note.headings

    def test_wiki_links_deduplicated(self):
        content = "[[RAG]] and [[RAG]] and [[RAG]]"
        p = _make_temp_note(content)
        note = parse_note(p)
        assert note.wiki_links.count("RAG") == 1

    def test_empty_file(self):
        p = _make_temp_note(SAMPLE_EMPTY)
        note = parse_note(p)
        assert note.wiki_links == []
        assert note.content == ""


class TestParseVault:
    def test_parse_vault(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "01_AI.md").write_text("# AI\n\n[[LLM]] and [[RAG]]", encoding="utf-8")
        (tmp / "02_LLM.md").write_text("# LLM\n\n[[AI]] and [[Embeddings]]", encoding="utf-8")
        notes = parse_vault(tmp)
        assert len(notes) == 2
        titles = [n.title for n in notes]
        assert "AI" in titles
        assert "LLM" in titles

    def test_empty_vault(self):
        tmp = Path(tempfile.mkdtemp())
        notes = parse_vault(tmp)
        assert notes == []


class TestChunkNote:
    def test_basic_chunking(self):
        p = _make_temp_note(SAMPLE_MD)
        note = parse_note(p)
        chunks = chunk_note(note, max_chars=200)
        assert len(chunks) >= 1
        for chunk in chunks:
            assert len(chunk.strip()) > 40

    def test_short_note_single_chunk(self):
        content = "# Short\n\nThis is a short note. " * 3
        p = _make_temp_note(content)
        note = parse_note(p)
        chunks = chunk_note(note, max_chars=2000)
        assert len(chunks) == 1

    def test_long_note_multiple_chunks(self):
        # Create a note with many paragraphs
        paragraphs = "\n\n".join([f"Paragraph {i}: " + "word " * 30 for i in range(20)])
        p = _make_temp_note(f"# Long\n\n{paragraphs}")
        note = parse_note(p)
        chunks = chunk_note(note, max_chars=300)
        assert len(chunks) > 1


class TestExtractConceptName:
    def test_basic(self):
        assert extract_concept_name("RAG") == "RAG"

    def test_underscores(self):
        assert extract_concept_name("Vector_Database") == "Vector Database"

    def test_whitespace(self):
        assert extract_concept_name("  LLM  ") == "LLM"
