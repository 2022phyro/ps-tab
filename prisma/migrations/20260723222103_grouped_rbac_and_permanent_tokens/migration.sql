-- DropForeignKey
ALTER TABLE "CircuitAdmin" DROP CONSTRAINT "CircuitAdmin_circuitId_fkey";

-- DropForeignKey
ALTER TABLE "CircuitAdmin" DROP CONSTRAINT "CircuitAdmin_userId_fkey";

-- DropForeignKey
ALTER TABLE "InstitutionCoordinator" DROP CONSTRAINT "InstitutionCoordinator_institutionId_fkey";

-- DropForeignKey
ALTER TABLE "InstitutionCoordinator" DROP CONSTRAINT "InstitutionCoordinator_tournamentId_fkey";

-- DropForeignKey
ALTER TABLE "InstitutionCoordinator" DROP CONSTRAINT "InstitutionCoordinator_userId_fkey";

-- DropForeignKey
ALTER TABLE "TournamentCollaborator" DROP CONSTRAINT "TournamentCollaborator_tournamentId_fkey";

-- DropForeignKey
ALTER TABLE "TournamentCollaborator" DROP CONSTRAINT "TournamentCollaborator_userId_fkey";

-- AlterTable
ALTER TABLE "AccessToken" ALTER COLUMN "expiresAt" DROP NOT NULL;

-- AlterTable
ALTER TABLE "User" DROP COLUMN "isSuperAdmin";

-- DropTable
DROP TABLE "CircuitAdmin";

-- DropTable
DROP TABLE "InstitutionCoordinator";

-- DropTable
DROP TABLE "TournamentCollaborator";

-- CreateTable
CREATE TABLE "Permission" (
    "id" TEXT NOT NULL,
    "key" TEXT NOT NULL,
    "description" TEXT NOT NULL,

    CONSTRAINT "Permission_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Group" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "isDefault" BOOLEAN NOT NULL DEFAULT false,
    "tournamentId" TEXT,
    "circuitId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Group_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "GroupPermission" (
    "id" TEXT NOT NULL,
    "groupId" TEXT NOT NULL,
    "permissionId" TEXT NOT NULL,

    CONSTRAINT "GroupPermission_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "GroupMembership" (
    "id" TEXT NOT NULL,
    "groupId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "institutionId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "GroupMembership_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "Permission_key_key" ON "Permission"("key");

-- CreateIndex
CREATE UNIQUE INDEX "Group_tournamentId_name_key" ON "Group"("tournamentId", "name");

-- CreateIndex
CREATE UNIQUE INDEX "Group_circuitId_name_key" ON "Group"("circuitId", "name");

-- CreateIndex
CREATE UNIQUE INDEX "GroupPermission_groupId_permissionId_key" ON "GroupPermission"("groupId", "permissionId");

-- CreateIndex
CREATE UNIQUE INDEX "GroupMembership_groupId_userId_institutionId_key" ON "GroupMembership"("groupId", "userId", "institutionId");

-- AddForeignKey
ALTER TABLE "Group" ADD CONSTRAINT "Group_tournamentId_fkey" FOREIGN KEY ("tournamentId") REFERENCES "Tournament"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Group" ADD CONSTRAINT "Group_circuitId_fkey" FOREIGN KEY ("circuitId") REFERENCES "Circuit"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "GroupPermission" ADD CONSTRAINT "GroupPermission_groupId_fkey" FOREIGN KEY ("groupId") REFERENCES "Group"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "GroupPermission" ADD CONSTRAINT "GroupPermission_permissionId_fkey" FOREIGN KEY ("permissionId") REFERENCES "Permission"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "GroupMembership" ADD CONSTRAINT "GroupMembership_groupId_fkey" FOREIGN KEY ("groupId") REFERENCES "Group"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "GroupMembership" ADD CONSTRAINT "GroupMembership_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "GroupMembership" ADD CONSTRAINT "GroupMembership_institutionId_fkey" FOREIGN KEY ("institutionId") REFERENCES "Institution"("id") ON DELETE CASCADE ON UPDATE CASCADE;

