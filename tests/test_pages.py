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
async def test_home_page_five_sections_and_cultural_instruments(client: AsyncClient):
    """Verify Home page renders all 5 required sections, Kakaki, Talking Drum, and interactive showcase."""
    res = await client.get("/")
    assert res.status_code == 200

    # 01 Hero Section & Cultural Forensics Instruments
    assert "Tired of Terrifying Tabs" in res.text or "Flawless tabulation for" in res.text
    assert "Say no more" in res.text or "tertiary public speaking" in res.text
    assert "Kakaki" in res.text
    assert "Talking Drum" in res.text

    # 02 Core Capabilities
    assert "02 Core Capabilities" in res.text or "Engineered for Speech" in res.text
    assert "Digital Ballots &amp; Instant Magic QR" in res.text or "Digital Ballots" in res.text
    assert "Section Allocation &amp; Bias Rotation" in res.text or "Section Allocation" in res.text
    assert "Controlled State-Gated Publishing" in res.text or "Controlled Publishing" in res.text

    # 03 How It Works
    assert "03 How It Works" in res.text or "Organise &bull; Adjudicate &bull; Tabulate" in res.text
    assert "Organise &bull; Adjudicate &bull; Tabulate" in res.text or "Organise" in res.text

    # 04 Product Showcase
    assert "04 Product Showcase" in res.text or "Real Interface Previews" in res.text
    assert "Latin-Square" in res.text or "Room Balancing" in res.text
    assert "Live Mobile Ballot" in res.text

    # 05 Contact / Get Started
    assert "05 Contact" in res.text or "Ready to Host" in res.text
    assert "Instant Tournament Setup" in res.text


@pytest.mark.asyncio
async def test_header_scroll_and_reverse_footer_wave(client: AsyncClient):
    """Verify base template includes scroll-aware header and reverse wavy footer divider."""
    res = await client.get("/")
    assert res.status_code == 200
    assert "headerHidden" in res.text
    assert "-translate-y-full" in res.text
    assert "rotate-180" in res.text  # Reversed wavy border on top of footer


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
    assert "v0.1.0" in res.text


@pytest.mark.asyncio
async def test_button_design_showcase_page(client: AsyncClient):
    """Verify /design route renders high-fidelity Kwuo Editorial Design Specification with all 3 components."""
    # Test primary /design route
    res = await client.get("/design")
    assert res.status_code == 200
    assert "The Kwuo Design System" in res.text or "The Kwuo Button" in res.text
    assert "Full Solid" in res.text or "Primary" in res.text
    assert "kwuo-btn" in res.text
    assert "kwuo-btn-primary" in res.text
    assert "kwuo-btn-secondary" in res.text
    assert "kwuo-btn-outline" in res.text
    assert "kwuo-btn-alternate" in res.text
    assert "kwuo-btn-pill" in res.text
    assert "Torn-Docket" in res.text
    assert "Wind-Curled" in res.text
    assert "kwuo-post-it-right" in res.text
    assert "kwuo-post-it-left" in res.text
    assert "URGENT BRIEFING" in res.text
    assert "Room 204" in res.text

    # Test /design/button redirect
    res_redirect = await client.get("/design/button", follow_redirects=True)
    assert res_redirect.status_code == 200
    assert "The Kwuo Design System" in res_redirect.text or "The Kwuo Button" in res_redirect.text
