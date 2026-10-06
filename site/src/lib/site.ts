// The site ships to two hosts that are both indexed, so they must not compete as
// duplicate content. Each host declares itself canonical and cross-links the other
// with hreflang:
//   - Layero (primary, Russian):  https://linguafix.layero.app
//   - Vercel (mirror, English):   https://linguafix.vercel.app
//
// VERCEL_URL is set for every Vercel build (including the stable production
// domain), so it selects the Vercel host. The canonical/OG origin is always the
// stable domain, never the per-deployment VERCEL_URL host.
export const LAYERO_URL = "https://linguafix.layero.app";
export const VERCEL_URL = "https://linguafix.vercel.app";

export const isVercel = Boolean(import.meta.env.VERCEL_URL);

/** Origin of the host currently being built. */
export const siteUrl = isVercel ? VERCEL_URL : LAYERO_URL;

/** BCP-47 language of the host currently being built. */
export const lang = isVercel ? "en" : "ru";

/** Text shown in a copy's own language, keyed by the host language. */
export function pick<T>(ru: T, en: T): T {
  return isVercel ? en : ru;
}
