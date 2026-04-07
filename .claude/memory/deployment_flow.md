---
name: MLB bot deployment flow
description: How to run the bot and deploy to the website — run main.py, then push site/ to kern-mlb repo for GitHub Pages
type: reference
---

## Run the bot
```bash
cd ~/Desktop/mlb-bot
source venv/bin/activate
python main.py
```

## Push to website
The site is a separate git repo inside `site/` that deploys to GitHub Pages via Actions.
```bash
cd site
git add -A && git commit -m "Update $(date +%Y-%m-%d)" && git push
```

## Website URL
https://nkernaghan.github.io/kern-mlb/

## GitHub repos
- Code: github.com/nkernaghan/mlb-bot (private)
- Site: github.com/nkernaghan/kern-mlb (public)

## n8n
- Start: `NODE_FUNCTION_ALLOW_BUILTIN=child_process nohup n8n start > /tmp/n8n.log 2>&1 &`
- URL: http://localhost:5678
- Launchd plist at ~/Library/LaunchAgents/com.n8n.start.plist (broken, use manual start)
