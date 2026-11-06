"""Comprehensive tests for Django-esque Admin Panel, ModelAdmins, and extended actions."""

import pytest
import re
from httpx import AsyncClient
from kwuo.core.security import SESSION_COOKIE_NAME


async def create_super_admin(client: AsyncClient) -> None:
    """Register first user (who becomes Super Admin) and set cookie."""
    res = await client.post(
        "/auth/register",
        data={"full_name": "Chief Tab Admin", "email": "admin@kwuo.org", "password": "Password123!"},
        follow_redirects=False,
    )
    client.cookies.set(SESSION_COOKIE_NAME, res.cookies[SESSION_COOKIE_NAME])


@pytest.mark.asyncio
async def test_admin_index_dashboard(client: AsyncClient):
    """Admin Index should display registered models, counts, and system metrics."""
    await create_super_admin(client)
    res = await client.get("/admin")
    assert res.status_code == 200
    assert "Site Administration" in res.text
    assert "Authentication &amp; Security" in res.text or "Authentication & Security" in res.text
    assert "Users" in res.text
    assert "Groups" in res.text
    assert "Group Permissions" in res.text
    assert "Group Memberships" in res.text
    assert "System Statistics" in res.text


@pytest.mark.asyncio
async def test_non_super_admin_forbidden_from_admin_index(client: AsyncClient):
    """Non-super admin cannot access /admin index or any admin route."""
    # First user is super admin
    await client.post(
        "/auth/register",
        data={"full_name": "First Admin", "email": "first@kwuo.org", "password": "Password123!"},
    )
    # Second user is normal organizer
    user_res = await client.post(
        "/auth/register",
        data={"full_name": "Normal User", "email": "normal@kwuo.org", "password": "Password123!"},
        follow_redirects=False,
    )
    client.cookies.set(SESSION_COOKIE_NAME, user_res.cookies[SESSION_COOKIE_NAME])

    admin_res = await client.get("/admin")
    assert admin_res.status_code == 403

    users_res = await client.get("/admin/users")
    assert users_res.status_code == 403


@pytest.mark.asyncio
async def test_user_changelist_search_and_filter(client: AsyncClient):
    """Changelist should support search and filter sidebar."""
    await create_super_admin(client)

    # Register another user
    await client.post(
        "/admin/users/add",
        data={
            "full_name": "Debate Coach Charlie",
            "email": "charlie@speech.edu",
            "password": "Password123!",
            "is_active": "true",
            "_action": "_save",
        },
        follow_redirects=True,
    )

    # 1. Test changelist view
    res = await client.get("/admin/users")
    assert res.status_code == 200
    assert "Debate Coach Charlie" in res.text
    assert "charlie@speech.edu" in res.text
    assert "Filter" in res.text

    # 2. Test search query (?q=Charlie)
    search_res = await client.get("/admin/users?q=Charlie")
    assert search_res.status_code == 200
    assert "Debate Coach Charlie" in search_res.text

    # Search with no match
    no_match_res = await client.get("/admin/users?q=NonExistentPerson")
    assert no_match_res.status_code == 200
    assert "No users found" in no_match_res.text


@pytest.mark.asyncio
async def test_user_bulk_actions(client: AsyncClient):
    """Bulk actions executor should toggle status and handle batch updates."""
    await create_super_admin(client)

    # Create two regular users
    await client.post(
        "/admin/users/add",
        data={
            "full_name": "Target User One",
            "email": "user1@speech.edu",
            "is_active": "true",
            "_action": "_save",
        },
        follow_redirects=True,
    )
    await client.post(
        "/admin/users/add",
        data={
            "full_name": "Target User Two",
            "email": "user2@speech.edu",
            "is_active": "true",
            "_action": "_save",
        },
        follow_redirects=True,
    )

    # Get user list to obtain their IDs
    list_page = await client.get("/admin/users")
    assert "user1@speech.edu" in list_page.text

    ids = re.findall(r'value="(usr_[a-z0-9]+)"', list_page.text)
    assert len(ids) >= 2

    bulk_res = await client.post(
        "/admin/users/action",
        data={
            "action": "suspend_users",
            "_selected_action": ids,
        },
        follow_redirects=True,
    )
    assert bulk_res.status_code == 200
    assert "Suspended" in bulk_res.text


@pytest.mark.asyncio
async def test_group_extended_actions_clone_and_assign(client: AsyncClient):
    """Group model extended actions: add/remove permissions, clone group, assign all users."""
    await create_super_admin(client)

    # 1. Create a group
    create_res = await client.post(
        "/admin/groups/add",
        data={
            "name": "Equity Committee",
            "description": "Handles tournament equity inquiries",
            "scope_type": "global",
            "_action": "_save",
        },
        follow_redirects=True,
    )
    assert create_res.status_code == 200
    assert "Equity Committee" in create_res.text

    # Find the group ID
    match = re.search(r'href="/admin/groups/(grp_[a-z0-9]+)"', create_res.text)
    assert match is not None
    group_id = match.group(1)

    # 2. Add permission to group
    add_perm_res = await client.post(
        f"/admin/groups/{group_id}/permissions/add",
        data={"permission": "equity:report:review"},
        follow_redirects=True,
    )
    assert add_perm_res.status_code == 200
    assert "equity:report:review" in add_perm_res.text

    # 3. Clone group
    clone_res = await client.post(
        f"/admin/groups/{group_id}/clone",
        follow_redirects=True,
    )
    assert clone_res.status_code == 200
    assert "Copy of Equity Committee" in clone_res.text

    # 4. Assign all active users to this group
    assign_res = await client.post(
        f"/admin/groups/{group_id}/assign-all",
        follow_redirects=True,
    )
    assert assign_res.status_code == 200
    assert "Assigned" in assign_res.text


@pytest.mark.asyncio
async def test_reset_user_password(client: AsyncClient):
    """Super Admin can directly set a new password for any user account."""
    await create_super_admin(client)

    # Create user
    await client.post(
        "/admin/users/add",
        data={
            "full_name": "Reset Target",
            "email": "target@kwuo.org",
            "password": "OldPassword1!",
            "is_active": "true",
            "_action": "_save",
        },
        follow_redirects=True,
    )

    list_page = await client.get("/admin/users?q=target@kwuo.org")
    match = re.search(r'href="/admin/users/(usr_[a-z0-9]+)"', list_page.text)
    assert match is not None
    target_id = match.group(1)

    # Reset password
    reset_res = await client.post(
        f"/admin/users/{target_id}/reset-password",
        data={"new_password": "NewBrandPassword2026!"},
        follow_redirects=True,
    )
    assert reset_res.status_code == 200
    assert "Password for Reset Target was updated successfully" in reset_res.text


@pytest.mark.asyncio
async def test_group_permission_edit_and_delete(client: AsyncClient):
    """Super Admin can view, edit, and delete GroupPermission records without integer PK mismatches."""
    await create_super_admin(client)

    # 1. Create a group
    create_res = await client.post(
        "/admin/groups/add",
        data={
            "name": "Adjudication Core",
            "description": "Tabulation & Scoring panel",
            "scope_type": "global",
            "_action": "_save",
        },
        follow_redirects=True,
    )
    assert create_res.status_code == 200
    match = re.search(r'href="/admin/groups/(grp_[a-z0-9]+)"', create_res.text)
    assert match is not None
    group_id = match.group(1)

    # 2. Add permission to group
    add_perm_res = await client.post(
        f"/admin/groups/{group_id}/permissions/add",
        data={"permission": "ballot:score:submit"},
        follow_redirects=True,
    )
    assert add_perm_res.status_code == 200

    # 3. View group-permissions changelist
    perms_list = await client.get("/admin/group-permissions")
    assert perms_list.status_code == 200
    assert "ballot:score:submit" in perms_list.text

    # Extract integer ID of permission
    perm_match = re.search(r'href="/admin/group-permissions/(\d+)"', perms_list.text)
    assert perm_match is not None
    perm_id = perm_match.group(1)

    # 4. View change form for group-permission
    change_view = await client.get(f"/admin/group-permissions/{perm_id}")
    assert change_view.status_code == 200
    assert "ballot:score:submit" in change_view.text

    # 5. Submit change to update permission string
    update_res = await client.post(
        f"/admin/group-permissions/{perm_id}",
        data={
            "group_id": group_id,
            "permission": "ballot:score:finalize",
            "_action": "_save",
        },
        follow_redirects=True,
    )
    assert update_res.status_code == 200
    assert "was changed successfully" in update_res.text
    assert "ballot:score:finalize" in update_res.text

    # 6. Delete permission
    delete_res = await client.post(
        f"/admin/group-permissions/{perm_id}/delete",
        follow_redirects=True,
    )
    assert delete_res.status_code == 200
    assert "Successfully deleted" in delete_res.text


@pytest.mark.asyncio
async def test_audit_logs_read_only_and_export(client: AsyncClient):
    """Audit logs are strictly immutable: cannot be added, deleted, or mutated, and can be exported as JSON."""
    await create_super_admin(client)

    # 1. Accessing /admin/audit-logs/add should redirect
    add_attempt = await client.get("/admin/audit-logs/add", follow_redirects=False)
    assert add_attempt.status_code == 302
    assert "/admin/audit-logs" in add_attempt.headers["location"]

    # 2. View audit logs changelist
    logs_page = await client.get("/admin/audit-logs")
    assert logs_page.status_code == 200
    assert "Select audit log to inspect" in logs_page.text
    assert "Add Audit Log" not in logs_page.text
    # Filter sidebar shows severity choices
    assert "INFO" in logs_page.text or "Info" in logs_page.text

    # Extract an audit log ID if present
    log_match = re.search(r'value="(aud_[a-z0-9]+)"', logs_page.text)
    if log_match:
        log_id = log_match.group(1)

        # Attempt to delete should fail/be rejected
        del_attempt = await client.post(
            f"/admin/audit-logs/{log_id}/delete",
            follow_redirects=False,
        )
        assert del_attempt.status_code == 302
        assert "cannot be deleted" in del_attempt.headers["location"] or "msg=" in del_attempt.headers["location"]

        # Bulk export as JSON
        export_res = await client.post(
            "/admin/audit-logs/action",
            data={
                "action": "export_json",
                "_selected_action": [log_id],
            },
        )
        assert export_res.status_code == 200
        assert export_res.headers["content-type"].startswith("application/json")
        data = export_res.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["id"] == log_id


@pytest.mark.asyncio
async def test_admin_aside_navigation_present_on_all_pages(client: AsyncClient):
    """Ergonomic aside navigation with app sections and models is present across all admin pages."""
    await create_super_admin(client)

    for path in ["/admin", "/admin/users", "/admin/groups", "/admin/group-permissions", "/admin/audit-logs"]:
        res = await client.get(path)
        assert res.status_code == 200
        # Check that aside navigation contains key model links
        assert 'href="/admin/users"' in res.text
        assert 'href="/admin/groups"' in res.text
        assert 'href="/admin/audit-logs"' in res.text
        assert "Admin Dashboard" in res.text

