# LinguaFix — лендинг

Статический сайт (Astro 5 + Tailwind CSS) для проекта
[LinguaFix](https://github.com/Pavel1778/LinguaFix).

## Локальный запуск

```bash
cd site
npm install
npm run dev        # http://localhost:4321
```

Сборка и предпросмотр:

```bash
npm run build      # dist/
npm run preview
```

## Структура

```
site/
├── astro.config.mjs      # site URL, интеграции (tailwind, sitemap)
├── tailwind.config.mjs
├── vercel.json           # конфиг для Vercel
├── layero.json           # конфиг для Layero
├── deploy.sh             # сборка + деплой
├── public/               # favicon, logo, og-image, robots.txt, скриншоты
└── src/
    ├── consts.ts         # URL-ы (repo, releases, .deb) и версия
    ├── layouts/Base.astro
    ├── components/       # 10 секций + CodeBlock
    ├── pages/index.astro
    └── styles/global.css
```

## Деплой

### Vercel (основной)

1. Зарегистрируйтесь на <https://vercel.com> через GitHub.
2. **Add New → Project** → выберите репозиторий `LinguaFix`.
3. **Root Directory** = `site`.
4. Framework определится как Astro; build — `npm run build`, output — `dist`.
5. **Deploy**. Сайт будет на `<проект>.vercel.app`.

### Layero (зеркало для РФ)

Проект Layero **подключён к репозиторию**: платформа сама собирает и публикует
сайт на каждом push в `main`. Репозиторий самодостаточен для сборки — на это
работают два файла:

- корневой **`layero.json`** — описывает сборку монорепо, т.к. приложение лежит
  не в корне: `framework: generic`, `buildCommand: npm --prefix site ci &&
  npm --prefix site run build`, `outputDirectory: site/dist`. Без него Layero
  из корня не находит приложение («This folder has no app of its own»).
- `site/layero.json` — настройки, если собирать из папки `site/` вручную.

Проверить план сборки без выгрузки (логин не нужен):

```bash
npx layero@latest deploy --dry-run
```

**Вручную** (не обязательно, только для локальной проверки):

```bash
npx layero@latest deploy --root site
```

`layero.json` не обязателен, если Layero сам определяет Astro, но для монорепо
корневой файл нужен явно.

## Обновление версии

Версия и ссылки на релиз живут в `src/consts.ts` (`VERSION`). При выпуске новой
версии поменяйте `VERSION` — ссылка на `.deb` и строка в Hero обновятся
автоматически. `site` в `astro.config.mjs` и `robots.txt` стоит поправить на
боевой домен после деплоя.

## Что менять

- **Скриншоты** — `public/screenshots/*.svg` это плейсхолдеры. Замените их
  реальными снимками GUI (`.png`), сохранив имена, либо обновите пути в
  `Hero.astro`.
- **OG-изображение** — `public/og-image.png` (1200×630).
