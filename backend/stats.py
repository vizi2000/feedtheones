"""
The Ones AI Feed - Statistics Tracker
Lightweight, persistent stats: article views, shares, category popularity.
Stores everything in a single JSON file with thread-safe updates.
"""
import os
import json
import time
import threading
import logging
from collections import defaultdict
from typing import Dict, List, Optional

log = logging.getLogger('feed.stats')


class StatsTracker:
    def __init__(self, storage_path: str):
        self.storage_path = storage_path
        os.makedirs(os.path.dirname(storage_path), exist_ok=True)
        self._lock = threading.RLock()
        self._data = self._load()
        self._last_save_ts = 0
        self._dirty = False
        # Periodically auto-flush to disk
        self._start_autoflush()

    # ----------------------------------------------------------------------
    def _load(self) -> Dict:
        if not os.path.exists(self.storage_path):
            return self._empty()
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # ensure all required keys exist
            base = self._empty()
            base.update(data)
            return base
        except Exception as e:
            log.warning(f'failed to load stats, starting fresh: {e}')
            return self._empty()

    def _empty(self) -> Dict:
        return {
            'created_at': time.time(),
            'total_views': 0,
            'total_shares': 0,
            'total_installs': 0,
            'total_saves': 0,
            'articles': {},      # id -> {views, shares, last_view, title, category}
            'categories': {},    # category_key -> view count
            'sources': {},       # source name -> view count
            'shares_by_platform': {},  # platform -> count
            'daily': {},         # YYYY-MM-DD -> {views, shares}
        }

    # ----------------------------------------------------------------------
    def _save(self):
        try:
            tmp = self.storage_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.storage_path)
            self._last_save_ts = time.time()
            self._dirty = False
        except Exception as e:
            log.warning(f'stats save failed: {e}')

    def _start_autoflush(self):
        def _loop():
            while True:
                time.sleep(15)
                with self._lock:
                    if self._dirty:
                        self._save()
        t = threading.Thread(target=_loop, daemon=True, name='feed-stats-flush')
        t.start()

    def flush(self):
        with self._lock:
            self._save()

    # ----------------------------------------------------------------------
    def _today(self) -> str:
        return time.strftime('%Y-%m-%d')

    # ----------------------------------------------------------------------
    def track_view(self, article_id: str, title: str = '', category: str = '',
                   source: str = '', icon: str = '', image: str = ''):
        """Record an article view."""
        if not article_id:
            return
        with self._lock:
            self._data['total_views'] += 1
            arts = self._data['articles']
            if article_id not in arts:
                arts[article_id] = {
                    'views': 0, 'shares': 0,
                    'first_view': time.time(),
                    'last_view': time.time(),
                    'title': title, 'category': category,
                    'source': source, 'icon': icon, 'image': image,
                }
            arts[article_id]['views'] += 1
            arts[article_id]['last_view'] = time.time()
            # Refresh metadata in case it was missing
            for k, v in (('title', title), ('category', category),
                          ('source', source), ('icon', icon), ('image', image)):
                if v and not arts[article_id].get(k):
                    arts[article_id][k] = v

            if category:
                self._data['categories'][category] = self._data['categories'].get(category, 0) + 1
            if source:
                self._data['sources'][source] = self._data['sources'].get(source, 0) + 1

            today = self._today()
            day = self._data['daily'].setdefault(today, {'views': 0, 'shares': 0})
            day['views'] += 1

            self._dirty = True

    # ----------------------------------------------------------------------
    def track_share(self, article_id: str, platform: str = ''):
        with self._lock:
            self._data['total_shares'] += 1
            if article_id and article_id in self._data['articles']:
                self._data['articles'][article_id]['shares'] = \
                    self._data['articles'][article_id].get('shares', 0) + 1
            if platform:
                self._data['shares_by_platform'][platform] = \
                    self._data['shares_by_platform'].get(platform, 0) + 1
            today = self._today()
            day = self._data['daily'].setdefault(today, {'views': 0, 'shares': 0})
            day['shares'] += 1
            self._dirty = True

    # ----------------------------------------------------------------------
    def track_install(self):
        with self._lock:
            self._data['total_installs'] += 1
            self._dirty = True

    def track_save(self):
        with self._lock:
            self._data['total_saves'] += 1
            self._dirty = True

    # ----------------------------------------------------------------------
    def get_summary(self, top_n: int = 10) -> Dict:
        """Return aggregated stats summary for display."""
        with self._lock:
            arts = self._data['articles']
            sorted_articles = sorted(
                arts.items(),
                key=lambda kv: (kv[1].get('views', 0), kv[1].get('shares', 0)),
                reverse=True,
            )
            top_articles = []
            for aid, data in sorted_articles[:top_n]:
                top_articles.append({
                    'id': aid,
                    'title': data.get('title', ''),
                    'category': data.get('category', ''),
                    'source': data.get('source', ''),
                    'icon': data.get('icon', ''),
                    'image': data.get('image', ''),
                    'views': data.get('views', 0),
                    'shares': data.get('shares', 0),
                    'last_view': data.get('last_view'),
                })

            top_categories = sorted(self._data['categories'].items(),
                                    key=lambda kv: kv[1], reverse=True)
            top_sources = sorted(self._data['sources'].items(),
                                 key=lambda kv: kv[1], reverse=True)[:top_n]
            top_platforms = sorted(self._data['shares_by_platform'].items(),
                                   key=lambda kv: kv[1], reverse=True)

            # Last 7 days timeline
            today_dt = time.strftime('%Y-%m-%d')
            timeline = []
            for i in range(6, -1, -1):
                day = time.strftime('%Y-%m-%d', time.localtime(time.time() - i * 86400))
                day_data = self._data['daily'].get(day, {'views': 0, 'shares': 0})
                timeline.append({
                    'date': day,
                    'label': time.strftime('%a %d.%m', time.localtime(time.time() - i * 86400)),
                    'views': day_data.get('views', 0),
                    'shares': day_data.get('shares', 0),
                })

            return {
                'total_views': self._data['total_views'],
                'total_shares': self._data['total_shares'],
                'total_installs': self._data['total_installs'],
                'total_saves': self._data['total_saves'],
                'unique_articles': len(arts),
                'top_articles': top_articles,
                'top_categories': [{'key': k, 'views': v} for k, v in top_categories],
                'top_sources': [{'name': k, 'views': v} for k, v in top_sources],
                'shares_by_platform': [{'platform': k, 'count': v} for k, v in top_platforms],
                'timeline_7d': timeline,
                'created_at': self._data['created_at'],
            }
