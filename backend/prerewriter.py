"""
The Ones AI Feed - Background Pre-Rewriter
After news are fetched, this module spawns background threads to rewrite
articles in advance, so when a user clicks 'Czytaj więcej' the article
is already prepared and opens instantly.
"""
import os
import time
import logging
import threading
import concurrent.futures
from typing import List, Dict, Optional

log = logging.getLogger('feed.prerewriter')


class PreRewriter:
    """Background worker that pre-rewrites articles using the ArticleRewriter.
    Maintains a queue of pending articles and processes them in parallel
    workers, skipping anything already cached on disk.
    """

    def __init__(self, rewriter, max_workers: int = 2, max_per_run: int = 30):
        """
        :param rewriter: ArticleRewriter instance
        :param max_workers: parallel LLM calls (keep low to respect rate limits)
        :param max_per_run: hard cap on items processed per enqueue cycle
        """
        self.rewriter = rewriter
        self.max_workers = max_workers
        self.max_per_run = max_per_run
        self._lock = threading.Lock()
        self._processed_ids = set()  # in-memory record of what we've enqueued
        self._stats = {
            'queued': 0,
            'completed': 0,
            'failed': 0,
            'skipped_cached': 0,
            'last_run_started': None,
            'last_run_ended': None,
            'in_progress': 0,
        }
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix='feed-prerw')

    # ----------------------------------------------------------------------
    def stats(self) -> Dict:
        with self._lock:
            return dict(self._stats)

    # ----------------------------------------------------------------------
    def _is_cached(self, article_id: str) -> bool:
        """Check if article rewrite is already cached on disk."""
        return os.path.exists(self.rewriter._cache_path(article_id))

    # ----------------------------------------------------------------------
    def _rewrite_one(self, item: Dict) -> bool:
        """Rewrite a single item. Returns True on success."""
        article_id = item.get('id')
        if not article_id:
            return False
        try:
            with self._lock:
                self._stats['in_progress'] += 1
            self.rewriter.get_article(
                article_id=article_id,
                url=item.get('url', ''),
                fallback_title=item.get('title_en') or item.get('title_pl', ''),
                fallback_summary=item.get('summary_en') or item.get('summary_pl', ''),
                source=item.get('source', ''),
            )
            with self._lock:
                self._stats['completed'] += 1
                self._stats['in_progress'] -= 1
            log.info(f'pre-rewrite OK | {article_id} | {(item.get("title_en") or item.get("title_pl",""))[:60]}')
            return True
        except Exception as e:
            with self._lock:
                self._stats['failed'] += 1
                self._stats['in_progress'] -= 1
            log.warning(f'pre-rewrite FAIL | {article_id} | {e}')
            return False

    # ----------------------------------------------------------------------
    def enqueue_items(self, items: List[Dict]) -> int:
        """Enqueue a list of news items for background rewriting.
        Skips items already cached on disk or already enqueued in this run.
        Returns the number of items actually enqueued.
        """
        if not items:
            return 0

        to_process = []
        with self._lock:
            for item in items:
                aid = item.get('id')
                if not aid:
                    continue
                if aid in self._processed_ids:
                    continue
                if self._is_cached(aid):
                    self._processed_ids.add(aid)
                    self._stats['skipped_cached'] += 1
                    continue
                self._processed_ids.add(aid)
                to_process.append(item)
                if len(to_process) >= self.max_per_run:
                    break
            self._stats['queued'] += len(to_process)
            if to_process:
                self._stats['last_run_started'] = time.time()

        if not to_process:
            return 0

        log.info(f'enqueueing {len(to_process)} items for pre-rewrite (workers={self.max_workers})')

        # Submit to thread pool — fire and forget; results tracked via _stats
        def _runner():
            for item in to_process:
                # Throttle: tiny delay between submissions to avoid hammering the LLM
                time.sleep(0.2)
                self._executor.submit(self._rewrite_one, item)
            with self._lock:
                self._stats['last_run_ended'] = time.time()

        threading.Thread(target=_runner, daemon=True, name='feed-prerw-dispatch').start()
        return len(to_process)

    # ----------------------------------------------------------------------
    def shutdown(self):
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass
