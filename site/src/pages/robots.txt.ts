import type { APIRoute } from "astro";

// The Vercel copy is a protected preview; keep it out of every index. Layero is
// the canonical host and points crawlers at its sitemap. A static public file
// cannot express this because it would be identical on both hosts.
const isVercel = Boolean(import.meta.env.VERCEL_URL);

const LAYERO_ROBOTS = [
  "User-agent: *",
  "Allow: /",
  "",
  "Sitemap: https://linguafix.layero.app/sitemap-index.xml",
  "",
].join("\n");

const VERCEL_ROBOTS = ["User-agent: *", "Disallow: /", ""].join("\n");

export const GET: APIRoute = () =>
  new Response(isVercel ? VERCEL_ROBOTS : LAYERO_ROBOTS, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
