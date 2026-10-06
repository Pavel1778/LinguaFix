import type { APIRoute } from "astro";
import { siteUrl } from "../lib/site";

// Both hosts are indexed, so each allows crawlers and points at its own sitemap.
// A static public file cannot express this because it would be identical on both
// hosts and would advertise the wrong sitemap URL on one of them.
export const GET: APIRoute = () => {
  const body = [
    "User-agent: *",
    "Allow: /",
    "",
    `Sitemap: ${siteUrl}/sitemap-index.xml`,
    "",
  ].join("\n");
  return new Response(body, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
};
