import { test, expect } from "@playwright/test";
import { brand } from "../branding.config";

test("home page shows the brand tagline", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(brand.tagline)).toBeVisible();
});
