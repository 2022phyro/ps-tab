-- AlterTable
ALTER TABLE "Judge" ADD COLUMN     "claimCode" TEXT;

-- AlterTable
ALTER TABLE "Speaker" ADD COLUMN     "claimCode" TEXT;

-- CreateIndex
CREATE UNIQUE INDEX "Judge_claimCode_key" ON "Judge"("claimCode");

-- CreateIndex
CREATE UNIQUE INDEX "Speaker_claimCode_key" ON "Speaker"("claimCode");

