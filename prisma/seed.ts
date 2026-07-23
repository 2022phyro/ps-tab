import "dotenv/config";
import { PrismaClient } from "../src/generated/prisma/client";
import { PrismaPg } from "@prisma/adapter-pg";

const adapter = new PrismaPg({ connectionString: process.env.DATABASE_URL! });
const prisma = new PrismaClient({ adapter });

async function main() {
  const owner = await prisma.user.upsert({
    where: { email: "director@example.com" },
    update: {},
    create: {
      name: "Sample Tournament Director",
      email: "director@example.com",
    },
  });

  const tournament = await prisma.tournament.create({
    data: {
      name: "Riverside Invitational",
      slug: "riverside-invitational",
      state: "ACTIVE",
      ownerId: owner.id,
    },
  });

  const institutionNames = ["Lincoln High School", "Brookfield Academy", "Riverside Prep"];
  const institutions = await Promise.all(
    institutionNames.map((name) =>
      prisma.institution.create({
        data: { tournamentId: tournament.id, name },
      }),
    ),
  );

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
