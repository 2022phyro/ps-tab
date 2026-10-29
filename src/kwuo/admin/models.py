"""ModelAdmin implementations and registrations for Kwuo core models."""

from typing import Any, List, Optional
from markupsafe import Markup
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from kwuo.admin.options import ModelAdmin, ActionItem
from kwuo.admin.site import admin_site
from kwuo.models.user import User, UserStatus, Group, GroupPermission, GroupMembership
from kwuo.models.audit import AuditLog, AuditSeverity
from kwuo.core.security import hash_password


class UserAdmin(ModelAdmin):
    category = "Authentication & Security"
    slug = "users"
    verbose_name = "User"
    verbose_name_plural = "Users"
    list_display = ("id", "full_name", "email", "status_badge",
                    "is_super_admin", "groups_list", "last_login", "created_at")
    list_filter = ("status", "is_admin")
    search_fields = ("first_name", "last_name", "email", "id")
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at", "updated_at", "auth_updated_at",
                       "last_login", "last_login_ip", "login_failed_attempts", "locked_until")
    actions = ["delete_selected", "activate_users", "suspend_users",
               "ban_users", "make_super_admin", "remove_super_admin"]

    async def get_queryset(self, db: AsyncSession):
        return (
            select(User)
            .options(
                selectinload(User.group_memberships)
                .selectinload(GroupMembership.group)
                .selectinload(Group.permissions)
            )
        )

    def status_badge(self, user: User) -> str:
        colors = {
            UserStatus.ACTIVE: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-400 border border-emerald-300 dark:border-emerald-800",
            UserStatus.UNVERIFIED: "bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-400 border border-amber-300 dark:border-amber-800",
            UserStatus.SUSPENDED: "bg-orange-100 text-orange-800 dark:bg-orange-950/40 dark:text-orange-400 border border-orange-300 dark:border-orange-800",
            UserStatus.BANNED: "bg-rose-100 text-rose-800 dark:bg-rose-950/40 dark:text-rose-400 border border-rose-300 dark:border-rose-800",
            UserStatus.DELETED: "bg-slate-100 text-slate-800 dark:bg-slate-950/40 dark:text-slate-400 border border-slate-300 dark:border-slate-800",
        }
        badge_cls = colors.get(user.status, "bg-slate-100 text-slate-800")
        label = user.status.value.upper()
        return Markup(f'<span class="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold font-body {badge_cls}">{label}</span>')

    def groups_list(self, user: User) -> str:
        if not user.group_memberships:
            return "—"
        names = [m.group.name for m in user.group_memberships if m.group]
        return ", ".join(names) if names else "—"

    def get_available_actions(self) -> List[ActionItem]:
        return [
            ActionItem(name="delete_selected",
                       description="Delete selected users"),
            ActionItem(name="activate_users",
                       description="Activate selected users"),
            ActionItem(name="suspend_users",
                       description="Suspend selected users (kills active sessions)"),
            ActionItem(
                name="ban_users", description="Permanently ban selected users (kills active sessions)"),
            ActionItem(name="make_super_admin",
                       description="Grant Super Admin privileges to selected"),
            ActionItem(name="remove_super_admin",
                       description="Revoke Super Admin privileges from selected"),
        ]


class GroupAdmin(ModelAdmin):
    category = "Authentication & Security"
    slug = "groups"
    verbose_name = "Group"
    verbose_name_plural = "Groups"
    list_display = ("id", "name", "scope_badge",
                    "permissions_count", "members_count", "created_at")
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
            ActionItem(name="delete_selected",
                       description="Delete selected groups"),
            ActionItem(name="clone_groups",
                       description="Clone selected groups (with permissions)"),
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
            ActionItem(name="delete_selected",
                       description="Delete selected permissions"),
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
            ActionItem(name="delete_selected",
                       description="Delete selected memberships"),
        ]


class AuditLogAdmin(ModelAdmin):
    category = "Compliance & Governance"
    slug = "audit-logs"
    verbose_name = "Audit Log"
    verbose_name_plural = "Audit Logs"
    list_display = ("id", "severity_badge", "action", "user_email",
                    "resource_type", "resource_id", "ip_address", "created_at")
    list_filter = ("severity", "action", "success")
    search_fields = ("action", "user_email", "resource_id", "ip_address")
    ordering = ("-created_at",)
    readonly_fields = (
        "id", "user_id", "user_email", "user_type", "action", "action_description",
        "resource_type", "resource_id", "resource_name", "ip_address", "user_agent",
        "request_method", "request_path", "request_id", "changes", "extra_data",
        "severity", "success", "error_message", "created_at",
    )
    actions = []

    def severity_badge(self, log: AuditLog) -> str:
        colors = {
            AuditSeverity.INFO.value: "bg-blue-100 text-blue-800 dark:bg-blue-950/40 dark:text-blue-400 border border-blue-300 dark:border-blue-800",
            AuditSeverity.WARNING.value: "bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-400 border border-amber-300 dark:border-amber-800",
            AuditSeverity.ERROR.value: "bg-rose-100 text-rose-800 dark:bg-rose-950/40 dark:text-rose-400 border border-rose-300 dark:border-rose-800",
            AuditSeverity.CRITICAL.value: "bg-purple-100 text-purple-800 dark:bg-purple-950/40 dark:text-purple-400 border border-purple-300 dark:border-purple-800",
        }
        badge_cls = colors.get(log.severity, "bg-slate-100 text-slate-800")
        return Markup(f'<span class="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-bold font-body {badge_cls}">{log.severity}</span>')

    def get_available_actions(self) -> List[ActionItem]:
        # Audit logs are immutable and cannot be deleted or bulk-manipulated
        return []


# Register all models with the AdminSite
admin_site.register(User, UserAdmin)
admin_site.register(Group, GroupAdmin)
admin_site.register(GroupPermission, GroupPermissionAdmin)
admin_site.register(GroupMembership, GroupMembershipAdmin)
admin_site.register(AuditLog, AuditLogAdmin)
