// @ts-check
import { defineConfig, fontProviders } from "astro/config";
import tailwind from "@astrojs/tailwind";
import sitemap from "@astrojs/sitemap";

// Update `site` to the production domain once the Vercel project is created,
// so canonical URLs and the generated sitemap point at the real host.
// Override at build time with the SITE_URL environment variable (for example
// in Vercel: Settings → Environment Variables → SITE_URL). The default is the
// domain that actually serves the site today; the old default host returned
// 404, which made the canonical/og:image URLs point at a dead domain.
const site = process.env.SITE_URL || "https://linguafix.layero.app";

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
