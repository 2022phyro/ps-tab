import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import Home from "./page";
import { brand } from "../../branding.config";

describe("Home", () => {
  it("renders the brand tagline", () => {
    render(<Home />);
    expect(screen.getByText(brand.tagline)).toBeInTheDocument();
  });
});
