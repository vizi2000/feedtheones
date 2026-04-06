# The Ones AI Feed

> Daily AI news curated for ADHD & neurodivergent developers.
> 25 sources, 9 categories, refreshed 4× daily, ADHD-friendly format.

Live: https://feed.theones.io

## Stack
- **Backend**: Flask (Python 3.10), feedparser, trafilatura, OpenAI SDK (litellm-compatible)
- **LLM**: borg.tools `claude-haiku-4-5` for article rewriting
- **Frontend**: Server-rendered Jinja2 + vanilla JS, dark theme, PWA
- **PWA**: Service Worker, manifest, offline page, push notifications via VAPID
- **Storage**: Per-article JSON cache (`cache/articles/`)

## Categories
1. **Neurodiversity** — ADDitude, CHADD, Medium, Reddit
2. **ADHD Devs** — r/ADHD_Programmers, HN search
3. Models & Labs (OpenAI, Google AI, DeepMind, Microsoft)
4. Research & Papers (arXiv, MIT Tech Review)
5. Open Source (Hugging Face, Simon Willison)
6. Cloud & Infra (AWS, Cloudflare)
7. Business (VentureBeat, TechCrunch, AI News)
8. Tech News (The Verge, Ars Technica)
9. Community (Hacker News)

## Local development
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
PORT=5101 python backend/app.py
```

## Production deploy
- systemd unit: `/etc/systemd/system/feed-theones.service`
- nginx vhost: `/etc/nginx/sites-enabled/feed.theones.io` (proxy_pass to :5101)
- runtime data: `/home/vizi/feed.theones.io/runtime/` (cache + .env)


## License
MIT
