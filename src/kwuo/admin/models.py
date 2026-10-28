"""ModelAdmin implementations and registrations for Kwuo core models."""

from typing import Any, List, Optional
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kwuo.admin.options import ModelAdmin, ActionItem
from kwuo.admin.site import admin_site
from kwuo.models.user import User, Group, GroupPermission, GroupMembership
from kwuo.core.security import hash_password


class UserAdmin(ModelAdmin):
    category = "Authentication & Security"
    slug = "users"
    verbose_name = "User"
    verbose_name_plural = "Users"
    list_display = ("id", "full_name", "email", "is_super_admin", "is_active", "groups_list", "created_at")
    list_filter = ("is_super_admin", "is_active")
    search_fields = ("full_name", "email", "id")
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at", "updated_at")
    actions = ["delete_selected", "activate_users", "suspend_users", "make_super_admin", "remove_super_admin"]

    async def get_queryset(self, db: AsyncSession):
        return (
            select(User)
            .options(
                selectinload(User.group_memberships)
                .selectinload(GroupMembership.group)
                .selectinload(Group.permissions)
            )
        )

    def groups_list(self, user: User) -> str:
        if not user.group_memberships:
            return "—"
        names = [m.group.name for m in user.group_memberships if m.group]
        return ", ".join(names) if names else "—"

    def get_available_actions(self) -> List[ActionItem]:
        return [
            ActionItem(name="delete_selected", description="Delete selected users"),
            ActionItem(name="activate_users", description="Activate selected users"),
            ActionItem(name="suspend_users", description="Suspend selected users"),
            ActionItem(name="make_super_admin", description="Grant Super Admin privileges to selected"),
            ActionItem(name="remove_super_admin", description="Revoke Super Admin privileges from selected"),
        ]


class GroupAdmin(ModelAdmin):
    category = "Authentication & Security"
    slug = "groups"
    verbose_name = "Group"
    verbose_name_plural = "Groups"
    list_display = ("id", "name", "scope_badge", "permissions_count", "members_count", "created_at")
    search_fields = ("name", "description", "id", "tournament_id")
    ordering = ("name",)
    readonly_fields = ("id", "created_at", "updated_at")
    actions = ["delete_selected", "clone_groups"]

    async def get_queryset(self, db: AsyncSession):
        return (
            select(Group)
            .options(
                selectinload(Group.permissions),
                selectinload(Group.memberships),
            )
        )

    def scope_badge(self, group: Group) -> str:
        if group.tournament_id:
            return f"Tournament ({group.tournament_id})"
        return "Global (All Tournaments)"

    def permissions_count(self, group: Group) -> int:
        return len(group.permissions) if group.permissions else 0

    def members_count(self, group: Group) -> int:
        return len(group.memberships) if group.memberships else 0

    def get_available_actions(self) -> List[ActionItem]:
        return [
            ActionItem(name="delete_selected", description="Delete selected groups"),
            ActionItem(name="clone_groups", description="Clone selected groups (with permissions)"),
        ]


class GroupPermissionAdmin(ModelAdmin):
    category = "Authentication & Security"
    slug = "group-permissions"
    verbose_name = "Group Permission"
    verbose_name_plural = "Group Permissions"
    list_display = ("id", "permission", "group_name", "group_id")
    search_fields = ("permission", "group_id")
    ordering = ("permission",)
    readonly_fields = ("id",)
    actions = ["delete_selected"]

    async def get_queryset(self, db: AsyncSession):
        return select(GroupPermission).options(selectinload(GroupPermission.group))

    def group_name(self, perm: GroupPermission) -> str:
        return perm.group.name if perm.group else perm.group_id

    def get_available_actions(self) -> List[ActionItem]:
        return [
            ActionItem(name="delete_selected", description="Delete selected permissions"),
        ]


class GroupMembershipAdmin(ModelAdmin):
    category = "Authentication & Security"
    slug = "group-memberships"
    verbose_name = "Group Membership"
    verbose_name_plural = "Group Memberships"
    list_display = ("id", "user_display", "group_display", "created_at")
    search_fields = ("user_id", "group_id")
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at", "updated_at")
    actions = ["delete_selected"]

    async def get_queryset(self, db: AsyncSession):
        return (
            select(GroupMembership)
            .options(
                selectinload(GroupMembership.user),
                selectinload(GroupMembership.group),
            )
        )

    def user_display(self, membership: GroupMembership) -> str:
        if membership.user:
            return f"{membership.user.full_name} ({membership.user.email})"
        return membership.user_id

    def group_display(self, membership: GroupMembership) -> str:
        if membership.group:
            return membership.group.name
        return membership.group_id

    def get_available_actions(self) -> List[ActionItem]:
        return [
            ActionItem(name="delete_selected", description="Delete selected memberships"),
        ]


# Register all models with the AdminSite
admin_site.register(User, UserAdmin)
admin_site.register(Group, GroupAdmin)
admin_site.register(GroupPermission, GroupPermissionAdmin)
admin_site.register(GroupMembership, GroupMembershipAdmin)
