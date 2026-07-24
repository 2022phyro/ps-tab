-- CreateEnum
CREATE TYPE "LockTrigger" AS ENUM ('ON_RESULTS_RELEASE', 'ON_ALL_BALLOTS_SUBMITTED');

-- CreateEnum
CREATE TYPE "PublishGate" AS ENUM ('DRAWS', 'RESULTS', 'STANDINGS');

-- AlterEnum
ALTER TYPE "JudgeCheckInStatus" ADD VALUE 'RECUSED';

-- AlterEnum
ALTER TYPE "PanelStatus" ADD VALUE 'LEFT_MID_ROUND';

-- AlterTable
ALTER TABLE "Division" ADD COLUMN     "lockTrigger" "LockTrigger" NOT NULL DEFAULT 'ON_RESULTS_RELEASE',
ADD COLUMN     "minimumPanelSize" INTEGER NOT NULL DEFAULT 1,
ADD COLUMN     "panelSize" INTEGER NOT NULL DEFAULT 3;

-- AlterTable
ALTER TABLE "Round" ADD COLUMN     "scheduledEndAt" TIMESTAMP(3);

-- CreateTable
CREATE TABLE "ScheduledRelease" (
    "id" TEXT NOT NULL,
    "roundId" TEXT NOT NULL,
    "gate" "PublishGate" NOT NULL,
    "releaseAt" TIMESTAMP(3) NOT NULL,
    "cancelledAt" TIMESTAMP(3),
    "executedAt" TIMESTAMP(3),
    "createdByUserId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ScheduledRelease_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "ScheduledRelease_roundId_gate_idx" ON "ScheduledRelease"("roundId", "gate");

-- AddForeignKey
ALTER TABLE "ScheduledRelease" ADD CONSTRAINT "ScheduledRelease_roundId_fkey" FOREIGN KEY ("roundId") REFERENCES "Round"("id") ON DELETE CASCADE ON UPDATE CASCADE;

