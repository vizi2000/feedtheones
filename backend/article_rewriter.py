"""
The Ones AI Feed - Article Rewriter
Fetches full article body from source URL, rewrites it in proper Polish
using an LLM (OpenRouter / Llama 3.3 70B), and caches results to disk.
"""
import os
import re
import json
import hashlib
import logging
import time
from typing import Dict, Optional, List
import trafilatura
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
try:
    from googlenewsdecoder import gnewsdecoder
    HAS_GNEWS_DECODER = True
except ImportError:
    HAS_GNEWS_DECODER = False

log = logging.getLogger('feed.rewriter')

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cache', 'articles')
os.makedirs(CACHE_DIR, exist_ok=True)

FEED_LLM_KEY = (
    os.environ.get('FEED_LLM_KEY')
    or os.environ.get('API_KEY_OTHER')
    or os.environ.get('OPENROUTER_API_KEY')
    or os.environ.get('API_KEY_OPENROUTER')
    or ''
)
FEED_LLM_BASE = os.environ.get('FEED_LLM_BASE', 'https://llm.borg.tools/v1')
FEED_LLM_MODEL = os.environ.get('FEED_LLM_MODEL', 'claude-haiku-4-5-20251001')
OPENROUTER_KEY = FEED_LLM_KEY  # back-compat alias
OPENROUTER_MODEL = FEED_LLM_MODEL

# System prompt for the rewriter LLM
SYSTEM_PROMPT = """You are a professional tech journalist writing for The Ones AI Feed — a curated AI news portal.
Your task: based on the provided source article (any language), write a fresh, original article in clear English.

RULES:
1. Write in crisp, factual English — like a senior tech journalist for The Verge or Ars Technica.
2. DO NOT translate literally — paraphrase, rewrite, add context and flow.
3. Preserve all key facts, numbers, model names, version numbers, citations.
4. Structure: short punchy lead (1-2 sentences), then 3-6 paragraphs.
5. ALWAYS use 2-4 section headings as ## Section Title — REQUIRED, divides article (e.g. ## What is it, ## How it works, ## Why it matters, ## The bigger picture). Minimum 2 ## headings per article.
6. Tone: informed, neutral, slightly skeptical. No marketing fluff. No emoji.
7. Length: minimum 300 words, optimal 400-700 words.
8. DO NOT add source links at the end — they are appended automatically.
9. Do NOT hallucinate. If the source is vague, be vague. Never invent quotes.
10. Output format: Markdown with H1 first line (# Title), then content.

Start immediately with the article. No preamble like "Here is the article:"."""


class ArticleRewriter:
    def __init__(self):
        self.client = None
        if OPENROUTER_KEY:
            self.client = OpenAI(
                api_key=OPENROUTER_KEY,
                base_url=FEED_LLM_BASE,
                default_headers={'User-Agent': 'Mozilla/5.0 TheOnesFeed/1.0',
                    'HTTP-Referer': 'https://feed.theones.io',
                    'X-Title': 'The Ones AI Feed',
                },
            )
        else:
            log.warning('No OPENROUTER_API_KEY set — rewriter will use fallback translation only')

    # ----------------------------------------------------------------------
    def _cache_path(self, article_id: str) -> str:
        return os.path.join(CACHE_DIR, f'{article_id}.json')

    def _load_cache(self, article_id: str) -> Optional[Dict]:
        path = self._cache_path(article_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Cache valid for 7 days
            if time.time() - data.get('cached_at', 0) < 7 * 86400:
                return data
        except Exception as e:
            log.warning(f'cache read error: {e}')
        return None

    def _save_cache(self, article_id: str, data: Dict) -> None:
        try:
            data['cached_at'] = time.time()
            with open(self._cache_path(article_id), 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning(f'cache save error: {e}')

    # ----------------------------------------------------------------------
    def _resolve_url(self, url: str) -> str:
        """Decode Google News redirect URLs to the actual article URL."""
        if not url:
            return url
        if 'news.google.com' not in url:
            return url
        if not HAS_GNEWS_DECODER:
            return url
        try:
            result = gnewsdecoder(url, interval=1)
            if isinstance(result, dict) and result.get('status') and result.get('decoded_url'):
                decoded = result['decoded_url']
                log.info(f'decoded gnews url -> {decoded[:80]}')
                return decoded
        except Exception as e:
            log.warning(f'gnews decode failed: {e}')
        return url

    # ----------------------------------------------------------------------
    def _extract_article_images(self, html: str, base_url: str, max_images: int = 6) -> List[str]:
        """Extract all meaningful images from article HTML.
        Filters out icons, ads, tracking pixels, logos. Returns absolute URLs.
        """
        from urllib.parse import urljoin
        try:
            soup = BeautifulSoup(html, 'lxml')
        except Exception:
            return []

        # Find the main article container (try common selectors)
        article_root = (
            soup.find('article')
            or soup.find('main')
            or soup.find(attrs={'role': 'main'})
            or soup.find(class_=re.compile(r'(article|post|content|story)-body|article-content|entry-content', re.I))
            or soup
        )

        seen = set()
        images = []

        # 1. og:image first (usually the hero)
        og = soup.find('meta', property='og:image') or soup.find('meta', attrs={'name': 'og:image'})
        if og and og.get('content'):
            src = og['content'].strip()
            if src.startswith('//'):
                src = 'https:' + src
            elif not src.startswith('http'):
                src = urljoin(base_url, src)
            if src not in seen:
                seen.add(src)
                images.append(src)

        # 2. All img tags inside article body
        for img in article_root.find_all('img'):
            src = (img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                   or img.get('data-original') or img.get('data-srcset', '').split(' ')[0]
                   or '')
            if not src:
                # Try srcset
                srcset = img.get('srcset', '')
                if srcset:
                    src = srcset.split(',')[0].strip().split(' ')[0]
            if not src:
                continue
            src = src.strip()
            if src.startswith('//'):
                src = 'https:' + src
            elif not src.startswith('http'):
                src = urljoin(base_url, src)

            # Filter out unwanted images
            lower = src.lower()
            if any(skip in lower for skip in [
                'data:image', '.gif', 'pixel.', '/pixel', 'tracker', 'analytics',
                '/ads/', '/ad-', 'doubleclick', 'logo', 'icon', 'avatar',
                'badge', 'sprite', 'placeholder', '1x1', 'spacer', 'blank.',
                'amazon-adsystem', 'googletagmanager',
            ]):
                continue

            # Skip very small images by checking width/height attrs
            try:
                w = int(img.get('width', '0') or 0)
                h = int(img.get('height', '0') or 0)
                if w and w < 200:
                    continue
                if h and h < 150:
                    continue
            except (ValueError, TypeError):
                pass

            if src in seen:
                continue
            seen.add(src)
            images.append(src)
            if len(images) >= max_images:
                break

        # 3. Also check picture/source tags
        for picture in article_root.find_all('picture'):
            source = picture.find('source')
            if source and source.get('srcset'):
                src = source['srcset'].split(',')[0].strip().split(' ')[0]
                if src.startswith('//'):
                    src = 'https:' + src
                elif not src.startswith('http'):
                    src = urljoin(base_url, src)
                if src and src not in seen:
                    seen.add(src)
                    images.append(src)
                    if len(images) >= max_images:
                        break

        return images[:max_images]

    # ----------------------------------------------------------------------
    def scrape_article(self, url: str) -> Dict:
        """Extract clean body text + images from an article URL."""
        # Resolve Google News redirect first
        real_url = self._resolve_url(url)
        try:
            r = requests.get(real_url, headers={'User-Agent': USER_AGENT}, timeout=15, allow_redirects=True)
            if r.status_code != 200:
                log.warning(f'scrape http {r.status_code} for {real_url}')
                return {'body': '', 'title': '', 'final_url': real_url, 'images': []}
            html = r.text
            extracted = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=False,
                favor_recall=True,
                output_format='txt',
                with_metadata=False,
            )
            metadata = trafilatura.extract_metadata(html)
            title = metadata.title if metadata and metadata.title else ''
            images = self._extract_article_images(html, base_url=r.url, max_images=6)
            log.info(f'scraped {len(images)} images from {real_url[:60]}')
            return {
                'body': (extracted or '').strip(),
                'title': title.strip(),
                'final_url': r.url,
                'images': images,
            }
        except Exception as e:
            log.warning(f'scrape failed for {real_url}: {e}')
            return {'body': '', 'title': '', 'final_url': real_url, 'images': []}

    # ----------------------------------------------------------------------
    def rewrite_to_polish(self, title_en: str, body_en: str, source: str) -> str:
        """Rewrite article in Polish using LLM. Returns markdown text."""
        if not self.client:
            return ''

        # Truncate body to avoid huge LLM cost - keep first ~6000 chars (well-formed news bodies)
        body_excerpt = (body_en or '')[:6000]
        if not body_excerpt and not title_en:
            return ''

        user_msg = (
            f'Źródło: {source}\n\n'
            f'Oryginalny tytuł: {title_en}\n\n'
            f'Treść oryginalna:\n{body_excerpt}\n\n'
            f'Napisz nowy artykuł po polsku zgodnie z zasadami.'
        )
        try:
            response = self.client.chat.completions.create(
                model=OPENROUTER_MODEL,
                messages=[
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': user_msg},
                ],
                temperature=0.7,
                max_tokens=1500,
            )
            return (response.choices[0].message.content or '').strip()
        except Exception as e:
            log.error(f'LLM rewrite failed: {e}')
            return ''

    # ----------------------------------------------------------------------
    @staticmethod
    def _auto_promote_section_titles(md: str) -> str:
        """Detect plain-text section titles and promote them to ## headers.

        A line is considered a section title if:
        - It's short (< 80 chars)
        - Not ending in punctuation (. ! ? : , ; - —)
        - Not starting with #, !, -, *, > or quote
        - Surrounded by longer text lines or blank lines
        - Not the H1 title (first line)
        """
        lines = md.split('\n')
        out = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Skip empty, headers, lists, images, blockquotes
            if (not stripped or stripped.startswith('#') or stripped.startswith('!')
                    or stripped.startswith('-') or stripped.startswith('*')
                    or stripped.startswith('>') or stripped.startswith('"')
                    or stripped.startswith('„')):
                out.append(line)
                continue

            # Check if it looks like a section title
            is_short = len(stripped) < 80
            ends_with_punct = stripped[-1] in '.!?:,;—-"”'
            has_period_inside = '. ' in stripped
            words = stripped.split()
            word_count = len(words)

            # Title heuristic
            looks_like_title = (
                is_short
                and not ends_with_punct
                and not has_period_inside
                and 2 <= word_count <= 10
            )
            if looks_like_title:
                # Make sure surrounding lines are longer (to avoid false positives)
                prev_long = i > 0 and len(lines[i - 1].strip()) > 100
                next_long = i < len(lines) - 1 and len(lines[i + 1].strip()) > 100
                if prev_long or next_long:
                    out.append('')
                    out.append('## ' + stripped)
                    out.append('')
                    continue
            out.append(line)
        return '\n'.join(out)

    @staticmethod
    def _embed_images_in_markdown(md: str, images: List[str], hero_image: str = '') -> str:
        """Insert images into markdown intelligently.

        Strategy:
        0. Auto-promote plain-text section titles to ## H2 headers
        1. Embed the hero image right after the H1
        2. Distribute remaining images after each H2 section
        3. Fallback: every Nth text line if no H2s found
        """
        if not md or not images:
            return md

        # Step 0: Auto-promote section titles
        md = ArticleRewriter._auto_promote_section_titles(md)

        def _norm(u):
            return (u or '').split('?')[0].rstrip('/').lower()

        primary_hero = images[0] if images else ''
        body_imgs = [img for img in images[1:] if _norm(img) != _norm(primary_hero)]

        lines = md.split('\n')

        # Step 1: Insert hero image right after the H1 line
        if primary_hero:
            for i, line in enumerate(lines):
                if line.strip().startswith('# '):
                    lines.insert(i + 1, '')
                    lines.insert(i + 2, f'![]({primary_hero})')
                    lines.insert(i + 3, '')
                    break

        if not body_imgs:
            return '\n'.join(lines)

        # Step 2: Find H2 boundaries
        h2_indices = [i for i, line in enumerate(lines) if line.strip().startswith('## ')]

        if h2_indices:
            inserts = []
            for idx, h2_line_idx in enumerate(h2_indices):
                if idx >= len(body_imgs):
                    break
                inserts.append((h2_line_idx + 1, body_imgs[idx]))
            for line_idx, img_url in reversed(inserts):
                lines.insert(line_idx, '')
                lines.insert(line_idx + 1, f'![]({img_url})')
                lines.insert(line_idx + 2, '')
        else:
            # Fallback: distribute images after every Nth text line
            text_line_indices = []
            for i, line in enumerate(lines):
                stripped = line.strip()
                if (stripped and not stripped.startswith('#') and not stripped.startswith('!')
                        and len(stripped) > 60):
                    text_line_indices.append(i)
            if len(text_line_indices) >= 3 and body_imgs:
                # Skip the first line (right after H1+hero), then distribute
                # Take indices from index 1 onwards
                usable = text_line_indices[1:]
                if usable:
                    spacing = max(1, len(usable) // (len(body_imgs) + 1))
                    inserts = []
                    for idx, img in enumerate(body_imgs):
                        pos = (idx + 1) * spacing
                        if pos >= len(usable):
                            break
                        line_idx = usable[pos]
                        inserts.append((line_idx + 1, img))  # insert AFTER that line
                    for line_idx, img_url in reversed(inserts):
                        lines.insert(line_idx, '')
                        lines.insert(line_idx + 1, f'![]({img_url})')
                        lines.insert(line_idx + 2, '')

        return '\n'.join(lines)

    # ----------------------------------------------------------------------
    def get_article(self, article_id: str, url: str, fallback_title: str,
                    fallback_summary: str, source: str) -> Dict:
        """Main entry point: get rewritten Polish article (with caching)."""
        cached = self._load_cache(article_id)
        # Re-process if cache exists but is from old version (no 'images' field)
        if cached and 'images' in cached:
            log.info(f'article cache hit | {article_id}')
            return cached

        log.info(f'rewriting article | {article_id} | {url[:60]}')

        # 1. Scrape article body + images
        scraped = self.scrape_article(url)
        body = scraped['body']
        title = scraped['title'] or fallback_title
        scraped_images = scraped.get('images', [])

        # 2. If body too short, use fallback summary
        if len(body) < 200:
            body = fallback_summary or fallback_title or ''

        # 3. Rewrite in Polish
        rewritten_md = self.rewrite_to_polish(title, body, source)

        # 4. Fallback if LLM failed: use translated body via deep-translator
        if not rewritten_md:
            try:
                from deep_translator import GoogleTranslator
                tr = GoogleTranslator(source='auto', target='pl')
                pl_body = ''
                src = body[:6000] or fallback_summary or fallback_title
                for i in range(0, len(src), 4500):
                    pl_body += tr.translate(src[i:i+4500]) + ' '
                pl_title = tr.translate(title[:500]) if title else fallback_title
                rewritten_md = f'# {pl_title}\n\n{pl_body.strip()}'
            except Exception as e:
                log.error(f'fallback translation failed: {e}')
                rewritten_md = f'# {fallback_title}\n\n{fallback_summary or "Treść niedostępna."}'

        # 5. Embed scraped images into markdown
        # The hero image is the first scraped image (typically og:image)
        hero_image = scraped_images[0] if scraped_images else ''
        rewritten_md = self._embed_images_in_markdown(rewritten_md, scraped_images, hero_image=hero_image)

        result = {
            'id': article_id,
            'url': url,
            'source': source,
            'content_md': rewritten_md,
            'word_count': len(rewritten_md.split()),
            'images': scraped_images,
        }
        self._save_cache(article_id, result)
        return result


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)
    rw = ArticleRewriter()
    test_url = sys.argv[1] if len(sys.argv) > 1 else 'https://www.allure.com/story/skin-care-routine'
    result = rw.get_article(
        article_id='test123',
        url=test_url,
        fallback_title='Test',
        fallback_summary='Test summary',
        source='Allure',
    )
    print(result['content_md'][:2000])
    print(f'\n\n[words: {result["word_count"]}]')
