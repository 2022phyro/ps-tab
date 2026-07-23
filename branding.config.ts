/**
 * PS Tab — brand tokens
 * ---------------------
 * Single source of truth for the visual identity. Nothing here is wired into
 * the app until Section 1 (Tailwind/shadcn init) maps these onto the Tailwind
 * theme and `next/font` — until then, this file is just the record of the
 * decisions so they don't have to be re-derived or re-argued later.
 *
 * To rebrand: edit values here, then re-run the Section 1 theme-mapping step.
 * Nothing downstream should hardcode a hex/font value directly — always
 * reference this file (or the Tailwind theme it generates).
 *
 * Direction: modern + a little playful (a public-speaking tournament should
 * not feel like enterprise accounting software) but still reads as a serious,
 * trustworthy system of record — the tone that wins here is "confident",
 * not "cute". Color carries the playfulness; typography and layout carry
 * the seriousness.
 */

export const brand = {
  name: "PS Tab",
  fullName: "PS Tab — Public Speaking Tabulation",
  tagline: "Tabulation for individual speech, done right.",

  colors: {
    // Core brand color — confident, a little unexpected for a "tab tool"
    // (most of this category is navy/gray corporate; violet reads modern
    // without sacrificing seriousness).
    primary: {
      50: "#F2F1FD",
      100: "#E4E2FB",
      200: "#C9C5F7",
      300: "#A9A2F1",
      400: "#8B81EA",
      500: "#6D5FE3", // primary brand color — buttons, links, active states
      600: "#5B4FE9", // hover/pressed
      700: "#4A3FC7",
      800: "#3A319C",
      900: "#2B2574",
    },

    // Playful counterpoint — used sparingly for highlights, badges,
    // "you qualified" moments, CTA accents. Never for body text or large
    // surfaces — it's a spark, not a base color.
    accent: {
      400: "#FF8A65",
      500: "#FF6B4A", // accent — break-line badges, celebratory states
      600: "#F0512E",
    },

    // Semantic — always paired with an icon/label too, never color-only
    // (see docs/06-ux-and-views.md §6 accessibility requirement).
    semantic: {
      success: "#1FA97A", // e.g. "checked in", "ballot submitted"
      warning: "#E8A317", // e.g. "unresponsive judge", "embargoed result"
      danger: "#E5484D", // e.g. "no-show", "round locked / blocked"
      info: "#3B82F6", // e.g. "scheduled auto-publish pending"
    },

    // Neutrals — use Tailwind's built-in `slate` scale directly rather than
    // redefining one; recorded here just so the choice of *which* gray scale
    // is deliberate and documented.
    neutralScale: "slate",

    // Surface tokens — the two modes the UI must support (docs/06 targets
    // both organizer desktop use and judge/competitor mobile use in bright
    // or dim venues).
    surface: {
      light: { bg: "#FFFFFF", subtle: "#F8F8FC", border: "#E5E4F1" },
      dark: { bg: "#121016", subtle: "#1A1822", border: "#2B2836" },
    },
  },

  fonts: {
    // Headings & large numerals (leaderboard ranks, scores) — a geometric
    // sans with a bit of character, especially in its numerals.
    heading: {
      family: "Space Grotesk",
      googleFont: "Space_Grotesk",
      fallback: ["system-ui", "sans-serif"],
    },
    // Body & dense UI text — optimized for legibility at small sizes on
    // mobile (the judge scorecard is the highest-frequency surface).
    body: {
      family: "Inter",
      googleFont: "Inter",
      fallback: ["system-ui", "sans-serif"],
    },
    // Tokens, claim codes, IDs — anything that benefits from unambiguous
    // character shapes (0 vs O, 1 vs l).
    mono: {
      family: "JetBrains Mono",
      googleFont: "JetBrains_Mono",
      fallback: ["ui-monospace", "monospace"],
    },
  },

  shape: {
    // Rounded enough to feel approachable, not so rounded it looks like a
    // kids' app. Cards/inputs use `md`; pills/badges/avatars use `full`.
    radius: {
      sm: "0.375rem", // 6px
      md: "0.625rem", // 10px — default for cards, inputs, buttons
      lg: "1rem", // 16px — modals, larger panels
      full: "9999px", // pills, badges, avatars
    },
  },

  voice: [
    "Direct, plain language over jargon — a competitor reading their own feedback should never feel talked over.",
    "Never cute at the expense of clarity — a locked round, a no-show alert, an embargoed result: state plainly what happened, playfulness lives in color/shape, not copy.",
    "Numbers are the hero — ranks, scores, standings should visually lead; chrome around them stays quiet.",
  ],
} as const;

export type Brand = typeof brand;
