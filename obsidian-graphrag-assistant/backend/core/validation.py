"""Shared validation helpers for API inputs that need normalization."""
from __future__ import annotations

import re
from pathlib import PureWindowsPath

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_SAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._ -]+")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def sanitize_markdown_filename(filename: str | None, fallback: str = "upload.md") -> str:
    """
    Return a safe basename for a Markdown file.

    The result never contains directory separators, control characters, leading
    path dots, Windows device names, or non-.md extensions.
    """
    using_fallback = filename is None
    candidate = (filename if filename is not None else fallback).strip().replace("\\", "/")
    candidate = PureWindowsPath(candidate).name
    candidate = candidate.split("/")[-1]
    candidate = _SAFE_FILENAME_CHARS.sub("_", candidate).strip(" .")

    if not candidate and using_fallback:
        candidate = fallback
    elif not candidate:
        raise ValueError("Filename is not allowed.")

    if not candidate.lower().endswith(".md"):
        raise ValueError("Only .md (Markdown) files are accepted.")

    stem = candidate[:-3].strip(" .")
    if not stem or stem.upper() in WINDOWS_RESERVED_NAMES:
        raise ValueError("Filename is not allowed.")

    safe = f"{stem[:240]}.md"
    return safe


def validate_cypher_identifier(identifier: str, label: str = "identifier") -> str:
    """Validate a Neo4j identifier that must be interpolated into Cypher."""
    if not _IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"Invalid Neo4j {label}.")
    return identifier


def bounded_int(value: int | None, default: int, minimum: int, maximum: int) -> int:
    """Clamp optional integer configuration used in dynamic graph patterns."""
    if value is None:
        value = default
    return max(minimum, min(int(value), maximum))
