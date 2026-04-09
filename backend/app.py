"""
The Ones AI Feed - Flask Application
Serves the modern beauty news portal with daily themed content.
"""
import os
import sys
import datetime
import logging
from flask import Flask, render_template, jsonify, request, send_from_directory, make_response

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from news_fetcher import NewsFetcher, CATEGORIES, DAILY_THEMES
from article_rewriter import ArticleRewriter
from prerewriter import PreRewriter
from stats import StatsTracker
from comments import CommentsStore
from push_notifications import PushManager

log = logging.getLogger('feed.app')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')

app = Flask(
    __name__,
    template_folder=TEMPLATES_DIR,
    static_folder=STATIC_DIR,
)

fetcher = NewsFetcher(cache_ttl=1800)  # 30 minutes
rewriter = ArticleRewriter()
prerewriter = PreRewriter(rewriter, max_workers=2, max_per_run=40)
stats_tracker = StatsTracker(
    storage_path=os.path.join(BASE_DIR, 'cache', 'stats.json'))
comments_store = CommentsStore(
    storage_path=os.path.join(BASE_DIR, 'cache', 'comments.json'))
push_manager = PushManager(
    storage_path=os.path.join(BASE_DIR, 'cache', 'push_subs.json'),
    vapid_path=os.path.join(BASE_DIR, 'cache', 'vapid_private.pem'),
    subject='mailto:feed-theones@local',
)

# In-memory map: article_id -> news item dict (for /api/article lookups)
_item_index = {}


def _index_items(items_dict):
    """Add items to the in-memory index for later lookup by ID."""
    global _item_index
    for cat_data in items_dict.values():
        for item in cat_data.get('items', []):
            _item_index[item['id']] = item


def _get_neighbors(article_id):
    """Return (prev_id, next_id) based on insertion order in _item_index.
    Wraps around at the ends so navigation is always cyclic."""
    ids = list(_item_index.keys())
    if not ids or article_id not in ids:
        return (None, None)
    idx = ids.index(article_id)
    prev_id = ids[idx - 1] if idx > 0 else ids[-1]
    next_id = ids[idx + 1] if idx < len(ids) - 1 else ids[0]
    return (prev_id, next_id)


def get_today_theme():
    """Get the daily theme based on current weekday."""
    weekday = datetime.datetime.now().weekday()
    return DAILY_THEMES.get(weekday, DAILY_THEMES[0]), weekday


@app.route('/')
def index():
    """Main page - shows today's themed news."""
    theme, weekday = get_today_theme()
    today_label = datetime.datetime.now().strftime('%d.%m.%Y')
    return render_template(
        'index.html',
        theme=theme,
        weekday=weekday,
        today_label=today_label,
        all_categories=CATEGORIES,
        all_themes=DAILY_THEMES,
    )


@app.route('/api/news')
def api_news():
    """Return news for today's theme (or specific categories)."""
    cats_param = request.args.get('categories')
    if cats_param:
        categories = [c.strip() for c in cats_param.split(',') if c.strip() in CATEGORIES]
    else:
        theme, _ = get_today_theme()
        categories = theme['categories']

    results = fetcher.fetch_categories_parallel(categories)
    payload = {}
    for cat in categories:
        items = results.get(cat, [])
        payload[cat] = {
            'name': CATEGORIES[cat]['name'],
            'icon': CATEGORIES[cat]['icon'],
            'color': CATEGORIES[cat]['color'],
            'items': [it.to_dict() for it in items],
        }
    _index_items(payload)

    # Trigger background pre-rewriting for all items in this batch
    all_items_flat = []
    for cat in categories:
        all_items_flat.extend(payload[cat]['items'])
    try:
        prerewriter.enqueue_items(all_items_flat)
    except Exception as e:
        log.warning(f'prerewriter enqueue failed: {e}')

    return jsonify({
        'generated_at': datetime.datetime.now().isoformat(),
        'categories': payload,
    })


@app.route('/api/category/<category>')
def api_category(category):
    """Return news for a single category."""
    if category not in CATEGORIES:
        return jsonify({'error': 'unknown category'}), 404
    items = fetcher.fetch_category(category)
    return jsonify({
        'category': category,
        'name': CATEGORIES[category]['name'],
        'icon': CATEGORIES[category]['icon'],
        'items': [it.to_dict() for it in items],
    })


@app.route('/api/article/<article_id>')
def api_article(article_id):
    """Return the rewritten Polish article body for a given article id."""
    item = _item_index.get(article_id)
    if not item:
        # Maybe cache was lost (server restart) - try to refresh news first
        theme, _ = get_today_theme()
        results = fetcher.fetch_categories_parallel(theme['categories'])
        payload = {}
        for cat in theme['categories']:
            payload[cat] = {'items': [it.to_dict() for it in results.get(cat, [])]}
        _index_items(payload)
        item = _item_index.get(article_id)
    if not item:
        return jsonify({'error': 'article not found, refresh page'}), 404

    article = rewriter.get_article(
        article_id=article_id,
        url=item['url'],
        fallback_title=item.get('title_en') or item.get('title_pl', ''),
        fallback_summary=item.get('summary_en') or item.get('summary_pl', ''),
        source=item.get('source', ''),
    )
    # Add original item metadata for the modal
    article['title_pl'] = item.get('title_pl', '')
    article['source'] = item.get('source', '')
    article['image'] = item.get('image', '')
    article['category_name'] = item.get('category_name', '')
    article['icon'] = item.get('icon', '')
    article['published'] = item.get('published', '')
    prev_id, next_id = _get_neighbors(article_id)
    article['prev_id'] = prev_id
    article['next_id'] = next_id
    if next_id and next_id in _item_index:
        article['next_title'] = _item_index[next_id].get('title_pl', '')
        article['next_image'] = _item_index[next_id].get('image', '')
        article['next_category'] = _item_index[next_id].get('category_name', '')
        article['next_icon'] = _item_index[next_id].get('icon', '')
    # Auto-track view
    try:
        stats_tracker.track_view(
            article_id=article_id,
            title=item.get('title_pl', ''),
            category=item.get('category_name', ''),
            source=item.get('source', ''),
            icon=item.get('icon', ''),
            image=item.get('image', ''),
        )
    except Exception as e:
        log.warning(f'track_view failed: {e}')

    return jsonify(article)


@app.route('/a/<article_id>')
def article_page(article_id):
    """Standalone shareable page for a single rewritten article (with OG meta)."""
    item = _item_index.get(article_id)
    if not item:
        # Repopulate from cache
        theme, _ = get_today_theme()
        results = fetcher.fetch_categories_parallel(theme['categories'])
        payload = {}
        for cat in theme['categories']:
            payload[cat] = {'items': [it.to_dict() for it in results.get(cat, [])]}
        _index_items(payload)
        item = _item_index.get(article_id)

    if not item:
        return render_template('article.html', article=None, title='Artykuł nieznaleziony',
                               description='', image='', source_url='#', source_name=''), 404

    article = rewriter.get_article(
        article_id=article_id,
        url=item['url'],
        fallback_title=item.get('title_en') or item.get('title_pl', ''),
        fallback_summary=item.get('summary_en') or item.get('summary_pl', ''),
        source=item.get('source', ''),
    )
    md = article.get('content_md', '')
    # Extract title (first H1) and a short description for OG
    title_pl = item.get('title_pl', '')
    desc = ''
    for line in md.split('\n'):
        line = line.strip()
        if line and not line.startswith('#') and len(line) > 30:
            desc = line[:200]
            break
    if not desc:
        desc = item.get('summary_pl', '') or 'Artykuł z The Ones AI Feed'

    prev_id, next_id = _get_neighbors(article_id)
    next_item = _item_index.get(next_id) if next_id else None

    return render_template(
        'article.html',
        article=article,
        item=item,
        content_md=md,
        title=title_pl,
        description=desc,
        image=item.get('image', ''),
        source_url=item.get('url', '#'),
        source_name=item.get('source', ''),
        category_name=item.get('category_name', ''),
        icon=item.get('icon', ''),
        prev_id=prev_id,
        next_id=next_id,
        next_item=next_item,
    )


@app.route('/api/theme')
def api_theme():
    theme, weekday = get_today_theme()
    return jsonify({
        'weekday': weekday,
        'theme': theme,
        'all_themes': DAILY_THEMES,
    })


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'feed-theones'})


# ============================================================
# STATS — tracking endpoints
# ============================================================
@app.route('/api/track/share', methods=['POST'])
def api_track_share():
    data = request.get_json(silent=True) or {}
    aid = data.get('article_id', '')
    platform = data.get('platform', '')
    stats_tracker.track_share(article_id=aid, platform=platform)
    return jsonify({'ok': True})


@app.route('/api/track/install', methods=['POST'])
def api_track_install():
    stats_tracker.track_install()
    return jsonify({'ok': True})


@app.route('/api/track/save', methods=['POST'])
def api_track_save():
    stats_tracker.track_save()
    return jsonify({'ok': True})


@app.route('/api/stats')
def api_stats():
    """Aggregated stats summary as JSON."""
    return jsonify(stats_tracker.get_summary(top_n=10))


@app.route('/api/prerewriter/stats')
def api_prerewriter_stats():
    """Background pre-rewriter status."""
    return jsonify(prerewriter.stats())


@app.route('/stats')
def stats_page():
    """Stats dashboard page."""
    return render_template('stats.html')


# ============================================================
# PWA — manifest, service worker, offline page
# ============================================================
@app.route('/manifest.json')
def pwa_manifest():
    """Serve manifest.json from root scope."""
    response = send_from_directory(STATIC_DIR, 'manifest.json')
    response.headers['Content-Type'] = 'application/manifest+json; charset=utf-8'
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response


@app.route('/sw.js')
def pwa_service_worker():
    """Serve service worker from root scope so it can control entire site."""
    response = send_from_directory(STATIC_DIR, 'sw.js')
    response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


@app.route('/offline.html')
def pwa_offline():
    """Offline fallback page for service worker."""
    return render_template('offline.html')

# ============================================================
# COMMENTS — self-hosted comments
# ============================================================
@app.route('/api/comments/<article_id>', methods=['GET'])
def api_get_comments(article_id):
    items = comments_store.get_comments(article_id)
    items.sort(key=lambda c: c.get('timestamp', 0), reverse=True)
    return jsonify({
        'article_id': article_id,
        'count': len(items),
        'comments': items,
    })


@app.route('/api/comments/<article_id>', methods=['POST'])
def api_add_comment(article_id):
    data = request.get_json(silent=True) or {}
    author = (data.get('author') or '').strip()
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'empty text'}), 400
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or '')
    ip = ip.split(',')[0].strip()
    comment = comments_store.add_comment(article_id, author, text, ip)
    if not comment:
        return jsonify({'error': 'rejected (spam, rate limit, or too short)'}), 429
    return jsonify({'ok': True, 'comment': comment})


@app.route('/api/comments/counts', methods=['POST'])
def api_comments_counts():
    """Bulk fetch comment counts for a list of article ids."""
    data = request.get_json(silent=True) or {}
    ids = data.get('ids', [])
    if not isinstance(ids, list):
        return jsonify({}), 400
    return jsonify(comments_store.get_counts_bulk(ids))


# ============================================================
# PUSH NOTIFICATIONS — Web Push via VAPID
# ============================================================
@app.route('/api/push/vapid-public-key')
def api_push_vapid_key():
    return jsonify({'publicKey': push_manager.public_key()})


@app.route('/api/push/subscribe', methods=['POST'])
def api_push_subscribe():
    sub = request.get_json(silent=True) or {}
    if not sub.get('endpoint'):
        return jsonify({'error': 'invalid subscription'}), 400
    sid = push_manager.add_subscription(sub)
    return jsonify({'ok': True, 'id': sid, 'subscribers': push_manager.subscription_count()})


@app.route('/api/push/unsubscribe', methods=['POST'])
def api_push_unsubscribe():
    data = request.get_json(silent=True) or {}
    sid = data.get('id', '')
    ok = push_manager.remove_subscription(sid)
    return jsonify({'ok': ok, 'subscribers': push_manager.subscription_count()})


@app.route('/api/push/test', methods=['POST'])
def api_push_test():
    """Send a test notification to all subscribers."""
    result = push_manager.send_notification(
        title='🌙 Test z The Ones AI Feed',
        body='Powiadomienia działają! Codziennie o 9:00 dostaniesz najnowsze newsy z branży beauty.',
        url='/',
    )
    return jsonify(result)


@app.route('/api/push/send-daily', methods=['POST'])
def api_push_send_daily():
    """Manually trigger the daily push notification (admin/cron endpoint)."""
    result = _send_daily_push()
    return jsonify(result)


def _send_daily_push():
    """Build & send the daily theme push notification."""
    theme, _ = get_today_theme()
    title = '🌙 The Ones AI Feed — ' + theme.get('title', 'Nowe newsy')
    body = theme.get('subtitle', 'Sprawdź najnowsze newsy ze świata piękna') + ' ✨'
    return push_manager.send_notification(title=title, body=body, url='/')


# Start the daily push scheduler at first request (lazy)
_scheduler_started = False
@app.before_request
def _start_scheduler_once():
    global _scheduler_started
    if not _scheduler_started:
        _scheduler_started = True
        push_manager.start_daily_scheduler(_send_daily_push, hour=9, minute=0)





@app.route('/pl/')
@app.route('/pl')
def index_pl():
    theme, weekday = get_today_theme()
    today_label = datetime.datetime.now().strftime('%d.%m.%Y')
    return render_template(
        'index_pl.html',
        theme=theme,
        weekday=weekday,
        today_label=today_label,
        all_categories=CATEGORIES,
        all_themes=DAILY_THEMES,
    )

@app.route('/sitemap.xml')
def sitemap():
    from flask import Response
    base = 'https://feed.theones.io'
    urls = [
        (base + '/', '1.0', 'hourly'),
        (base + '/pl/', '1.0', 'hourly'),
        (base + '/?cat=neurodiversity', '0.9', 'daily'),
        (base + '/?cat=adhd_dev', '0.9', 'daily'),
        (base + '/?cat=models', '0.8', 'daily'),
        (base + '/?cat=research', '0.8', 'daily'),
        (base + '/?cat=open_source', '0.8', 'daily'),
        (base + '/?cat=cloud', '0.7', 'daily'),
        (base + '/?cat=business', '0.7', 'daily'),
        (base + '/?cat=news', '0.7', 'daily'),
        (base + '/?cat=community', '0.6', 'daily'),
        (base + '/stats', '0.3', 'weekly'),
    ]
    cache_dir = os.path.join(BASE_DIR, 'cache', 'articles')
    if os.path.isdir(cache_dir):
        for fn in sorted(os.listdir(cache_dir))[:200]:
            if fn.endswith('.json'):
                aid = fn[:-5]
                urls.append((base + '/a/' + aid, '0.6', 'weekly'))
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u, prio, freq in urls:
        parts.append('<url><loc>' + u + '</loc><priority>' + prio + '</priority><changefreq>' + freq + '</changefreq></url>')
    parts.append('</urlset>')
    return Response(chr(10).join(parts), mimetype='application/xml')


@app.route('/robots.txt')
def robots():
    from flask import Response
    nl = chr(10)
    body = 'User-agent: *' + nl + 'Allow: /' + nl + 'Disallow: /api/' + nl + 'Disallow: /stats' + nl + nl + 'Sitemap: https://feed.theones.io/sitemap.xml' + nl
    return Response(body, mimetype='text/plain')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
