import "dotenv/config";
import { PrismaClient } from "../src/generated/prisma/client";
import { PrismaPg } from "@prisma/adapter-pg";

const adapter = new PrismaPg({ connectionString: process.env.DATABASE_URL! });
const prisma = new PrismaClient({ adapter });

// docs/03's permission matrix, as a seeded catalog — see prisma/schema.prisma
// "Roles & permissions (Grouped RBAC)". Organizers assign these to Groups;
// they don't invent new permission keys themselves.
const PERMISSIONS = [
  { key: "tournament.configure", description: "Configure rubrics, break rules, room bounds" },
  { key: "tournament.manage_staff", description: "Add/remove collaborators (owner only)" },
  { key: "tournament.delete", description: "Delete the tournament (owner only)" },
  { key: "draws.generate", description: "Run check-in, generate draws" },
  { key: "draws.override", description: "Manual draw/judge overrides, hot-swaps" },
  { key: "judges.hotswap", description: "Swap a missing judge with a reserve" },
  { key: "rounds.advance", description: "Advance a round through its lifecycle" },
  { key: "publish.draws", description: "Release a round's draws" },
  { key: "publish.results", description: "Release a round's results" },
  { key: "publish.standings", description: "Release cumulative standings" },
  { key: "rounds.lock_override", description: "Unlock a locked round (Super Admin escalation)" },
  { key: "audit.view", description: "View the tournament's audit log" },
  { key: "roster.manage", description: "Bulk import / edit the full roster" },
  {
    key: "roster.manage_own_institution",
    description: "Edit/scratch one institution's own entries",
  },
  {
    key: "circuit.configure",
    description: "Configure circuit points rules and qualification thresholds",
  },
  { key: "circuit.manage_membership", description: "Add/remove tournaments from a circuit" },
] as const;

async function seedPermissions() {
  const permissions = new Map<string, string>();
  for (const p of PERMISSIONS) {
    const row = await prisma.permission.upsert({
      where: { key: p.key },
      update: { description: p.description },
      create: p,
    });
    permissions.set(p.key, row.id);
  }
  return permissions;
}

async function main() {
  const permissions = await seedPermissions();

  const owner = await prisma.user.upsert({
    where: { email: "director@example.com" },
    update: {},
    create: {
      name: "Sample Tournament Director",
      email: "director@example.com",
    },
  });

  const coach = await prisma.user.upsert({
    where: { email: "coach@example.com" },
    update: {},
    create: {
      name: "Lincoln HS Coach",
      email: "coach@example.com",
    },
  });

  const circuitAdmin = await prisma.user.upsert({
    where: { email: "circuitadmin@example.com" },
    update: {},
    create: {
      name: "Fall Circuit Administrator",
      email: "circuitadmin@example.com",
    },
  });

  const superAdminUser = await prisma.user.upsert({
    where: { email: "superadmin@example.com" },
    update: {},
    create: {
      name: "Platform Super Admin",
      email: "superadmin@example.com",
    },
  });

  // Platform-global Group — tournamentId AND circuitId both null. Seeded
  // once; every permission, since Super Admin's whole point (docs/03) is
  // emergency/support access across the entire platform.
  //
  // Nullable fields inside a compound @@unique are unreliable to target with
  // Prisma's upsert/findUnique (Postgres itself treats NULL as non-equal to
  // NULL, and Prisma's generated compound-key input doesn't handle this
  // cleanly) — find-then-create instead rather than fighting that.
  let superAdminGroup = await prisma.group.findFirst({
    where: { name: "Super Admin", tournamentId: null, circuitId: null },
  });
  if (!superAdminGroup) {
    superAdminGroup = await prisma.group.create({
      data: {
        name: "Super Admin",
        isDefault: true,
        permissions: {
          create: [...permissions.values()].map((permissionId) => ({ permissionId })),
        },
      },
    });
  }

  const existingSuperAdminMembership = await prisma.groupMembership.findFirst({
    where: { groupId: superAdminGroup.id, userId: superAdminUser.id },
  });
  if (!existingSuperAdminMembership) {
    await prisma.groupMembership.create({
      data: { groupId: superAdminGroup.id, userId: superAdminUser.id },
    });
  }

  const tournament = await prisma.tournament.create({
    data: {
      name: "Riverside Invitational",
      slug: "riverside-invitational",
      state: "ACTIVE",
      ownerId: owner.id,
    },
  });

  // Default Groups for this tournament (docs/03) — "Tab Staff" and
  // "Institution Coordinator" are seeded per-tournament rather than global,
  // since their permission set only makes sense scoped to one tournament.
  const tabStaffGroup = await prisma.group.create({
    data: {
      name: "Tab Staff",
      isDefault: true,
      tournamentId: tournament.id,
      permissions: {
        create: [
          "tournament.configure",
          "draws.generate",
          "draws.override",
          "judges.hotswap",
          "rounds.advance",
          "publish.draws",
          "publish.results",
          "publish.standings",
          "roster.manage",
          "audit.view",
        ].map((key) => ({ permissionId: permissions.get(key)! })),
      },
    },
  });

  const coordinatorGroup = await prisma.group.create({
    data: {
      name: "Institution Coordinator",
      isDefault: true,
      tournamentId: tournament.id,
      permissions: {
        create: [{ permissionId: permissions.get("roster.manage_own_institution")! }],
      },
    },
  });

  // Owner sits in the Tab Staff group too — ownership itself (tournament.delete,
  // tournament.manage_staff) stays a dedicated Tournament.ownerId check rather
  // than a permission, per docs/03's owner-vs-collaborator distinction.
  await prisma.groupMembership.create({
    data: { groupId: tabStaffGroup.id, userId: owner.id },
  });

  const institutionNames = ["Lincoln High School", "Brookfield Academy", "Riverside Prep"];
  const institutions = await Promise.all(
    institutionNames.map((name) =>
      prisma.institution.create({
        data: { tournamentId: tournament.id, name },
      }),
    ),
  );

  // Coordinator membership is narrowed to one institution (Lincoln High
  // School) — the Group defines *what* a coordinator can do, this row
  // defines *which* institution this particular coordinator is scoped to.
  await prisma.groupMembership.create({
    data: {
      groupId: coordinatorGroup.id,
      userId: coach.id,
      institutionId: institutions[0]!.id,
    },
  });

  // A circuit this tournament belongs to, with its own Circuit Administrator
  // group/permissions — demonstrates the circuit-scoped side of Grouped RBAC.
  const circuit = await prisma.circuit.create({
    data: {
      name: "Fall Season Circuit",
      ownerId: circuitAdmin.id,
      breakCount: 20,
      dropWorstCount: 2,
    },
  });

  await prisma.circuitMembership.create({
    data: { circuitId: circuit.id, tournamentId: tournament.id },
  });

  const circuitAdminGroup = await prisma.group.create({
    data: {
      name: "Circuit Administrator",
      isDefault: true,
      circuitId: circuit.id,
      permissions: {
        create: [
          { permissionId: permissions.get("circuit.configure")! },
          { permissionId: permissions.get("circuit.manage_membership")! },
        ],
      },
    },
  });

  await prisma.groupMembership.create({
    data: { groupId: circuitAdminGroup.id, userId: circuitAdmin.id },
  });

  const open = await prisma.division.create({
    data: {
      tournamentId: tournament.id,
      name: "Open",
      roomSizeMin: 4,
      roomSizeMax: 8,
      breakType: "FIXED_COUNT",
      breakCount: 6,
      dropWorstCount: 1,
    },
  });

  const rubric = await prisma.rubric.create({
    data: {
      tournamentId: tournament.id,
      divisionId: open.id,
      name: "Standard Prepared Speech",
      criteria: {
        create: [
          { name: "Content", maxPoints: 30, order: 1 },
          { name: "Delivery", maxPoints: 30, order: 2 },
          { name: "Structure", maxPoints: 20, order: 3 },
          { name: "Language Use", maxPoints: 20, order: 4 },
        ],
      },
      timePenaltyPolicy: {
        create: {
          allowedSeconds: 360,
          graceSeconds: 10,
          penaltyPerInterval: 1,
          intervalSeconds: 5,
          maxPenalty: 10,
        },
      },
    },
  });

  // 20 speakers spread across 3 institutions + a few independents
  const speakerNames = [
    "A. Okafor",
    "J. Reyes",
    "M. Chen",
    "T. Adeyemi",
    "S. Patel",
    "L. Nguyen",
    "R. Garcia",
    "K. Johnson",
    "D. Kim",
    "F. Rossi",
    "P. Singh",
    "N. Ibrahim",
    "C. Martins",
    "B. Novak",
    "E. Larsen",
    "H. Osei",
    "V. Petrov",
    "W. Tanaka",
    "G. Silva",
    "Y. Haddad",
  ];

  const speakers = await Promise.all(
    speakerNames.map((name, i) =>
      prisma.speaker.create({
        data: {
          tournamentId: tournament.id,
          divisionId: open.id,
          institutionId: i % 4 === 0 ? null : institutions[i % institutions.length]!.id,
          name,
          email: `${name.replace(/[^a-z]/gi, "").toLowerCase()}@example.com`,
        },
      }),
    ),
  );

  const round1 = await prisma.round.create({
    data: {
      divisionId: open.id,
      roundNumber: 1,
      kind: "PRELIM",
      rubricId: rubric.id,
      drawsState: "RELEASED",
      resultsState: "RELEASED",
      standingsState: "RELEASED",
    },
  });

  // One completed room, 6 speakers, single-judge panel, full ballots
  const roomSpeakers = speakers.slice(0, 6);
  const section = await prisma.section.create({
    data: {
      roundId: round1.id,
      roomLabel: "Room 1",
      assignments: {
        create: roomSpeakers.map((s, i) => ({ speakerId: s.id, position: i + 1 })),
      },
    },
  });

  const judge = await prisma.judge.create({
    data: {
      tournamentId: tournament.id,
      institutionId: null,
      name: "R. Whitfield",
      email: "rwhitfield@example.com",
      chairEligible: true,
    },
  });

  await prisma.panel.create({
    data: { sectionId: section.id, judgeId: judge.id, isChair: true, status: "CHECKED_IN" },
  });

  const criteria = await prisma.rubricCriterion.findMany({ where: { rubricId: rubric.id } });

  for (const [i, speaker] of roomSpeakers.entries()) {
    const scores = criteria.map((c) => Math.round(c.maxPoints * (0.7 + 0.05 * ((i + 1) % 5))));
    const judgeTotal = scores.reduce((a, b) => a + b, 0);

    const ballot = await prisma.ballot.create({
      data: {
        sectionId: section.id,
        judgeId: judge.id,
        speakerId: speaker.id,
        submittedAt: new Date(),
        timePenalty: 0,
        judgeTotal,
        scores: {
          create: criteria.map((c, ci) => ({ criterionId: c.id, score: scores[ci]! })),
        },
      },
    });

    await prisma.roundResult.create({
      data: {
        roundId: round1.id,
        speakerId: speaker.id,
        roundScore: ballot.judgeTotal!,
        rank: i + 1, // seed data only — real rank comes from the rules engine (Section 3)
      },
    });
  }

  // Judge feedback (docs/02 §7) — a few speakers rate the room's judge.
  await Promise.all(
    roomSpeakers.slice(0, 3).map((speaker, i) =>
      prisma.judgeFeedback.create({
        data: {
          sectionId: section.id,
          ratedJudgeId: judge.id,
          raterSpeakerId: speaker.id,
          score: [9, 8, 10][i]!,
        },
      }),
    ),
  );

  console.log(`Seeded tournament "${tournament.name}" (${tournament.slug})`);
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
