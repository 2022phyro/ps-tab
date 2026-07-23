// docs/08-cross-tournament-ecosystem.md §5 — guardian consent for minors.
// Tournament-day token access is never gated by this; only creating a
// persistent account and opting into cross-tournament rating are.

import { prisma } from "@/lib/prisma";

export async function hasConfirmedGuardianConsent(speakerId: string): Promise<boolean> {
  const speaker = await prisma.speaker.findUniqueOrThrow({ where: { id: speakerId } });
  if (!speaker.isMinor) return true; // the gate only applies to minors at all

  const confirmedLink = await prisma.guardianLink.findFirst({
    where: { speakerId, confirmedAt: { not: null } },
  });
  return confirmedLink !== null;
}

/** Throws with a clear message rather than returning false — call sites
 *  (account creation, rating opt-in) should treat this as a hard stop. */
export async function assertGuardianConsent(speakerId: string): Promise<void> {
  if (!(await hasConfirmedGuardianConsent(speakerId))) {
    throw new Error("This roster entry is a minor and requires confirmed guardian consent first");
  }
}

/** Starts the link — explicit and confirmable, never automatic (docs/08 §5). */
export async function requestGuardianLink(speakerId: string, guardianUserId: string) {
  const speaker = await prisma.speaker.findUniqueOrThrow({ where: { id: speakerId } });
  if (!speaker.isMinor) {
    throw new Error("Guardian links are only meaningful for minor roster entries");
  }
  return prisma.guardianLink.create({ data: { speakerId, guardianUserId } });
}

export async function confirmGuardianLink(guardianLinkId: string) {
  return prisma.guardianLink.update({
    where: { id: guardianLinkId },
    data: { confirmedAt: new Date() },
  });
}
