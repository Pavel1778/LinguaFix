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

**Автоматически.** Workflow `.github/workflows/deploy-layero.yml` собирает и
деплоит `site/` на Layero при каждом изменении лендинга в `main`. Нужен один
секрет: получите API-токен в панели Layero и добавьте его в
**Settings → Secrets and variables → Actions** под именем `LAYERO_TOKEN`. Без
секрета шаг завершается предупреждением и не роняет сборку.

**Вручную** (если нужно задеплоить из локальной машины):

1. Зарегистрируйтесь на <https://layero.app> через GitHub.
2. Установите CLI и войдите:
   ```bash
   npm i -g layero@latest   # либо используйте npx
   layero login             # либо задайте LAYERO_TOKEN
   ```
3. Задеплойте из папки `site/`:
   ```bash
   cd site
   npx layero@latest deploy
   ```
   Сайт будет на `linguafix.layero.app`.

`layero.json` не обязателен, если Layero сам определяет Astro, но оставлен для
явности.

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
