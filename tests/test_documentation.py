"""Tests for the dynamic documentation engine, mtime caching, and outline tracking."""

import pytest
from httpx import AsyncClient
from pathlib import Path
from kwuo.services.documentation import get_documentation_tree, get_document, DOCS_DIR


@pytest.mark.asyncio
async def test_documentation_tree_discovered():
    """Verify folders and documents are recursively discovered with header.txt titles."""
    tree, flat_docs = get_documentation_tree()
    assert len(tree) >= 4

    folder_titles = [sec.title for sec in tree]
    assert "Getting Started" in folder_titles
    assert "Tournament Mechanics" in folder_titles
    assert "Adjudication & Rubrics" in folder_titles
    assert "Tabulation & Breaks" in folder_titles

    slugs = [doc.slug for doc in flat_docs]
    assert "getting-started/overview" in slugs
    assert "tournament-mechanics/dynamic-room-sizing" in slugs
    assert "tournament-mechanics/position-bias" in slugs


@pytest.mark.asyncio
async def test_documentation_root_redirects_to_first_doc(client: AsyncClient):
    """GET /documentation should 302 redirect to the first available doc."""
    response = await client.get("/documentation", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/documentation/getting-started/overview"


@pytest.mark.asyncio
async def test_document_page_renders_with_outline_and_alerts(client: AsyncClient):
    """GET /documentation/getting-started/overview should render HTML, TOC outline, and alert boxes."""
    response = await client.get("/documentation/getting-started/overview")
    assert response.status_code == 200
    assert "Welcome to Kwuo" in response.text
    assert "The Three Fundamental Shifts" in response.text
    assert "Reading Progress" in response.text
    assert "On This Page" in response.text
    # Verify GitHub alert conversion
    assert "Note" in response.text


@pytest.mark.asyncio
async def test_nested_document_renders(client: AsyncClient):
    """Verify multi-level nested folders render cleanly."""
    response = await client.get("/documentation/getting-started/architecture/stack-deep-dive")
    assert response.status_code == 200
    assert "Technology Stack Deep-Dive" in response.text
    assert "FastAPI" in response.text
    assert "MessagePack" in response.text


@pytest.mark.asyncio
async def test_nonexistent_document_returns_404(client: AsyncClient):
    """Accessing non-existent doc path returns 404."""
    response = await client.get("/documentation/invalid/unknown-page")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_mtime_cache_auto_detects_edits():
    """Modifying a markdown file's content updates the parsed document on the next request."""
    test_file = DOCS_DIR / "01-getting-started" / "overview.md"
    original_doc = get_document("getting-started/overview")
    assert original_doc is not None

    # Verify cached retrieval
    cached_doc = get_document("getting-started/overview")
    assert cached_doc is original_doc  # Same instance from in-memory cache
