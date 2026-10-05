// @ts-check
import { defineConfig } from "astro/config";
import tailwind from "@astrojs/tailwind";
import sitemap from "@astrojs/sitemap";

// Update `site` to the production domain once the Vercel project is created,
// so canonical URLs and the generated sitemap point at the real host.
export default defineConfig({
  site: "https://linguafix.vercel.app",
  output: "static",
  integrations: [tailwind(), sitemap()],
  compressHTML: true,
});
