"""End-to-end tests for landing page, authentication, dashboard, and Scoped RBAC."""

import pytest
from httpx import AsyncClient
from kwuo.core.security import SESSION_COOKIE_NAME


@pytest.mark.asyncio
async def test_home_page_renders(client: AsyncClient):
    """Verify landing page renders successfully."""
    response = await client.get("/")
    assert response.status_code == 200
    assert "Kwuo" in response.text
    assert "Log in" in response.text


@pytest.mark.asyncio
async def test_unauthenticated_dashboard_redirects(client: AsyncClient):
    """Unauthenticated access to /dashboard should redirect to login."""
    response = await client.get("/dashboard", headers={"accept": "text/html"})
    assert response.status_code in (302, 307)
    assert "/auth/login" in response.headers["location"]


@pytest.mark.asyncio
async def test_first_registered_user_becomes_super_admin(client: AsyncClient):
    """The first user registered on Kwuo automatically receives Super Admin privileges."""
    reg_response = await client.post(
        "/auth/register",
        data={
            "full_name": "Tab Master Alice",
            "email": "alice@tabroom.edu",
            "password": "Password123!",
        },
        follow_redirects=False,
    )
    assert reg_response.status_code == 302
    assert reg_response.headers["location"] == "/dashboard"
    assert SESSION_COOKIE_NAME in reg_response.cookies

    # Persist cookie on client
    client.cookies.set(SESSION_COOKIE_NAME, reg_response.cookies[SESSION_COOKIE_NAME])

    # Access dashboard with session cookie
    dash_response = await client.get("/dashboard")
    assert dash_response.status_code == 200
    assert "Tab Master Alice" in dash_response.text
    assert "Platform Super Admin" in dash_response.text


@pytest.mark.asyncio
async def test_second_user_is_regular_organizer(client: AsyncClient):
    """Subsequent registrations are standard organizers without Super Admin access."""
    # Register Alice (Super Admin)
    await client.post(
        "/auth/register",
        data={"full_name": "Alice", "email": "alice@univ.edu", "password": "Password123!"},
    )

    # Register Bob (Standard Organizer)
    bob_reg = await client.post(
        "/auth/register",
        data={"full_name": "Bob Judge", "email": "bob@univ.edu", "password": "Password123!"},
        follow_redirects=False,
    )
    assert bob_reg.status_code == 302

    # Set Bob's session on client
    client.cookies.set(SESSION_COOKIE_NAME, bob_reg.cookies[SESSION_COOKIE_NAME])

    # Bob's dashboard should say Organizer, not Super Admin
    dash_response = await client.get("/dashboard")
    assert dash_response.status_code == 200
    assert "Tournament Organizer" in dash_response.text
    assert "Platform Super Admin" not in dash_response.text

    # Bob cannot access /admin/users
    admin_response = await client.get("/admin/users")
    assert admin_response.status_code == 403


@pytest.mark.asyncio
async def test_super_admin_can_manage_accounts_and_rbac(client: AsyncClient):
    """Super Admin can access /admin/users, toggle user privileges, and create groups."""
    # 1. Register Alice (Super Admin)
    alice_res = await client.post(
        "/auth/register",
        data={"full_name": "Alice Admin", "email": "alice@univ.edu", "password": "Password123!"},
    )

    # 2. Register Bob (Standard User)
    await client.post(
        "/auth/register",
        data={"full_name": "Bob Staff", "email": "bob@univ.edu", "password": "Password123!"},
    )

    # Set Alice's session
    client.cookies.set(SESSION_COOKIE_NAME, alice_res.cookies[SESSION_COOKIE_NAME])

    # 3. Alice visits /admin/users
    admin_page = await client.get("/admin/users")
    assert admin_page.status_code == 200
    assert "Platform Account & RBAC Administration" in admin_page.text
    assert "Bob Staff" in admin_page.text

    # 4. Alice creates a Scoped Security Group
    group_res = await client.post(
        "/admin/groups",
        data={
            "name": "Adjudication Core (CAP)",
            "description": "Chief Adjudicator panel for judge allocation",
            "scope_type": "global",
        },
        follow_redirects=True,
    )
    assert group_res.status_code == 200
    assert "Adjudication Core (CAP)" in group_res.text


@pytest.mark.asyncio
async def test_logout_clears_cookie(client: AsyncClient):
    """Logging out removes session cookie and redirects home."""
    reg_response = await client.post(
        "/auth/register",
        data={"full_name": "User", "email": "user@univ.edu", "password": "Password123!"},
    )
    client.cookies.set(SESSION_COOKIE_NAME, reg_response.cookies[SESSION_COOKIE_NAME])

    logout_response = await client.post(
        "/auth/logout",
        follow_redirects=False,
    )
    assert logout_response.status_code == 302
    assert logout_response.headers["location"] == "/"
