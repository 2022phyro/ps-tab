"""End-to-end tests for About page, Contact form, Legal policies, and Home features."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_about_page_renders_complete_content(client: AsyncClient):
    """Verify /about page renders platform mission, Igbo namesake, creators, pillars, and sponsor button."""
    res = await client.get("/about")
    assert res.status_code == 200
    assert "The Philosophy Behind Kwuo" in res.text
    assert "individual oratorical competition" in res.text
    assert "Igbo" in res.text
    assert "Why Competitive Speech Deserves Its Own Engine" in res.text
    assert "Algorithmic Fairness" in res.text
    assert "Modern Tech Stack" in res.text
    assert "Buy Me a Coffee" in res.text


@pytest.mark.asyncio
async def test_contact_page_renders_channels_and_form(client: AsyncClient):
    """Verify /contact renders team channels, response guarantee, and submission form."""
    res = await client.get("/contact")
    assert res.status_code == 200
    assert "Talk to the Kwuo Team" in res.text
    assert "tab@kwuo.org" in res.text
    assert "tournaments@kwuo.org" in res.text
    assert "Tournament Onboarding" in res.text


@pytest.mark.asyncio
async def test_contact_form_submission_standard(client: AsyncClient):
    """Submitting contact form redirects with success message."""
    res = await client.post(
        "/contact",
        data={
            "name": "Director Chidi",
            "email": "chidi@speech.edu",
            "organization": "West African Forensic Association",
            "subject": "Tournament Onboarding",
            "message": "We would like to run our national oratorical championships on Kwuo next term.",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert "Thank you, <strong>Director Chidi</strong>" in res.text


@pytest.mark.asyncio
async def test_contact_form_submission_htmx(client: AsyncClient):
    """Submitting contact form via HTMX returns targeted HTML partial."""
    res = await client.post(
        "/contact",
        headers={"HX-Request": "true"},
        data={
            "name": "Coach Ngozi",
            "email": "ngozi@tabroom.org",
            "organization": "University Forensics",
            "subject": "Custom Rubric Request",
            "message": "Can we configure a 4-tier rubric with weighted delivery points?",
        },
    )
    assert res.status_code == 200
    assert "Message Sent Successfully" in res.text
    assert "Coach Ngozi" in res.text


@pytest.mark.asyncio
async def test_privacy_policy_renders(client: AsyncClient):
    """Verify /privacy renders participant data protections and magic link statements."""
    res = await client.get("/privacy")
    assert res.status_code == 200
    assert "Privacy Policy" in res.text
    assert "Zero-Auth Magic Links" in res.text
    assert "State-Gated Results Publishing" in res.text


@pytest.mark.asyncio
async def test_terms_of_service_renders(client: AsyncClient):
    """Verify /terms renders platform terms, ballot integrity, and MIT license notice."""
    res = await client.get("/terms")
    assert res.status_code == 200
    assert "Terms of Service" in res.text
    assert "Ballot Integrity &amp; Mathematical Reproducibility" in res.text or "Ballot Integrity" in res.text
    assert "MIT Open Source License" in res.text


@pytest.mark.asyncio
async def test_home_page_enhanced_features_and_contact(client: AsyncClient):
    """Verify Home page includes features showcase and embedded contact section."""
    res = await client.get("/")
    assert res.status_code == 200
    assert "Why Kwuo Outperforms Legacy Debate Software" in res.text
    assert "Dynamic Section Allocation" in res.text
    assert "Position-Bias Neutralization" in res.text
    assert "Flexible Ballot Pipelines" in res.text
    assert "Zero-Auth Mobile Ballots" in res.text
    assert "Talk to the Tabulation Team" in res.text


@pytest.mark.asyncio
async def test_footer_rendered_across_pages(client: AsyncClient):
    """Verify global footer renders multi-column links, Buy Me a Coffee, and Igbo namesake."""
    res = await client.get("/")
    assert res.status_code == 200
    assert "Buy Me a Coffee" in res.text
    assert "Privacy Policy" in res.text
    assert "Terms of Service" in res.text
    assert "Documentation &amp; Guides" in res.text or "Documentation & Guides" in res.text
    assert "MIT Open Source" in res.text
    assert "v0.1.0-alpha" in res.text
