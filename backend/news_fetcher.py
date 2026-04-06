"""The Ones AI Feed — News Fetcher

Direct RSS pulls from 22 sources across 9 categories. Positioned for
neurodivergent ADHD developers in AI: cognitive tools, neurodiversity,
ADHD-friendly dev workflows + standard AI news.
"""
import feedparser
import hashlib
import html
import logging
import re
import time
import urllib.request
import concurrent.futures
from dataclasses import dataclass, asdict
from typing import Dict, List

from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')
log = logging.getLogger('feed.fetcher')

USER_AGENT = 'Mozilla/5.0 (compatible; TheOnesNewsBot/1.0; +https://feed.theones.io)'
feedparser.USER_AGENT = USER_AGENT


CATEGORIES = {
    'neurodiversity': {
        'name': 'Neurodiversity',
        'icon': '🧠✨',
        'color': '#10b981',
        'sources': [
            ('ADDitude Magazine', 'https://www.additudemag.com/feed/'),
            ('CHADD', 'https://chadd.org/feed/'),
            ('Medium · Neurodiversity', 'https://medium.com/feed/tag/neurodiversity'),
            ('Medium · ADHD', 'https://medium.com/feed/tag/adhd'),
            ('r/neurodiversity', 'https://www.reddit.com/r/neurodiversity/.rss'),
        ],
    },
    'adhd_dev': {
        'name': 'ADHD Devs',
        'icon': '⚡',
        'color': '#fbbf24',
        'sources': [
            ('r/ADHD_Programmers', 'https://www.reddit.com/r/ADHD_Programmers/.rss'),
            ('HN · ADHD', 'https://hnrss.org/newest?q=ADHD'),
            ('HN · neurodivergent', 'https://hnrss.org/newest?q=neurodivergent'),
            ('r/ADHD', 'https://www.reddit.com/r/ADHD/.rss'),
        ],
    },
    'models': {
        'name': 'Models & Labs',
        'icon': '🧠',
        'color': '#6366f1',
        'sources': [
            ('OpenAI', 'https://openai.com/blog/rss.xml'),
            ('Google AI', 'https://blog.google/technology/ai/rss/'),
            ('DeepMind', 'https://deepmind.google/blog/rss.xml'),
            ('Microsoft AI', 'https://www.microsoft.com/en-us/ai/blog/feed/'),
        ],
    },
    'research': {
        'name': 'Research & Papers',
        'icon': '📄',
        'color': '#f59e0b',
        'sources': [
            ('arXiv cs.AI', 'https://export.arxiv.org/rss/cs.AI'),
            ('MIT Tech Review AI', 'https://www.technologyreview.com/topic/artificial-intelligence/feed'),
        ],
    },
    'open_source': {
        'name': 'Open Source',
        'icon': '🛠️',
        'color': '#84cc16',
        'sources': [
            ('Hugging Face', 'https://huggingface.co/blog/feed.xml'),
            ('Simon Willison', 'https://simonwillison.net/atom/everything/'),
        ],
    },
    'cloud': {
        'name': 'Cloud & Infra',
        'icon': '☁️',
        'color': '#06b6d4',
        'sources': [
            ('AWS ML Blog', 'https://aws.amazon.com/blogs/machine-learning/feed/'),
            ('Cloudflare AI', 'https://blog.cloudflare.com/tag/ai/rss/'),
        ],
    },
    'business': {
        'name': 'Business',
        'icon': '💼',
        'color': '#ec4899',
        'sources': [
            ('VentureBeat AI', 'https://venturebeat.com/category/ai/feed/'),
            ('TechCrunch AI', 'https://techcrunch.com/category/artificial-intelligence/feed/'),
            ('AI News', 'https://www.artificialintelligence-news.com/feed/'),
        ],
    },
    'news': {
        'name': 'Tech News',
        'icon': '📰',
        'color': '#f97316',
        'sources': [
            ('The Verge AI', 'https://www.theverge.com/rss/ai-artificial-intelligence/index.xml'),
            ('Ars Technica', 'https://feeds.arstechnica.com/arstechnica/index'),
        ],
    },
    'community': {
        'name': 'Community',
        'icon': '💬',
        'color': '#8b5cf6',
        'sources': [
            ('Hacker News', 'https://news.ycombinator.com/rss'),
        ],
    },
}


DAILY_THEMES = {
    0: {'title': 'Monday: AI for ADHD Devs', 'subtitle': 'Tools, tactics, and stories from neurodivergent builders', 'categories': ['adhd_dev', 'neurodiversity', 'models']},
    1: {'title': 'Tuesday: Models & Open Source', 'subtitle': 'Latest from labs and the community', 'categories': ['models', 'open_source', 'adhd_dev']},
    2: {'title': 'Wednesday: Research Day', 'subtitle': 'Papers worth your hyperfocus', 'categories': ['research', 'neurodiversity', 'models']},
    3: {'title': 'Thursday: Build & Ship', 'subtitle': 'Cloud, infra, and dev workflows for ND minds', 'categories': ['cloud', 'open_source', 'adhd_dev']},
    4: {'title': 'Friday: Industry & Brain', 'subtitle': 'Business news + how AI is changing how we think', 'categories': ['business', 'neurodiversity', 'news']},
    5: {'title': 'Saturday: Long Reads', 'subtitle': 'Catch up on what your brain liked this week', 'categories': ['research', 'neurodiversity', 'community']},
    6: {'title': 'Sunday: Reset & Plan', 'subtitle': 'Tools and rituals for the week ahead', 'categories': ['adhd_dev', 'open_source', 'cloud']},
}


FALLBACK_IMAGES = {
    'neurodiversity': [
        'https://images.unsplash.com/photo-1530497610245-94d3c16cda28?w=800&q=80',
        'https://images.unsplash.com/photo-1559757148-5c350d0d3c56?w=800&q=80',
    ],
    'adhd_dev': [
        'https://images.unsplash.com/photo-1518770660439-4636190af475?w=800&q=80',
        'https://images.unsplash.com/photo-1542831371-29b0f74f9713?w=800&q=80',
    ],
    'models': [
        'https://images.unsplash.com/photo-1620712943543-bcc4688e7485?w=800&q=80',
        'https://images.unsplash.com/photo-1677442136019-21780ecad995?w=800&q=80',
    ],
    'research': [
        'https://images.unsplash.com/photo-1532094349884-543bc11b234d?w=800&q=80',
        'https://images.unsplash.com/photo-1456513080510-7bf3a84b82f8?w=800&q=80',
    ],
    'open_source': [
        'https://images.unsplash.com/photo-1556075798-4825dfaaf498?w=800&q=80',
        'https://images.unsplash.com/photo-1618401471353-b98afee0b2eb?w=800&q=80',
    ],
    'cloud': [
        'https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=800&q=80',
        'https://images.unsplash.com/photo-1544197150-b99a580bb7a8?w=800&q=80',
    ],
    'business': [
        'https://images.unsplash.com/photo-1444653614773-995cb1ef9efa?w=800&q=80',
        'https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=800&q=80',
    ],
    'news': [
        'https://images.unsplash.com/photo-1495020689067-958852a7765e?w=800&q=80',
        'https://images.unsplash.com/photo-1504711434969-e33886168f5c?w=800&q=80',
    ],
    'community': [
        'https://images.unsplash.com/photo-1522071820081-009f0129c71c?w=800&q=80',
        'https://images.unsplash.com/photo-1543269865-cbf427effbad?w=800&q=80',
    ],
}


@dataclass
class NewsItem:
    id: str
    title_pl: str   # name kept for template compat — content is EN
    title_en: str
    summary_pl: str
    summary_en: str
    url: str
    source: str
    published: str
    category: str
    category_name: str
    icon: str
    image: str
    is_fun: bool = False

    def to_dict(self) -> Dict:
        return asdict(self)


def _strip_html(raw: str) -> str:
    if not raw:
        return ''
    try:
        text = BeautifulSoup(raw, 'html.parser').get_text(separator=' ')
    except Exception:
        text = re.sub(r'<[^>]+>', ' ', raw)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def _extract_image(entry, fallback_list, item_id):
    for key in ('media_thumbnail', 'media_content'):
        media = getattr(entry, key, None)
        if media:
            try:
                url = media[0].get('url', '')
                if url and url.startswith('http'):
                    return url
            except Exception:
                pass
    for link in entry.get('links', []) or []:
        if link.get('rel') == 'enclosure' and (link.get('type') or '').startswith('image/'):
            return link.get('href', '')
    summary = entry.get('summary', '')
    m = re.search(r'<img[^>]+src="([^"]+)"', summary)
    if m:
        return m.group(1)
    if fallback_list:
        idx = int(item_id[:6], 16) % len(fallback_list)
        return fallback_list[idx]
    return ''


class NewsFetcher:
    def __init__(self, cache_ttl: int = 1800):
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, Dict] = {}

    def _fetch_rss(self, url, timeout=20):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': USER_AGENT,
                'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml, */*',
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return feedparser.parse(raw)
        except Exception as e:
            log.warning(f'rss fetch failed for {url}: {e}')
            return None

    def fetch_category(self, category, max_items=12):
        cached = self._cache.get(category)
        if cached and time.time() - cached['ts'] < self.cache_ttl:
            return cached['items']
        cfg = CATEGORIES.get(category)
        if not cfg:
            return []
        items: List[NewsItem] = []
        per_source = max(2, max_items // max(1, len(cfg['sources'])))
        for source_name, src_url in cfg['sources']:
            feed = self._fetch_rss(src_url)
            if not feed or not feed.entries:
                continue
            for entry in feed.entries[:per_source]:
                published = entry.get('published', entry.get('updated', ''))
                try:
                    if published and not published[0].isdigit():
                        from email.utils import parsedate_to_datetime
                        published_iso = parsedate_to_datetime(published).isoformat()
                    else:
                        published_iso = published[:19] if len(published) >= 19 else published
                except Exception:
                    published_iso = ''
                title = _strip_html(entry.get('title', ''))[:200]
                summary = _strip_html(entry.get('summary', ''))[:600]
                link = entry.get('link', '')
                if not link or not title:
                    continue
                item_id = hashlib.md5(link.encode()).hexdigest()[:16]
                image = _extract_image(entry, FALLBACK_IMAGES.get(category, []), item_id)
                items.append(NewsItem(
                    id=item_id, title_pl=title, title_en=title,
                    summary_pl=summary, summary_en=summary,
                    url=link, source=source_name, published=published_iso,
                    category=category, category_name=cfg['name'],
                    icon=cfg['icon'], image=image, is_fun=False,
                ))
        seen = set()
        deduped = []
        items.sort(key=lambda x: x.published or '', reverse=True)
        for it in items:
            if it.id in seen:
                continue
            seen.add(it.id)
            deduped.append(it)
        items = deduped[:max_items]
        self._cache[category] = {'ts': time.time(), 'items': items}
        return items

    def fetch_categories_parallel(self, categories):
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(self.fetch_category, c): c for c in categories}
            for fut in concurrent.futures.as_completed(futs):
                c = futs[fut]
                try:
                    results[c] = fut.result()
                except Exception as e:
                    log.warning(f'category {c} fetch failed: {e}')
                    results[c] = []
        return results
