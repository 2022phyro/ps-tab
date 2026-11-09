"""add_officials_affiliations_and_rbac

Revision ID: 181de544311f
Revises: b0a2ca65d129
Create Date: 2026-11-06 12:24:38.334377

"""
from typing import Sequence, Union
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import reflection


# revision identifiers, used by Alembic.
revision: str = '181de544311f'
down_revision: Union[str, Sequence[str], None] = 'b0a2ca65d129'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_TABROOM_PERMISSIONS = [
    ("settings:manage", "Tournament Settings", "Organization", "Configure tournament general settings, boundaries, and timetable"),
    ("documents:manage", "Documents & Repository", "Organization", "Upload, edit, and publish official documents and briefing slides"),
    ("rubric:manage", "Scoring Criteria & Rubric", "Organization", "Define scoring scales, speaker rubrics, and penalty rules"),
    ("speakers:manage", "Speakers Roster", "Organization", "Register, import, edit, and check in competitors"),
    ("judges:manage", "Judges & Panels", "Organization", "Accredit adjudicators, configure chair eligibility and independence"),
    ("officials:manage", "Officials & Staff", "Organization", "Manage official profiles and issue password setup links"),
    ("institutions:manage", "Institutions & Delegations", "Organization", "Merge, delete, export, and import delegation records"),
    ("authorization:manage", "Roles & Permissions (RBAC)", "Organization", "Create custom roles and grant/revoke access permissions"),
    ("rounds:manage", "Rounds & Pairings", "Rounds", "Generate draws, manage rooms, and verify ballots"),
    ("results:publish", "Publish Results", "Rounds", "Release round results, speaker tabs, and outround breaks"),
    ("equity:manage", "Equity & Complaints", "Equity", "Review equity incident reports and formal complaints"),
]

DEFAULT_TOURNAMENT_ROLES = [
    {
        "name": "Tournament Director",
        "description": "Full administrative control over all tournament organization and operations.",
        "permissions": [p[0] for p in DEFAULT_TABROOM_PERMISSIONS],
        "is_system": True,
    },
    {
        "name": "Tab Director",
        "description": "Full tabulation authority over speakers, judges, rounds, and pairings.",
        "permissions": [
            "documents:manage", "rubric:manage", "speakers:manage",
            "judges:manage", "institutions:manage", "rounds:manage", "results:publish"
        ],
        "is_system": True,
    },
    {
        "name": "Chief Adjudicator (CA)",
        "description": "Judging governance, rubric definition, panel assignments, and feedback.",
        "permissions": [
            "documents:manage", "rubric:manage", "judges:manage", "rounds:manage"
        ],
        "is_system": True,
    },
    {
        "name": "Deputy CA (DCA)",
        "description": "Adjudication team assistance, judge reviews, and panel assignments.",
        "permissions": [
            "documents:manage", "rubric:manage", "judges:manage", "rounds:manage"
        ],
        "is_system": True,
    },
    {
        "name": "Equity Officer",
        "description": "Equity guidelines, complaints handling, and participant welfare.",
        "permissions": [
            "documents:manage", "speakers:manage", "judges:manage", "equity:manage"
        ],
        "is_system": True,
    },
    {
        "name": "Organization Committee",
        "description": "Logistics, schedule, documents, institutions, and attendee registration.",
        "permissions": [
            "settings:manage", "documents:manage", "speakers:manage",
            "judges:manage", "institutions:manage"
        ],
        "is_system": True,
    },
    {
        "name": "Clerk / Room Staff",
        "description": "Participant check-in, document distribution, and ballot intake.",
        "permissions": [
            "documents:manage", "speakers:manage", "judges:manage"
        ],
        "is_system": True,
    },
]


def upgrade() -> None:
    conn = op.get_bind()
    insp = reflection.Inspector.from_engine(conn)
    existing_tables = set(insp.get_table_names())

    # 1. Create RBAC tables if not existing
    if "permissions" not in existing_tables:
        op.create_table(
            "permissions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("code", sa.String(length=80), nullable=False, unique=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("category", sa.String(length=50), nullable=False, server_default="General"),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index(op.f("ix_permissions_code"), "permissions", ["code"], unique=True)

    if "roles" not in existing_tables:
        op.create_table(
            "roles",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tournament_id", sa.String(length=36), sa.ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("tournament_id", "name", name="uq_roles_tournament_name"),
        )

    if "role_permissions" not in existing_tables:
        op.create_table(
            "role_permissions",
            sa.Column("role_id", sa.String(length=36), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("permission_id", sa.String(length=36), sa.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
        )

    if "official_role_assignments" not in existing_tables:
        op.create_table(
            "official_role_assignments",
            sa.Column("official_profile_id", sa.String(length=36), sa.ForeignKey("official_profiles.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("role_id", sa.String(length=36), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        )

    # 2. Update institutions table
    # Drop old unique constraint on name if present first
    inst_uqs = [u["name"] for u in insp.get_unique_constraints("institutions")]
    if "uq_institutions_tournament_name" in inst_uqs:
        op.drop_constraint("uq_institutions_tournament_name", "institutions", type_="unique")

    # Add name_normalized as nullable first
    inst_cols = [c["name"] for c in insp.get_columns("institutions")]
    if "name_normalized" not in inst_cols:
        op.add_column("institutions", sa.Column("name_normalized", sa.String(length=150), nullable=True))

    # Repoint duplicates and populate missing tournament_id with Oratoria or first tournament
    op.execute("""
        DO $$
        DECLARE
            target_t_id VARCHAR(36);
        BEGIN
            SELECT COALESCE(
                (SELECT id FROM tournaments WHERE slug = 'oratoria' LIMIT 1),
                (SELECT id FROM tournaments ORDER BY created_at ASC LIMIT 1)
            ) INTO target_t_id;

            IF target_t_id IS NOT NULL THEN
                -- Repoint participants
                UPDATE participants p
                SET institution_id = target_inst.id
                FROM institutions null_inst
                JOIN institutions target_inst ON lower(target_inst.name) = lower(null_inst.name) AND target_inst.tournament_id = target_t_id
                WHERE p.institution_id = null_inst.id AND null_inst.tournament_id IS NULL;

                -- Delete affiliations pointing to duplicate null_inst
                DELETE FROM participant_institutions pi
                USING institutions null_inst, institutions target_inst
                WHERE pi.institution_id = null_inst.id
                  AND null_inst.tournament_id IS NULL
                  AND target_inst.tournament_id = target_t_id
                  AND lower(target_inst.name) = lower(null_inst.name);

                -- Delete duplicate null_inst
                DELETE FROM institutions null_inst
                USING institutions target_inst
                WHERE null_inst.tournament_id IS NULL
                  AND target_inst.tournament_id = target_t_id
                  AND lower(target_inst.name) = lower(null_inst.name);

                -- Assign remaining NULL institutions to target_t_id
                UPDATE institutions
                SET tournament_id = target_t_id
                WHERE tournament_id IS NULL;
            END IF;
        END $$;
    """)

    # Populate name_normalized
    op.execute("""
        UPDATE institutions
        SET name_normalized = lower(regexp_replace(name, '[^a-zA-Z0-9 ]', '', 'g'))
        WHERE name_normalized IS NULL OR name_normalized = '';
    """)

    # Clean any potential name_normalized duplicates within the same tournament
    op.execute("""
        DELETE FROM institutions a
        USING institutions b
        WHERE a.id > b.id
          AND a.tournament_id = b.tournament_id
          AND a.name_normalized = b.name_normalized;
    """)

    op.alter_column("institutions", "name_normalized", nullable=False)
    op.alter_column("institutions", "tournament_id", existing_type=sa.VARCHAR(length=36), nullable=False)

    inst_indexes = [idx["name"] for idx in insp.get_indexes("institutions")]
    if "ix_institutions_name_normalized" not in inst_indexes:
        op.create_index("ix_institutions_name_normalized", "institutions", ["name_normalized"], unique=False)
    if "uq_institutions_tournament_name_normalized" not in inst_uqs:
        op.create_unique_constraint("uq_institutions_tournament_name_normalized", "institutions", ["tournament_id", "name_normalized"])

    # 3. Update official_profiles table
    off_cols = [c["name"] for c in insp.get_columns("official_profiles")]
    if "reset_token_hash" not in off_cols:
        op.add_column("official_profiles", sa.Column("reset_token_hash", sa.String(length=64), nullable=True))
    if "reset_token_expires_at" not in off_cols:
        op.add_column("official_profiles", sa.Column("reset_token_expires_at", sa.DateTime(timezone=True), nullable=True))

    op.alter_column("official_profiles", "role", existing_type=sa.VARCHAR(length=8), nullable=True)

    off_indexes = [idx["name"] for idx in insp.get_indexes("official_profiles")]
    if "ix_official_profiles_reset_token_hash" not in off_indexes:
        op.create_index("ix_official_profiles_reset_token_hash", "official_profiles", ["reset_token_hash"], unique=True)

    # 4. Update participant_institutions table
    part_inst_cols = [c["name"] for c in insp.get_columns("participant_institutions")]
    if "tie_type" not in part_inst_cols:
        op.add_column("participant_institutions", sa.Column("tie_type", sa.String(length=50), nullable=True, server_default="represents"))
    if "clash_policy" not in part_inst_cols:
        op.add_column("participant_institutions", sa.Column("clash_policy", sa.String(length=20), nullable=True, server_default="hard"))
    if "end_date" not in part_inst_cols:
        op.add_column("participant_institutions", sa.Column("end_date", sa.DateTime(timezone=True), nullable=True))

    op.execute("UPDATE participant_institutions SET tie_type = 'represents' WHERE tie_type IS NULL;")
    op.execute("UPDATE participant_institutions SET clash_policy = 'hard' WHERE clash_policy IS NULL;")
    op.alter_column("participant_institutions", "tie_type", nullable=False)
    op.alter_column("participant_institutions", "clash_policy", nullable=False)

    part_inst_uqs = [u["name"] for u in insp.get_unique_constraints("participant_institutions")]
    if "uq_participant_institution" in part_inst_uqs:
        op.drop_constraint("uq_participant_institution", "participant_institutions", type_="unique")
    if "uq_participant_inst_tie" not in part_inst_uqs:
        op.create_unique_constraint("uq_participant_inst_tie", "participant_institutions", ["participant_id", "institution_id", "tie_type"])

    # 5. Seed default permissions into permissions table
    from kwuo.core.typeid import generate_typeid
    for code, name, category, desc in DEFAULT_TABROOM_PERMISSIONS:
        op.execute(sa.text("""
            INSERT INTO permissions (id, code, name, category, description, created_at, updated_at)
            VALUES (:id, :code, :name, :category, :description, NOW(), NOW())
            ON CONFLICT (code) DO NOTHING;
        """).bindparams(
            id=generate_typeid("perm"),
            code=code,
            name=name,
            category=category,
            description=desc,
        ))

    # 6. Seed default roles for existing tournaments
    tournaments = conn.execute(sa.text("SELECT id FROM tournaments")).fetchall()
    for (t_id,) in tournaments:
        for r_spec in DEFAULT_TOURNAMENT_ROLES:
            existing_role = conn.execute(
                sa.text("SELECT id FROM roles WHERE tournament_id = :t_id AND name = :name"),
                {"t_id": t_id, "name": r_spec["name"]},
            ).fetchone()
            if existing_role:
                role_id = existing_role[0]
            else:
                role_id = generate_typeid("role")
                conn.execute(sa.text("""
                    INSERT INTO roles (id, tournament_id, name, description, is_system, created_at, updated_at)
                    VALUES (:id, :t_id, :name, :description, :is_system, NOW(), NOW())
                """), {
                    "id": role_id,
                    "t_id": t_id,
                    "name": r_spec["name"],
                    "description": r_spec["description"],
                    "is_system": r_spec["is_system"],
                })

            for p_code in r_spec["permissions"]:
                p_id_res = conn.execute(sa.text("SELECT id FROM permissions WHERE code = :code"), {"code": p_code}).fetchone()
                if p_id_res:
                    conn.execute(sa.text("""
                        INSERT INTO role_permissions (role_id, permission_id)
                        VALUES (:r_id, :p_id)
                        ON CONFLICT DO NOTHING;
                    """), {"r_id": role_id, "p_id": p_id_res[0]})


def downgrade() -> None:
    conn = op.get_bind()
    insp = reflection.Inspector.from_engine(conn)
    part_inst_uqs = [u["name"] for u in insp.get_unique_constraints("participant_institutions")]
    if "uq_participant_inst_tie" in part_inst_uqs:
        op.drop_constraint("uq_participant_inst_tie", "participant_institutions", type_="unique")
    if "uq_participant_institution" not in part_inst_uqs:
        op.create_unique_constraint("uq_participant_institution", "participant_institutions", ["participant_id", "institution_id"])

    op.drop_column("participant_institutions", "end_date")
    op.drop_column("participant_institutions", "clash_policy")
    op.drop_column("participant_institutions", "tie_type")

    op.drop_index("ix_official_profiles_reset_token_hash", table_name="official_profiles")
    op.drop_column("official_profiles", "reset_token_expires_at")
    op.drop_column("official_profiles", "reset_token_hash")

    inst_uqs = [u["name"] for u in insp.get_unique_constraints("institutions")]
    if "uq_institutions_tournament_name_normalized" in inst_uqs:
        op.drop_constraint("uq_institutions_tournament_name_normalized", "institutions", type_="unique")
    op.drop_index("ix_institutions_name_normalized", table_name="institutions")
    if "uq_institutions_tournament_name" not in inst_uqs:
        op.create_unique_constraint("uq_institutions_tournament_name", "institutions", ["tournament_id", "name"])
    op.alter_column("institutions", "tournament_id", existing_type=sa.VARCHAR(length=36), nullable=True)
    op.drop_column("institutions", "name_normalized")

