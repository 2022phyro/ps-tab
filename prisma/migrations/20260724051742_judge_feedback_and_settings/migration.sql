-- CreateEnum
CREATE TYPE "DrawMethod" AS ENUM ('RANDOM', 'POWER_MATCHED');

-- CreateEnum
CREATE TYPE "BallotMode" AS ENUM ('DEMOCRACY', 'STRICT');

-- AlterTable
ALTER TABLE "Division" ADD COLUMN     "allowTiesInPrelims" BOOLEAN NOT NULL DEFAULT true,
ADD COLUMN     "ballotMode" "BallotMode" NOT NULL DEFAULT 'DEMOCRACY',
ADD COLUMN     "drawMethod" "DrawMethod" NOT NULL DEFAULT 'RANDOM';

-- AlterTable
ALTER TABLE "Round" ADD COLUMN     "ballotModeOverride" "BallotMode",
ADD COLUMN     "drawMethodOverride" "DrawMethod";

-- AlterTable
ALTER TABLE "Rubric" ADD COLUMN     "baseScore" DOUBLE PRECISION NOT NULL DEFAULT 0;

-- CreateTable
CREATE TABLE "JudgeFeedback" (
    "id" TEXT NOT NULL,
    "sectionId" TEXT NOT NULL,
    "ratedJudgeId" TEXT NOT NULL,
    "raterSpeakerId" TEXT,
    "raterJudgeId" TEXT,
    "score" DOUBLE PRECISION NOT NULL,
    "comments" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "JudgeFeedback_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "JudgeFeedback_ratedJudgeId_idx" ON "JudgeFeedback"("ratedJudgeId");

-- AddForeignKey
ALTER TABLE "JudgeFeedback" ADD CONSTRAINT "JudgeFeedback_sectionId_fkey" FOREIGN KEY ("sectionId") REFERENCES "Section"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "JudgeFeedback" ADD CONSTRAINT "JudgeFeedback_ratedJudgeId_fkey" FOREIGN KEY ("ratedJudgeId") REFERENCES "Judge"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "JudgeFeedback" ADD CONSTRAINT "JudgeFeedback_raterSpeakerId_fkey" FOREIGN KEY ("raterSpeakerId") REFERENCES "Speaker"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "JudgeFeedback" ADD CONSTRAINT "JudgeFeedback_raterJudgeId_fkey" FOREIGN KEY ("raterJudgeId") REFERENCES "Judge"("id") ON DELETE CASCADE ON UPDATE CASCADE;

