"""
The Ones AI Feed - Comments Module
Lightweight, self-hosted comments. JSON file storage, thread-safe,
basic spam protection (rate limiting, length limits, profanity filter).
"""
import os
import json
import time
import uuid
import hashlib
import threading
import logging
import re
from typing import Dict, List, Optional

log = logging.getLogger('feed.comments')

# Banned phrases (very simple spam filter)
SPAM_PATTERNS = [
    r'\b(viagra|casino|porn|crypto|bitcoin|escort)\b',
    r'(http[s]?://\S+){3,}',  # 3+ URLs
    r'(.)\1{15,}',             # 15+ same chars
]


class CommentsStore:
    def __init__(self, storage_path: str):
        self.storage_path = storage_path
        os.makedirs(os.path.dirname(storage_path), exist_ok=True)
        self._lock = threading.RLock()
        self._data = self._load()
        # ip_address -> list of (timestamp, comment_id) for rate limiting
        self._rate_limit = {}

    # ----------------------------------------------------------------------
    def _load(self) -> Dict:
        if not os.path.exists(self.storage_path):
            return {'comments': {}, 'created_at': time.time()}
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log.warning(f'failed to load comments, starting fresh: {e}')
            return {'comments': {}, 'created_at': time.time()}

    def _save(self):
        try:
            tmp = self.storage_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.storage_path)
        except Exception as e:
            log.warning(f'comments save failed: {e}')

    # ----------------------------------------------------------------------
    def _check_rate_limit(self, ip: str) -> bool:
        """Return True if user can post (within rate limits).
        Limit: max 5 comments per 5 minutes per IP.
        """
        now = time.time()
        history = self._rate_limit.get(ip, [])
        # Keep only last 5 minutes
        history = [t for t in history if now - t < 300]
        if len(history) >= 5:
            return False
        history.append(now)
        self._rate_limit[ip] = history
        return True

    def _is_spam(self, text: str) -> bool:
        text_lower = text.lower()
        for pattern in SPAM_PATTERNS:
            if re.search(pattern, text_lower):
                return True
        return False

    def _sanitize(self, text: str, max_len: int = 2000) -> str:
        """Strip HTML tags and limit length."""
        text = re.sub(r'<[^>]+>', '', text)
        text = text.strip()
        return text[:max_len]

    # ----------------------------------------------------------------------
    def add_comment(self, article_id: str, author: str, text: str,
                    ip: str = '') -> Optional[Dict]:
        """Add a new comment. Returns the created comment or None on failure."""
        if not article_id or not text:
            return None

        text = self._sanitize(text)
        if len(text) < 2:
            return None

        author = self._sanitize(author or 'Anonim', max_len=60)
        if not author:
            author = 'Anonim'

        if self._is_spam(text):
            log.warning(f'spam comment blocked from {ip}: {text[:50]}')
            return None

        with self._lock:
            if ip and not self._check_rate_limit(ip):
                log.warning(f'rate limit hit for {ip}')
                return None

            comment = {
                'id': uuid.uuid4().hex[:12],
                'article_id': article_id,
                'author': author,
                'text': text,
                'timestamp': time.time(),
                'avatar_seed': hashlib.md5(author.encode('utf-8')).hexdigest()[:8],
            }
            arts = self._data['comments'].setdefault(article_id, [])
            arts.append(comment)
            self._save()
            return comment

    # ----------------------------------------------------------------------
    def get_comments(self, article_id: str) -> List[Dict]:
        with self._lock:
            return list(self._data['comments'].get(article_id, []))

    def get_count(self, article_id: str) -> int:
        with self._lock:
            return len(self._data['comments'].get(article_id, []))

    def get_counts_bulk(self, article_ids: List[str]) -> Dict[str, int]:
        with self._lock:
            return {aid: len(self._data['comments'].get(aid, [])) for aid in article_ids}

    def delete_comment(self, comment_id: str) -> bool:
        """Admin function — delete a comment by id."""
        with self._lock:
            for aid, comments in self._data['comments'].items():
                for i, c in enumerate(comments):
                    if c.get('id') == comment_id:
                        comments.pop(i)
                        self._save()
                        return True
            return False

    def get_recent(self, limit: int = 20) -> List[Dict]:
        """Get most recent comments across all articles."""
        with self._lock:
            all_comments = []
            for aid, comments in self._data['comments'].items():
                for c in comments:
                    all_comments.append({**c, 'article_id': aid})
            all_comments.sort(key=lambda c: c.get('timestamp', 0), reverse=True)
            return all_comments[:limit]

    def total_count(self) -> int:
        with self._lock:
            return sum(len(c) for c in self._data['comments'].values())
