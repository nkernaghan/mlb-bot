#!/bin/bash
# Push updated site data to GitHub Pages
set -e
cd /Users/nickkernaghan/Desktop/mlb-bot/site

DATE=$(date +%Y-%m-%d)

git add data/ index.html .github/
git diff --cached --quiet && echo "No changes to push" && exit 0

git commit -m "Update picks for ${DATE}"
git push origin main

echo "Site pushed to GitHub Pages"
