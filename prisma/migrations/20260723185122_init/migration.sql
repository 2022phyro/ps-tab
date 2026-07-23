-- Enable trigram matching for the institution-name search-existing-first
-- combobox (docs/01-tournament-mechanics.md §2) — added by hand, Prisma's
-- schema doesn't declare this extension.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- CreateEnum
CREATE TYPE "TournamentState" AS ENUM ('DRAFT', 'ACTIVE', 'CONCLUDED', 'ARCHIVED');

-- CreateEnum
CREATE TYPE "BreakType" AS ENUM ('FIXED_COUNT', 'PERCENTAGE', 'RANK_FLOOR');

-- CreateEnum
CREATE TYPE "RoundKind" AS ENUM ('PRELIM', 'ELIMINATION');

-- CreateEnum
CREATE TYPE "DrawsState" AS ENUM ('HIDDEN', 'RELEASED');

-- CreateEnum
CREATE TYPE "ResultsState" AS ENUM ('HELD', 'RELEASED');

-- CreateEnum
CREATE TYPE "StandingsState" AS ENUM ('HELD', 'RELEASED');

-- CreateEnum
CREATE TYPE "JudgeCheckInStatus" AS ENUM ('CHECKED_IN', 'NO_SHOW', 'UNRESPONSIVE');

-- CreateEnum
CREATE TYPE "PanelStatus" AS ENUM ('ASSIGNED', 'CHECKED_IN', 'NO_SHOW', 'REMOVED_FOR_CONFLICT', 'DEPLOYED_RESERVE');

-- CreateEnum
CREATE TYPE "ClaimMethod" AS ENUM ('EMAIL_MATCH', 'CLAIM_CODE');

-- CreateEnum
CREATE TYPE "ClaimStatus" AS ENUM ('CONFIRMED', 'CONTESTED', 'REVOKED');

-- CreateTable
CREATE TABLE "User" (
    "id" TEXT NOT NULL,
    "name" TEXT,
    "email" TEXT,
    "emailVerified" TIMESTAMP(3),
    "image" TEXT,
    "isSuperAdmin" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "User_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Account" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "provider" TEXT NOT NULL,
    "providerAccountId" TEXT NOT NULL,
    "refresh_token" TEXT,
    "access_token" TEXT,
    "expires_at" INTEGER,
    "token_type" TEXT,
    "scope" TEXT,
    "id_token" TEXT,
    "session_state" TEXT,

    CONSTRAINT "Account_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Session" (
    "id" TEXT NOT NULL,
    "sessionToken" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "expires" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Session_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "VerificationToken" (
    "identifier" TEXT NOT NULL,
    "token" TEXT NOT NULL,
    "expires" TIMESTAMP(3) NOT NULL
);

-- CreateTable
CREATE TABLE "Tournament" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "state" "TournamentState" NOT NULL DEFAULT 'DRAFT',
    "feedbackWindowOpensAt" TIMESTAMP(3),
    "feedbackWindowClosesAt" TIMESTAMP(3),
    "ownerId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Tournament_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "TournamentCollaborator" (
    "id" TEXT NOT NULL,
    "tournamentId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "TournamentCollaborator_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Division" (
    "id" TEXT NOT NULL,
    "tournamentId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "roomSizeMin" INTEGER NOT NULL DEFAULT 4,
    "roomSizeMax" INTEGER NOT NULL DEFAULT 8,
    "breakType" "BreakType" NOT NULL DEFAULT 'FIXED_COUNT',
    "breakCount" INTEGER,
    "breakPercentage" DOUBLE PRECISION,
    "dropWorstCount" INTEGER NOT NULL DEFAULT 1,
    "includeTiesAtBreak" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Division_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Round" (
    "id" TEXT NOT NULL,
    "divisionId" TEXT NOT NULL,
    "roundNumber" INTEGER NOT NULL,
    "kind" "RoundKind" NOT NULL DEFAULT 'PRELIM',
    "stageName" TEXT,
    "advancesFromRoundId" TEXT,
    "rubricId" TEXT,
    "checkInOpensAt" TIMESTAMP(3),
    "checkInClosesAt" TIMESTAMP(3),
    "scheduledStartAt" TIMESTAMP(3),
    "drawsState" "DrawsState" NOT NULL DEFAULT 'HIDDEN',
    "resultsState" "ResultsState" NOT NULL DEFAULT 'HELD',
    "standingsState" "StandingsState" NOT NULL DEFAULT 'HELD',
    "lockedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Round_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Institution" (
    "id" TEXT NOT NULL,
    "tournamentId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Institution_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Speaker" (
    "id" TEXT NOT NULL,
    "tournamentId" TEXT NOT NULL,
    "divisionId" TEXT NOT NULL,
    "institutionId" TEXT,
    "name" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "isMinor" BOOLEAN NOT NULL DEFAULT false,
    "guardianEmail" TEXT,
    "userId" TEXT,
    "waitlisted" BOOLEAN NOT NULL DEFAULT false,
    "waitlistOrder" INTEGER,
    "scratchedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Speaker_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Judge" (
    "id" TEXT NOT NULL,
    "tournamentId" TEXT NOT NULL,
    "institutionId" TEXT,
    "name" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "isMinor" BOOLEAN NOT NULL DEFAULT false,
    "userId" TEXT,
    "chairEligible" BOOLEAN NOT NULL DEFAULT false,
    "isReserve" BOOLEAN NOT NULL DEFAULT false,
    "maxRoundsPerDay" INTEGER,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Judge_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "SpeakerCheckIn" (
    "id" TEXT NOT NULL,
    "roundId" TEXT NOT NULL,
    "speakerId" TEXT NOT NULL,
    "checkedInAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "SpeakerCheckIn_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "JudgeCheckIn" (
    "id" TEXT NOT NULL,
    "roundId" TEXT NOT NULL,
    "judgeId" TEXT NOT NULL,
    "status" "JudgeCheckInStatus" NOT NULL DEFAULT 'CHECKED_IN',
    "checkedInAt" TIMESTAMP(3),
    "flaggedAt" TIMESTAMP(3),

    CONSTRAINT "JudgeCheckIn_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Section" (
    "id" TEXT NOT NULL,
    "roundId" TEXT NOT NULL,
    "roomLabel" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Section_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "SectionAssignment" (
    "id" TEXT NOT NULL,
    "sectionId" TEXT NOT NULL,
    "speakerId" TEXT NOT NULL,
    "position" INTEGER NOT NULL,
    "clashFlag" BOOLEAN NOT NULL DEFAULT false,

    CONSTRAINT "SectionAssignment_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Panel" (
    "id" TEXT NOT NULL,
    "sectionId" TEXT NOT NULL,
    "judgeId" TEXT NOT NULL,
    "isChair" BOOLEAN NOT NULL DEFAULT false,
    "status" "PanelStatus" NOT NULL DEFAULT 'ASSIGNED',
    "swappedFromJudgeId" TEXT,
    "swappedAt" TIMESTAMP(3),

    CONSTRAINT "Panel_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Rubric" (
    "id" TEXT NOT NULL,
    "tournamentId" TEXT NOT NULL,
    "divisionId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Rubric_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "RubricCriterion" (
    "id" TEXT NOT NULL,
    "rubricId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "maxPoints" DOUBLE PRECISION NOT NULL,
    "order" INTEGER NOT NULL,

    CONSTRAINT "RubricCriterion_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "TimePenaltyPolicy" (
    "id" TEXT NOT NULL,
    "rubricId" TEXT NOT NULL,
    "allowedSeconds" INTEGER NOT NULL,
    "graceSeconds" INTEGER NOT NULL DEFAULT 10,
    "penaltyPerInterval" DOUBLE PRECISION NOT NULL,
    "intervalSeconds" INTEGER NOT NULL DEFAULT 5,
    "maxPenalty" DOUBLE PRECISION,

    CONSTRAINT "TimePenaltyPolicy_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Ballot" (
    "id" TEXT NOT NULL,
    "sectionId" TEXT NOT NULL,
    "judgeId" TEXT NOT NULL,
    "speakerId" TEXT NOT NULL,
    "isPartial" BOOLEAN NOT NULL DEFAULT false,
    "submittedAt" TIMESTAMP(3),
    "timePenalty" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "judgeTotal" DOUBLE PRECISION,
    "comments" TEXT,
    "calibrationFlag" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Ballot_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "BallotScore" (
    "id" TEXT NOT NULL,
    "ballotId" TEXT NOT NULL,
    "criterionId" TEXT NOT NULL,
    "score" DOUBLE PRECISION NOT NULL,

    CONSTRAINT "BallotScore_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "RoundResult" (
    "id" TEXT NOT NULL,
    "roundId" TEXT NOT NULL,
    "speakerId" TEXT NOT NULL,
    "roundScore" DOUBLE PRECISION NOT NULL,
    "rank" INTEGER NOT NULL,

    CONSTRAINT "RoundResult_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Embargo" (
    "id" TEXT NOT NULL,
    "roundId" TEXT NOT NULL,
    "speakerId" TEXT NOT NULL,
    "reason" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "liftedAt" TIMESTAMP(3),

    CONSTRAINT "Embargo_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AuditLogEntry" (
    "id" TEXT NOT NULL,
    "tournamentId" TEXT,
    "actorUserId" TEXT NOT NULL,
    "actionType" TEXT NOT NULL,
    "summary" TEXT NOT NULL,
    "reason" TEXT,
    "beforeData" JSONB,
    "afterData" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "AuditLogEntry_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AccessToken" (
    "id" TEXT NOT NULL,
    "hashedValue" TEXT NOT NULL,
    "speakerId" TEXT,
    "judgeId" TEXT,
    "scope" TEXT NOT NULL,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "revokedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "AccessToken_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Claim" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "speakerId" TEXT,
    "judgeId" TEXT,
    "method" "ClaimMethod" NOT NULL,
    "status" "ClaimStatus" NOT NULL DEFAULT 'CONFIRMED',
    "claimedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "revokedAt" TIMESTAMP(3),

    CONSTRAINT "Claim_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ClaimDispute" (
    "id" TEXT NOT NULL,
    "claimId" TEXT NOT NULL,
    "competingUserId" TEXT NOT NULL,
    "raisedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "resolvedAt" TIMESTAMP(3),
    "resolvedByUserId" TEXT,
    "resolutionNote" TEXT,

    CONSTRAINT "ClaimDispute_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "GuardianLink" (
    "id" TEXT NOT NULL,
    "speakerId" TEXT NOT NULL,
    "guardianUserId" TEXT NOT NULL,
    "confirmedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "GuardianLink_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Circuit" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "ownerId" TEXT NOT NULL,
    "breakCount" INTEGER,
    "breakPercentage" DOUBLE PRECISION,
    "dropWorstCount" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Circuit_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CircuitAdmin" (
    "id" TEXT NOT NULL,
    "circuitId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,

    CONSTRAINT "CircuitAdmin_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CircuitMembership" (
    "id" TEXT NOT NULL,
    "circuitId" TEXT NOT NULL,
    "tournamentId" TEXT NOT NULL,

    CONSTRAINT "CircuitMembership_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CircuitPointsRule" (
    "id" TEXT NOT NULL,
    "circuitId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "conversionTable" JSONB NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "CircuitPointsRule_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CrossTournamentRating" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "rating" DOUBLE PRECISION NOT NULL DEFAULT 1500,
    "optedIn" BOOLEAN NOT NULL DEFAULT false,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "CrossTournamentRating_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "InstitutionCoordinator" (
    "id" TEXT NOT NULL,
    "tournamentId" TEXT NOT NULL,
    "institutionId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "InstitutionCoordinator_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "User_email_key" ON "User"("email");

-- CreateIndex
CREATE UNIQUE INDEX "Account_provider_providerAccountId_key" ON "Account"("provider", "providerAccountId");

-- CreateIndex
CREATE UNIQUE INDEX "Session_sessionToken_key" ON "Session"("sessionToken");

-- CreateIndex
CREATE UNIQUE INDEX "VerificationToken_token_key" ON "VerificationToken"("token");

-- CreateIndex
CREATE UNIQUE INDEX "VerificationToken_identifier_token_key" ON "VerificationToken"("identifier", "token");

-- CreateIndex
CREATE UNIQUE INDEX "Tournament_slug_key" ON "Tournament"("slug");

-- CreateIndex
CREATE UNIQUE INDEX "TournamentCollaborator_tournamentId_userId_key" ON "TournamentCollaborator"("tournamentId", "userId");

-- CreateIndex
CREATE UNIQUE INDEX "Division_tournamentId_name_key" ON "Division"("tournamentId", "name");

-- CreateIndex
CREATE UNIQUE INDEX "Round_divisionId_roundNumber_key" ON "Round"("divisionId", "roundNumber");

-- CreateIndex
CREATE UNIQUE INDEX "Institution_tournamentId_name_key" ON "Institution"("tournamentId", "name");

-- CreateIndex (hand-added, see pg_trgm extension above)
-- Backs the fuzzy "does this institution already exist" lookup, both for the
-- registration combobox and for flagging near-duplicate CSV-imported names.
CREATE INDEX "Institution_name_trgm_idx" ON "Institution" USING GIN ("name" gin_trgm_ops);

-- CreateIndex
CREATE INDEX "Speaker_tournamentId_email_idx" ON "Speaker"("tournamentId", "email");

-- CreateIndex
CREATE INDEX "Judge_tournamentId_email_idx" ON "Judge"("tournamentId", "email");

-- CreateIndex
CREATE UNIQUE INDEX "SpeakerCheckIn_roundId_speakerId_key" ON "SpeakerCheckIn"("roundId", "speakerId");

-- CreateIndex
CREATE UNIQUE INDEX "JudgeCheckIn_roundId_judgeId_key" ON "JudgeCheckIn"("roundId", "judgeId");

-- CreateIndex
CREATE UNIQUE INDEX "Section_roundId_roomLabel_key" ON "Section"("roundId", "roomLabel");

-- CreateIndex
CREATE UNIQUE INDEX "SectionAssignment_sectionId_speakerId_key" ON "SectionAssignment"("sectionId", "speakerId");

-- CreateIndex
CREATE UNIQUE INDEX "SectionAssignment_sectionId_position_key" ON "SectionAssignment"("sectionId", "position");

-- CreateIndex
CREATE UNIQUE INDEX "Panel_sectionId_judgeId_key" ON "Panel"("sectionId", "judgeId");

-- CreateIndex
CREATE UNIQUE INDEX "Rubric_divisionId_name_key" ON "Rubric"("divisionId", "name");

-- CreateIndex
CREATE UNIQUE INDEX "RubricCriterion_rubricId_order_key" ON "RubricCriterion"("rubricId", "order");

-- CreateIndex
CREATE UNIQUE INDEX "TimePenaltyPolicy_rubricId_key" ON "TimePenaltyPolicy"("rubricId");

-- CreateIndex
CREATE UNIQUE INDEX "Ballot_sectionId_judgeId_speakerId_key" ON "Ballot"("sectionId", "judgeId", "speakerId");

-- CreateIndex
CREATE UNIQUE INDEX "BallotScore_ballotId_criterionId_key" ON "BallotScore"("ballotId", "criterionId");

-- CreateIndex
CREATE UNIQUE INDEX "RoundResult_roundId_speakerId_key" ON "RoundResult"("roundId", "speakerId");

-- CreateIndex
CREATE UNIQUE INDEX "Embargo_roundId_speakerId_key" ON "Embargo"("roundId", "speakerId");

-- CreateIndex
CREATE INDEX "AuditLogEntry_tournamentId_actionType_idx" ON "AuditLogEntry"("tournamentId", "actionType");

-- CreateIndex
CREATE UNIQUE INDEX "AccessToken_hashedValue_key" ON "AccessToken"("hashedValue");

-- CreateIndex
CREATE UNIQUE INDEX "GuardianLink_speakerId_guardianUserId_key" ON "GuardianLink"("speakerId", "guardianUserId");

-- CreateIndex
CREATE UNIQUE INDEX "CircuitAdmin_circuitId_userId_key" ON "CircuitAdmin"("circuitId", "userId");

-- CreateIndex
CREATE UNIQUE INDEX "CircuitMembership_circuitId_tournamentId_key" ON "CircuitMembership"("circuitId", "tournamentId");

-- CreateIndex
CREATE UNIQUE INDEX "CrossTournamentRating_userId_key" ON "CrossTournamentRating"("userId");

-- CreateIndex
CREATE UNIQUE INDEX "InstitutionCoordinator_tournamentId_institutionId_userId_key" ON "InstitutionCoordinator"("tournamentId", "institutionId", "userId");

-- AddForeignKey
ALTER TABLE "Account" ADD CONSTRAINT "Account_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Session" ADD CONSTRAINT "Session_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Tournament" ADD CONSTRAINT "Tournament_ownerId_fkey" FOREIGN KEY ("ownerId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TournamentCollaborator" ADD CONSTRAINT "TournamentCollaborator_tournamentId_fkey" FOREIGN KEY ("tournamentId") REFERENCES "Tournament"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TournamentCollaborator" ADD CONSTRAINT "TournamentCollaborator_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Division" ADD CONSTRAINT "Division_tournamentId_fkey" FOREIGN KEY ("tournamentId") REFERENCES "Tournament"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Round" ADD CONSTRAINT "Round_advancesFromRoundId_fkey" FOREIGN KEY ("advancesFromRoundId") REFERENCES "Round"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Round" ADD CONSTRAINT "Round_rubricId_fkey" FOREIGN KEY ("rubricId") REFERENCES "Rubric"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Round" ADD CONSTRAINT "Round_divisionId_fkey" FOREIGN KEY ("divisionId") REFERENCES "Division"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Institution" ADD CONSTRAINT "Institution_tournamentId_fkey" FOREIGN KEY ("tournamentId") REFERENCES "Tournament"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Speaker" ADD CONSTRAINT "Speaker_divisionId_fkey" FOREIGN KEY ("divisionId") REFERENCES "Division"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Speaker" ADD CONSTRAINT "Speaker_institutionId_fkey" FOREIGN KEY ("institutionId") REFERENCES "Institution"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Judge" ADD CONSTRAINT "Judge_institutionId_fkey" FOREIGN KEY ("institutionId") REFERENCES "Institution"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SpeakerCheckIn" ADD CONSTRAINT "SpeakerCheckIn_roundId_fkey" FOREIGN KEY ("roundId") REFERENCES "Round"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SpeakerCheckIn" ADD CONSTRAINT "SpeakerCheckIn_speakerId_fkey" FOREIGN KEY ("speakerId") REFERENCES "Speaker"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "JudgeCheckIn" ADD CONSTRAINT "JudgeCheckIn_roundId_fkey" FOREIGN KEY ("roundId") REFERENCES "Round"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "JudgeCheckIn" ADD CONSTRAINT "JudgeCheckIn_judgeId_fkey" FOREIGN KEY ("judgeId") REFERENCES "Judge"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Section" ADD CONSTRAINT "Section_roundId_fkey" FOREIGN KEY ("roundId") REFERENCES "Round"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SectionAssignment" ADD CONSTRAINT "SectionAssignment_sectionId_fkey" FOREIGN KEY ("sectionId") REFERENCES "Section"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SectionAssignment" ADD CONSTRAINT "SectionAssignment_speakerId_fkey" FOREIGN KEY ("speakerId") REFERENCES "Speaker"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Panel" ADD CONSTRAINT "Panel_sectionId_fkey" FOREIGN KEY ("sectionId") REFERENCES "Section"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Panel" ADD CONSTRAINT "Panel_judgeId_fkey" FOREIGN KEY ("judgeId") REFERENCES "Judge"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Rubric" ADD CONSTRAINT "Rubric_divisionId_fkey" FOREIGN KEY ("divisionId") REFERENCES "Division"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "RubricCriterion" ADD CONSTRAINT "RubricCriterion_rubricId_fkey" FOREIGN KEY ("rubricId") REFERENCES "Rubric"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TimePenaltyPolicy" ADD CONSTRAINT "TimePenaltyPolicy_rubricId_fkey" FOREIGN KEY ("rubricId") REFERENCES "Rubric"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Ballot" ADD CONSTRAINT "Ballot_sectionId_fkey" FOREIGN KEY ("sectionId") REFERENCES "Section"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Ballot" ADD CONSTRAINT "Ballot_judgeId_fkey" FOREIGN KEY ("judgeId") REFERENCES "Judge"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Ballot" ADD CONSTRAINT "Ballot_speakerId_fkey" FOREIGN KEY ("speakerId") REFERENCES "Speaker"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "BallotScore" ADD CONSTRAINT "BallotScore_ballotId_fkey" FOREIGN KEY ("ballotId") REFERENCES "Ballot"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "BallotScore" ADD CONSTRAINT "BallotScore_criterionId_fkey" FOREIGN KEY ("criterionId") REFERENCES "RubricCriterion"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "RoundResult" ADD CONSTRAINT "RoundResult_roundId_fkey" FOREIGN KEY ("roundId") REFERENCES "Round"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "RoundResult" ADD CONSTRAINT "RoundResult_speakerId_fkey" FOREIGN KEY ("speakerId") REFERENCES "Speaker"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Embargo" ADD CONSTRAINT "Embargo_roundId_fkey" FOREIGN KEY ("roundId") REFERENCES "Round"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Embargo" ADD CONSTRAINT "Embargo_speakerId_fkey" FOREIGN KEY ("speakerId") REFERENCES "Speaker"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AuditLogEntry" ADD CONSTRAINT "AuditLogEntry_tournamentId_fkey" FOREIGN KEY ("tournamentId") REFERENCES "Tournament"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AuditLogEntry" ADD CONSTRAINT "AuditLogEntry_actorUserId_fkey" FOREIGN KEY ("actorUserId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AccessToken" ADD CONSTRAINT "AccessToken_speakerId_fkey" FOREIGN KEY ("speakerId") REFERENCES "Speaker"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AccessToken" ADD CONSTRAINT "AccessToken_judgeId_fkey" FOREIGN KEY ("judgeId") REFERENCES "Judge"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Claim" ADD CONSTRAINT "Claim_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Claim" ADD CONSTRAINT "Claim_speakerId_fkey" FOREIGN KEY ("speakerId") REFERENCES "Speaker"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Claim" ADD CONSTRAINT "Claim_judgeId_fkey" FOREIGN KEY ("judgeId") REFERENCES "Judge"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ClaimDispute" ADD CONSTRAINT "ClaimDispute_claimId_fkey" FOREIGN KEY ("claimId") REFERENCES "Claim"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ClaimDispute" ADD CONSTRAINT "ClaimDispute_competingUserId_fkey" FOREIGN KEY ("competingUserId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ClaimDispute" ADD CONSTRAINT "ClaimDispute_resolvedByUserId_fkey" FOREIGN KEY ("resolvedByUserId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "GuardianLink" ADD CONSTRAINT "GuardianLink_speakerId_fkey" FOREIGN KEY ("speakerId") REFERENCES "Speaker"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "GuardianLink" ADD CONSTRAINT "GuardianLink_guardianUserId_fkey" FOREIGN KEY ("guardianUserId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Circuit" ADD CONSTRAINT "Circuit_ownerId_fkey" FOREIGN KEY ("ownerId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CircuitAdmin" ADD CONSTRAINT "CircuitAdmin_circuitId_fkey" FOREIGN KEY ("circuitId") REFERENCES "Circuit"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CircuitAdmin" ADD CONSTRAINT "CircuitAdmin_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CircuitMembership" ADD CONSTRAINT "CircuitMembership_circuitId_fkey" FOREIGN KEY ("circuitId") REFERENCES "Circuit"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CircuitMembership" ADD CONSTRAINT "CircuitMembership_tournamentId_fkey" FOREIGN KEY ("tournamentId") REFERENCES "Tournament"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CircuitPointsRule" ADD CONSTRAINT "CircuitPointsRule_circuitId_fkey" FOREIGN KEY ("circuitId") REFERENCES "Circuit"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CrossTournamentRating" ADD CONSTRAINT "CrossTournamentRating_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "InstitutionCoordinator" ADD CONSTRAINT "InstitutionCoordinator_tournamentId_fkey" FOREIGN KEY ("tournamentId") REFERENCES "Tournament"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "InstitutionCoordinator" ADD CONSTRAINT "InstitutionCoordinator_institutionId_fkey" FOREIGN KEY ("institutionId") REFERENCES "Institution"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "InstitutionCoordinator" ADD CONSTRAINT "InstitutionCoordinator_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;
