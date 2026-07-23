import { describe, expect, it } from "vitest";
import { generateTokenQrDataUri } from "./qrcode";

describe("generateTokenQrDataUri", () => {
  it("renders the token URL as a PNG data URI", async () => {
    const dataUri = await generateTokenQrDataUri("https://example.com/t/abc123");
    expect(dataUri).toMatch(/^data:image\/png;base64,/);
  });
});
