"""
The Ones AI Feed - Push Notifications Module
Web Push notifications via VAPID. Stores subscriptions in JSON,
sends notifications to all subscribers.
"""
import os
import json
import time
import threading
import logging
import datetime
from typing import Dict, List, Optional
from pywebpush import webpush, WebPushException
from py_vapid import Vapid
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
import base64

log = logging.getLogger('feed.push')


class PushManager:
    def __init__(self, storage_path: str, vapid_path: str, subject: str = 'mailto:feed@local'):
        self.storage_path = storage_path
        self.vapid_path = vapid_path
        self.subject = subject
        os.makedirs(os.path.dirname(storage_path), exist_ok=True)
        os.makedirs(os.path.dirname(vapid_path), exist_ok=True)
        self._lock = threading.RLock()
        self._subs = self._load_subs()
        self._vapid_private_pem, self._vapid_public_b64 = self._init_vapid()
        self._scheduler_started = False

    # ----------------------------------------------------------------------
    def _load_subs(self) -> Dict[str, Dict]:
        if not os.path.exists(self.storage_path):
            return {}
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log.warning(f'failed to load subs: {e}')
            return {}

    def _save_subs(self):
        try:
            tmp = self.storage_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._subs, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.storage_path)
        except Exception as e:
            log.warning(f'subs save failed: {e}')

    # ----------------------------------------------------------------------
    def _init_vapid(self):
        """Generate or load VAPID keypair. Returns (private_pem, public_b64)."""
        priv_path = self.vapid_path
        pub_path = self.vapid_path + '.public'

        if os.path.exists(priv_path) and os.path.exists(pub_path):
            with open(priv_path, 'rb') as f:
                private_pem = f.read()
            with open(pub_path, 'r') as f:
                public_b64 = f.read().strip()
            log.info(f'loaded VAPID keys (public: {public_b64[:30]}...)')
            return private_pem, public_b64

        # Generate new keys
        log.info('generating new VAPID keypair')
        private_key = ec.generate_private_key(ec.SECP256R1())
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_key = private_key.public_key()
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        public_b64 = base64.urlsafe_b64encode(public_bytes).decode('ascii').rstrip('=')

        with open(priv_path, 'wb') as f:
            f.write(private_pem)
        with open(pub_path, 'w') as f:
            f.write(public_b64)
        log.info(f'saved new VAPID keys to {priv_path}')
        return private_pem, public_b64

    def public_key(self) -> str:
        return self._vapid_public_b64

    # ----------------------------------------------------------------------
    def add_subscription(self, sub: Dict) -> str:
        """Store a push subscription. Returns subscription id."""
        endpoint = sub.get('endpoint', '')
        if not endpoint:
            return ''
        # Use endpoint hash as ID to dedupe
        import hashlib
        sid = hashlib.md5(endpoint.encode()).hexdigest()[:16]
        with self._lock:
            self._subs[sid] = {
                'subscription': sub,
                'created_at': time.time(),
                'last_sent': None,
            }
            self._save_subs()
        log.info(f'subscription added: {sid}')
        return sid

    def remove_subscription(self, sid: str) -> bool:
        with self._lock:
            if sid in self._subs:
                del self._subs[sid]
                self._save_subs()
                return True
            return False

    def subscription_count(self) -> int:
        with self._lock:
            return len(self._subs)

    # ----------------------------------------------------------------------
    def send_notification(self, title: str, body: str, url: str = '/',
                          icon: str = '/static/img/icon-192.png',
                          badge: str = '/static/img/icon-192.png',
                          image: str = '') -> Dict:
        """Send notification to all subscribers. Returns {sent, failed} stats."""
        payload = json.dumps({
            'title': title,
            'body': body,
            'icon': icon,
            'badge': badge,
            'image': image,
            'url': url,
            'tag': 'feed-theones',
            'renotify': True,
        })
        sent = 0
        failed = 0
        to_remove = []

        with self._lock:
            subs_copy = dict(self._subs)

        for sid, data in subs_copy.items():
            sub = data.get('subscription', {})
            try:
                webpush(
                    subscription_info=sub,
                    data=payload,
                    vapid_private_key=self._vapid_private_pem.decode(),
                    vapid_claims={'sub': self.subject},
                )
                sent += 1
                with self._lock:
                    if sid in self._subs:
                        self._subs[sid]['last_sent'] = time.time()
            except WebPushException as e:
                failed += 1
                # 410 Gone = subscription expired, remove it
                if e.response and e.response.status_code == 410:
                    to_remove.append(sid)
                log.warning(f'push failed for {sid}: {e}')
            except Exception as e:
                failed += 1
                log.warning(f'push failed for {sid}: {e}')

        if to_remove:
            with self._lock:
                for sid in to_remove:
                    self._subs.pop(sid, None)
                self._save_subs()
            log.info(f'removed {len(to_remove)} expired subscriptions')

        with self._lock:
            self._save_subs()

        log.info(f'push complete: sent={sent} failed={failed}')
        return {'sent': sent, 'failed': failed, 'expired_removed': len(to_remove)}

    # ----------------------------------------------------------------------
    def start_daily_scheduler(self, send_callback, hour: int = 9, minute: int = 0):
        """Start a background thread that calls send_callback() daily at HH:MM.
        send_callback should be a no-arg function that builds & sends the notification.
        """
        if self._scheduler_started:
            return
        self._scheduler_started = True

        def _loop():
            log.info(f'daily push scheduler started — fires at {hour:02d}:{minute:02d}')
            last_sent_date = None
            while True:
                now = datetime.datetime.now()
                today_str = now.strftime('%Y-%m-%d')
                # Trigger if we're past the send time and haven't sent today
                if (last_sent_date != today_str
                        and (now.hour > hour
                             or (now.hour == hour and now.minute >= minute))):
                    try:
                        log.info(f'daily push triggered at {now}')
                        send_callback()
                        last_sent_date = today_str
                    except Exception as e:
                        log.error(f'daily send callback failed: {e}')
                time.sleep(60)

        threading.Thread(target=_loop, daemon=True, name='feed-push-scheduler').start()
