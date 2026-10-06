// @ts-check
import { defineConfig, fontProviders } from "astro/config";
import tailwind from "@astrojs/tailwind";
import sitemap from "@astrojs/sitemap";

// The site ships to two hosts that are both indexed: Layero (primary, Russian)
// and the Vercel mirror (English). Each build must declare its own origin so the
// canonical URLs, og:url and the sitemap point at the host that serves them,
// otherwise the two copies compete as duplicate content.
//
// VERCEL_URL is set for every Vercel build (including the stable production
// domain). SITE_URL overrides both for local checks.
const site =
  process.env.SITE_URL ||
  (process.env.VERCEL_URL ? "https://linguafix.vercel.app" : "https://linguafix.layero.app");

export default defineConfig({
  site,
  output: "static",
  integrations: [tailwind(), sitemap()],
  compressHTML: true,
  experimental: {
    // Self-hosted at build time with metric-matched fallbacks, so the text
    // does not reflow when the webfont swaps in (avoids layout shift).
    fonts: [
      {
        provider: fontProviders.google(),
        name: "Inter",
        cssVariable: "--font-inter",
        weights: [400, 500, 700],
        styles: ["normal"],
        subsets: ["latin", "cyrillic"],
        fallbacks: ["system-ui", "sans-serif"],
      },
      {
        provider: fontProviders.google(),
        name: "JetBrains Mono",
        cssVariable: "--font-mono",
        weights: [400],
        styles: ["normal"],
        subsets: ["latin", "cyrillic"],
        fallbacks: ["ui-monospace", "monospace"],
      },
    ],
  },
});
