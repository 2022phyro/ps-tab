// docs/04-identity-and-auth.md §1 — the same token link, rendered as a QR
// code for printing (name tags, etc). Purely a delivery-format concern; the
// URL itself already carries the token.

import QRCode from "qrcode";

export async function generateTokenQrDataUri(url: string): Promise<string> {
  return QRCode.toDataURL(url);
}
