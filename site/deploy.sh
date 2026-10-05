#!/bin/bash
# Build the landing page and (optionally) deploy it.
#
#   ./deploy.sh            build only
#   ./deploy.sh vercel     build, then print the Vercel next step
#   ./deploy.sh layero     build, then `npx layero@latest deploy`
#
# Vercel deploys from the dashboard (import the repo, root directory = site/).
# Layero deploys from the CLI after `npx layero@latest login`.
set -e
cd "$(dirname "$0")"

npm ci
npm run build

target="${1:-}"
case "$target" in
  layero)
    npx layero@latest deploy
    ;;
  vercel)
    echo "Build complete. Deploy to Vercel: import the repo at https://vercel.com/new"
    echo "and set the root directory to 'site'."
    ;;
  "")
    echo "Build complete (dist/). Pass 'vercel' or 'layero' to deploy."
    ;;
  *)
    echo "Unknown target: $target" >&2
    exit 1
    ;;
esac
