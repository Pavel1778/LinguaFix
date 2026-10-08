// Shared dictionary metadata for the landing page and the /dictionaries page.
//
// The base frequency lists and the thematic (professional) lists are described
// once here, so the download section and the catalogue never drift apart. Sizes
// and word counts are read from the repository at build time, so a card always
// reflects what is actually shipped.
import fs from "node:fs";
import path from "node:path";

import { REPO } from "../consts";

/** Stable URL prefix for release assets (attached to every GitHub Release). */
export const DICTIONARY_ASSET_BASE = `${REPO}/releases/latest/download`;

export type BaseLanguage = { code: string; title: string };

/** Languages that ship a base frequency list (`<code>-50k.txt`). */
export const baseLanguages: BaseLanguage[] = [
  { code: "ru", title: "Русский" },
  { code: "en", title: "English" },
  { code: "uk", title: "Українська" },
  { code: "de", title: "Deutsch" },
  { code: "fr", title: "Français" },
];

export type ThematicCategory = {
  slug: string;
  /** Localised titles; the site picks one per host language. */
  title: { ru: string; en: string };
  blurb: { ru: string; en: string };
  license: string;
};

/** Thematic (professional) categories, one release archive each. */
export const thematicCategories: ThematicCategory[] = [
  {
    slug: "it",
    title: { ru: "IT / программирование", en: "IT / programming" },
    blurb: {
      ru: "Языки, фреймворки, git, БД, сети, DevOps.",
      en: "Languages, frameworks, git, databases, networks, DevOps.",
    },
    license: "MIT",
  },
  {
    slug: "medicine",
    title: { ru: "Медицина и биология", en: "Medicine and biology" },
    blurb: {
      ru: "Анатомия, болезни, препараты, диагностика.",
      en: "Anatomy, diseases, drugs, diagnostics.",
    },
    license: "MIT",
  },
  {
    slug: "legal",
    title: { ru: "Юриспруденция", en: "Law" },
    blurb: { ru: "Кодексы, процессы, договоры, суд.", en: "Codes, proceedings, contracts, courts." },
    license: "MIT",
  },
  {
    slug: "finance",
    title: { ru: "Финансы и бухгалтерия", en: "Finance and accounting" },
    blurb: {
      ru: "Банки, налоги, отчётность, инвестиции.",
      en: "Banking, taxes, reporting, investments.",
    },
    license: "MIT",
  },
  {
    slug: "engineering",
    title: { ru: "Инженерия и строительство", en: "Engineering" },
    blurb: {
      ru: "Сопромат, механизмы, материалы, ГОСТы.",
      en: "Mechanics, materials, drawings, standards.",
    },
    license: "MIT",
  },
];

const dictRoot = path.resolve(process.cwd(), "..", "dictionaries");

export function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function countWords(file: string): number {
  try {
    return fs
      .readFileSync(file, "utf-8")
      .split("\n")
      .filter((line) => line.trim().length > 0).length;
  } catch {
    return 0;
  }
}

function fileSize(file: string): number {
  try {
    return fs.statSync(file).size;
  } catch {
    return 0;
  }
}

export type CategoryFile = { lang: string; title: string; size: number; words: number };
export type CategoryCard = ThematicCategory & { files: CategoryFile[] };

/** Categories with per-language file size and word count read from the repo. */
export const categoryCards: CategoryCard[] = thematicCategories.map((cat) => ({
  ...cat,
  files: [
    { lang: "ru", title: "Русский" },
    { lang: "en", title: "English" },
  ].map(({ lang, title }) => {
    const file = path.join(dictRoot, cat.slug, `${lang}-${cat.slug}-1k.txt`);
    return { lang, title, size: fileSize(file), words: countWords(file) };
  }),
}));

/** Total number of words across every thematic category (both languages). */
export const thematicWordTotal = categoryCards.reduce(
  (sum, cat) => sum + cat.files.reduce((n, file) => n + file.words, 0),
  0,
);
