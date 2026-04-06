/* ============================================================
   The Ones AI Feed — Frontend Logic
   - Fetches news from backend API
   - Renders elegant card layouts
   - Handles social sharing
   ============================================================ */

(function () {
    'use strict';

    const API_NEWS = '/api/news';
    const $loading = document.getElementById('loading');
    const $container = document.getElementById('news-container');
    const $modal = document.getElementById('share-modal');
    const $shareTitle = document.getElementById('share-title');
    const $shareFeedback = document.getElementById('share-feedback');

    let currentShareData = null;

    // Global state for category filter and items list
    let currentFilter = 'today';   // 'today' | 'all' | category key
    let allItems = [];              // ordered flat list of all loaded items
    let allItemsById = {};         // quick lookup

    // ----------------------------------------------------------
    // FAVORITES (localStorage-based bookmarks)
    // ----------------------------------------------------------
    const FAV_KEY = 'feed-favorites-v1';

    function getFavorites() {
        try {
            const raw = localStorage.getItem(FAV_KEY);
            return raw ? JSON.parse(raw) : {};
        } catch (e) {
            return {};
        }
    }

    function saveFavorites(favs) {
        try {
            localStorage.setItem(FAV_KEY, JSON.stringify(favs));
        } catch (e) {
            console.warn('failed to save favorites', e);
        }
        updateFavBadge();
    }

    function isFavorite(id) {
        if (!id) return false;
        return !!getFavorites()[id];
    }

    function toggleFavorite(item) {
        const favs = getFavorites();
        const id = item.id;
        if (favs[id]) {
            delete favs[id];
            saveFavorites(favs);
            return false;
        } else {
            favs[id] = {
                id: id,
                title_pl: item.title_pl || item.title_en || '',
                summary_pl: item.summary_pl || '',
                image: item.image || '',
                source: item.source || '',
                category_name: item.category_name || '',
                category_key: item.category_key || item.category || '',
                icon: item.icon || '',
                url: item.url || '',
                published: item.published || '',
                saved_at: Date.now(),
            };
            saveFavorites(favs);
            // Track save event
            fetch('/api/track/save', { method: 'POST' }).catch(() => {});
            return true;
        }
    }

    function getFavoritesList() {
        const favs = getFavorites();
        return Object.values(favs).sort((a, b) => (b.saved_at || 0) - (a.saved_at || 0));
    }

    function updateFavBadge() {
        const $b = document.getElementById('fav-count');
        if ($b) {
            const count = Object.keys(getFavorites()).length;
            $b.textContent = count;
            $b.style.display = count > 0 ? 'inline-block' : 'none';
        }
    }

    function attachFavHandlers() {
        document.querySelectorAll('[data-fav-id]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const id = btn.dataset.favId;
                // Find item in allItems or articleCache
                const item = allItemsById[id] || (articleCache[id] && articleCache[id]) || { id };
                const isNowSaved = toggleFavorite(item);
                btn.classList.toggle('is-saved', isNowSaved);
                btn.textContent = isNowSaved ? '♥' : '♡';
                // If currently viewing 'saved' filter, re-render to remove unsaved
                if (currentFilter === 'saved' && !isNowSaved) {
                    renderSavedView();
                }
            });
        });
    }

    // ----------------------------------------------------------
    // UTILITIES
    // ----------------------------------------------------------
    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function formatRelativeTime(isoOrRfc) {
        if (!isoOrRfc) return '';
        try {
            const d = new Date(isoOrRfc);
            if (isNaN(d.getTime())) return '';
            const diffMs = Date.now() - d.getTime();
            const mins = Math.floor(diffMs / 60000);
            if (mins < 1) return 'just now';
            if (mins < 60) return `${mins} min ago`;
            const hours = Math.floor(mins / 60);
            if (hours < 24) return `${hours} godz. ago`;
            const days = Math.floor(hours / 24);
            if (days < 7) return `${days} dni ago`;
            return d.toLocaleDateString('pl-PL', { day: '2-digit', month: 'short' });
        } catch (e) {
            return '';
        }
    }

    // ----------------------------------------------------------
    // RENDERING
    // ----------------------------------------------------------
    function renderCard(item) {
        const title = escapeHtml(item.title_pl || item.title_en);
        const summary = escapeHtml(item.summary_pl || item.summary_en);
        const source = escapeHtml(item.source || '');
        const time = formatRelativeTime(item.published);
        const meta = [source, time].filter(Boolean).join(' · ');
        const image = item.image || '';
        const url = escapeHtml(item.url);
        const id = escapeHtml(item.id);

        const badges = [];
        if (item.is_fun) {
            badges.push('<span class="badge fun">😄 Fun read</span>');
        } else {
            badges.push('<span class="badge science">🔬 Research</span>');
        }

        const imgHtml = image
            ? `<img class="card-image" src="${escapeHtml(image)}" alt="${title}" loading="lazy" onerror="this.style.display='none'">`
            : '';

        const isSaved = isFavorite(item.id) ? 'is-saved' : '';
        const favIcon = isFavorite(item.id) ? '♥' : '♡';

        return `
            <article class="news-card" data-id="${id}">
                <div class="card-image-wrap">
                    ${imgHtml}
                    <div class="card-image-overlay"></div>
                    <div class="card-badges">${badges.join('')}</div>
                    <button class="card-fav-btn ${isSaved}" data-fav-id="${id}" title="Save">${favIcon}</button>
                </div>
                <div class="card-body">
                    <h3 class="card-title">${title}</h3>
                    <p class="card-summary">${summary || ''}</p>
                    <div class="card-meta">
                        <span class="card-source">${meta || '&nbsp;'}</span>
                    </div>
                    <div class="card-actions">
                        <button class="card-link" data-article-id="${id}" data-article-url="${url}">
                            Read more →
                        </button>
                        <button class="card-share-btn" data-share-trigger
                                data-article-id="${id}"
                                data-title="${title}"
                                title="Share">
                            ↗
                        </button>
                    </div>
                </div>
            </article>
        `;
    }

    function renderCategory(catKey, catData, idx) {
        const items = catData.items || [];
        const cardsHtml = items.length
            ? items.map(renderCard).join('')
            : '<p style="grid-column:1/-1;text-align:center;color:var(--c-text-mute);padding:40px 0;">No fresh news in this category. Check back soon ⚡</p>';

        return `
            <section class="category-section" style="animation-delay: ${idx * 0.1}s">
                <header class="category-header">
                    <span class="category-icon">${catData.icon}</span>
                    <h2 class="category-title">${escapeHtml(catData.name)}</h2>
                    <span class="category-count">${items.length} ${items.length === 1 ? 'news' : 'news'}</span>
                </header>
                <div class="news-grid">
                    ${cardsHtml}
                </div>
            </section>
        `;
    }

    function renderAll(payload) {
        const cats = payload.categories || {};
        const keys = Object.keys(cats);

        // Rebuild global allItems list (preserve insertion order across categories)
        allItems = [];
        allItemsById = {};
        for (const key of keys) {
            const items = (cats[key].items || []).map(it => ({
                ...it,
                category_key: key,
                category_name: cats[key].name,
                icon: cats[key].icon,
            }));
            for (const it of items) {
                allItems.push(it);
                allItemsById[it.id] = it;
            }
        }

        if (!keys.length) {
            $container.innerHTML = '<p style="text-align:center;color:var(--c-text-mute);padding:60px 0;">No news to display.</p>';
            return;
        }
        const html = keys.map((k, i) => renderCategory(k, cats[k], i)).join('');
        $container.innerHTML = html;
        attachShareHandlers();
        attachArticleHandlers();
        attachFavHandlers();
        // Update list panel if it's open
        if ($readerListPanel && $readerListPanel.classList.contains('is-open')) {
            renderListPanel();
        }
    }

    // ----------------------------------------------------------
    // FETCH
    // ----------------------------------------------------------
    async function loadNews(filter) {
        if (filter !== undefined) currentFilter = filter;

        // Special filter: 'saved' = show favorites from localStorage (no fetch)
        if (currentFilter === 'saved') {
            renderSavedView();
            window.scrollTo({ top: 0, behavior: 'smooth' });
            return;
        }

        try {
            $loading.style.display = 'block';
            $container.style.display = 'none';

            // Build query: 'today' = no param (default theme), 'all' = all 7 categories,
            // <key> = single category
            let url = API_NEWS;
            if (currentFilter === 'all') {
                url = API_NEWS + '?categories=massage,kobido,skincare,hair,nails,brow_lamination,permanent_makeup';
            } else if (currentFilter && currentFilter !== 'today') {
                url = API_NEWS + '?categories=' + encodeURIComponent(currentFilter);
            }

            const res = await fetch(url);
            if (!res.ok) throw new Error('Network error: ' + res.status);
            const data = await res.json();
            $loading.style.display = 'none';
            $container.style.display = 'flex';
            renderAll(data);
            // Scroll to top so user sees new content
            window.scrollTo({ top: 0, behavior: 'smooth' });
        } catch (err) {
            console.error('loadNews failed', err);
            $loading.style.display = 'block';
            $container.style.display = 'none';
            $loading.innerHTML = `
                <p style="color:var(--c-deep-rose);font-weight:500;">
                    Failed to fetch news. <button id="retry-btn" style="text-decoration:underline;color:var(--c-mauve);font-weight:600;">Try again</button>
                </p>`;
            const $retry = document.getElementById('retry-btn');
            if ($retry) $retry.addEventListener('click', () => loadNews(currentFilter));
        }
    }

    // ----------------------------------------------------------
    // SHARE MODAL
    // ----------------------------------------------------------
    function attachShareHandlers() {
        document.querySelectorAll('[data-share-trigger]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const title = btn.dataset.title || '';
                const articleId = btn.dataset.articleId || '';
                openShareForArticle(articleId, title);
            });
        });
    }

    /** Open the share modal for a given article ID, fetching content first if needed. */
    async function openShareForArticle(articleId, title) {
        const articleUrl = articleId ? (window.location.origin + '/a/' + articleId) : window.location.href;
        // Try to get full content for sharing (cached or fetched)
        let fullText = '';
        if (articleId) {
            try {
                if (articleCache[articleId] && articleCache[articleId].content_md) {
                    fullText = mdToPlain(articleCache[articleId].content_md);
                } else {
                    // Fetch in background — open modal immediately so user sees something
                    showFeedback('Fetching article content...');
                    const res = await fetch('/api/article/' + articleId);
                    if (res.ok) {
                        const data = await res.json();
                        articleCache[articleId] = data;
                        fullText = mdToPlain(data.content_md || '');
                        showFeedback('');
                    }
                }
            } catch (e) {
                console.warn('share content prefetch failed', e);
            }
        }
        openShareModal(title, articleUrl, fullText);
    }

    /** Strip markdown to plain text for sharing. */
    function mdToPlain(md) {
        return (md || '')
            .replace(/^#+\s*/gm, '')
            .replace(/\*\*([^*]+)\*\*/g, '$1')
            .replace(/\*([^*]+)\*/g, '$1')
            .replace(/^- /gm, '• ')
            .replace(/^&gt; /gm, '"');
    }

    function openShareModal(title, url, fullText) {
        currentShareData = { title, url, fullText: fullText || '' };
        $shareTitle.textContent = title;
        $shareFeedback.textContent = '';
        $modal.classList.add('is-open');
        $modal.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
    }

    function closeShareModal() {
        $modal.classList.remove('is-open');
        $modal.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
        currentShareData = null;
    }

    function buildShareUrl(platform, title, url, fullText) {
        const t = encodeURIComponent(title);
        const u = encodeURIComponent(url);
        // For platforms that support long text, send full body
        const fullBody = fullText
            ? title + '\n\n' + fullText + '\n\n— The Ones AI Feed\n' + url
            : title + '\n' + url;
        const fullEnc = encodeURIComponent(fullBody);

        switch (platform) {
            case 'facebook':
                // FB strips text params; relies on OG meta from article URL page
                return `https://www.facebook.com/sharer/sharer.php?u=${u}&quote=${t}`;
            case 'twitter': {
                // Twitter has 280 char limit — share excerpt + URL
                const excerpt = (title + ' — ' + (fullText || '').substring(0, 160) + '…').substring(0, 200);
                return `https://twitter.com/intent/tweet?text=${encodeURIComponent(excerpt)}&url=${u}&hashtags=AINews,TheOnes`;
            }
            case 'whatsapp':
                return `https://wa.me/?text=${fullEnc}`;
            case 'telegram':
                return `https://t.me/share/url?url=${u}&text=${fullEnc}`;
            case 'messenger':
                return `https://www.facebook.com/dialog/send?link=${u}&app_id=291494419107518&redirect_uri=${u}`;
            case 'linkedin':
                return `https://www.linkedin.com/sharing/share-offsite/?url=${u}`;
            default:
                return null;
        }
    }

    function showFeedback(msg) {
        $shareFeedback.textContent = msg;
        if (msg) {
            setTimeout(() => {
                if ($shareFeedback) $shareFeedback.textContent = '';
            }, 3500);
        }
    }

    function handleShareClick(e) {
        const target = e.target.closest('[data-share]');
        if (!target || !currentShareData) return;
        e.preventDefault();
        const platform = target.dataset.share;
        const { title, url, fullText } = currentShareData;

        // Track share event (extract article id from article URL if present)
        const idMatch = (url || '').match(/\/a\/([a-f0-9]+)/);
        const trackId = idMatch ? idMatch[1] : '';
        fetch('/api/track/share', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ article_id: trackId, platform: platform })
        }).catch(() => {});

        if (platform === 'copy') {
            // Copy = full article text + article URL
            const textToCopy = fullText
                ? title + '\n\n' + fullText + '\n\n— The Ones AI Feed\n' + url
                : title + ' — ' + url;
            copyToClipboard(textToCopy)
                .then(() => showFeedback('✓ Full article copied to clipboard!'))
                .catch(() => showFeedback('Copy failed'));
            return;
        }

        if (platform === 'native') {
            if (navigator.share) {
                navigator.share({
                    title: 'The Ones AI Feed',
                    text: fullText ? title + '\n\n' + fullText : title,
                    url: url,
                }).catch(() => {});
            } else {
                showFeedback('Your browser doesn't support sharing');
            }
            return;
        }

        const shareUrl = buildShareUrl(platform, title, url, fullText);
        if (shareUrl) {
            window.open(shareUrl, '_blank', 'noopener,noreferrer,width=640,height=560');
        }
    }

    function copyToClipboard(text) {
        if (navigator.clipboard) {
            return navigator.clipboard.writeText(text);
        }
        return new Promise((resolve, reject) => {
            const ta = document.createElement('textarea');
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            try {
                document.execCommand('copy');
                resolve();
            } catch (err) {
                reject(err);
            }
            document.body.removeChild(ta);
        });
    }

    // ----------------------------------------------------------
    // ARTICLE MODAL — opens long-form rewritten Polish article
    // ----------------------------------------------------------
    const $articleModal = document.getElementById('article-modal');
    const $articleLoading = document.getElementById('article-loading');
    const $articleContent = document.getElementById('article-content');
    const $articleError = document.getElementById('article-error');
    const $articleImage = document.getElementById('article-image');
    const $articleCategory = document.getElementById('article-category');
    const $articleBody = document.getElementById('article-body');
    const $articleSaturceLink = document.getElementById('article-source-link');
    const $articleSaturceName = document.getElementById('article-source-name');
    const $articleErrorLink = document.getElementById('article-error-link');
    const $articleShareBtn = document.getElementById('article-share-btn');

    let currentArticle = null;
    const articleCache = {};

    /** Tiny markdown -> HTML converter (handles common syntax we use) */
    function renderMarkdown(md) {
        if (!md) return '';
        // Pre-process images BEFORE escaping (escape them to placeholders)
        const imgPlaceholders = [];
        let processed = md.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (m, alt, url) => {
            const idx = imgPlaceholders.length;
            imgPlaceholders.push({ alt, url });
            return `\u0001IMG${idx}\u0002`;
        });
        let html = escapeHtml(processed);
        // Headers (do them in order so longer matches first)
        html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
        html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
        html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
        // Bold and italic
        html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, '<em>$1</em>');
        // Blockquotes
        html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
        // Lists (simple)
        html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
        html = html.replace(/(<li>.*<\/li>\n?)+/g, m => '<ul>' + m + '</ul>');
        // Restore image placeholders → <figure><img></figure>
        html = html.replace(/\u0001IMG(\d+)\u0002/g, (m, idx) => {
            const img = imgPlaceholders[parseInt(idx, 10)];
            if (!img) return '';
            const alt = escapeHtml(img.alt || '');
            const url = escapeHtml(img.url);
            return `<figure class="article-figure"><img src="${url}" alt="${alt}" loading="lazy" onerror="this.parentNode.style.display='none'">${alt ? `<figcaption>${alt}</figcaption>` : ''}</figure>`;
        });
        // Paragraphs: split on blank lines, wrap non-block content
        const blocks = html.split(/\n{2,}/).map(b => {
            const trimmed = b.trim();
            if (!trimmed) return '';
            if (/^<(h[1-6]|ul|ol|blockquote|li|p|figure)/.test(trimmed)) return trimmed;
            return '<p>' + trimmed.replace(/\n/g, '<br>') + '</p>';
        });
        return blocks.join('\n');
    }

    function attachArticleHandlers() {
        document.querySelectorAll('[data-article-id]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const id = btn.dataset.articleId;
                const url = btn.dataset.articleUrl;
                openArticleModal(id, url);
            });
        });
    }

    function openArticleModal(id, fallbackUrl) {
        $articleModal.classList.add('is-open');
        $articleModal.setAttribute('aria-hidden', 'false');
        document.body.classList.add('article-modal-open');
        document.body.style.overflow = 'hidden';
        $articleLoading.style.display = 'block';
        $articleContent.style.display = 'none';
        $articleError.style.display = 'none';
        $articleErrorLink.href = fallbackUrl || '#';
        // Cached?
        if (articleCache[id]) {
            renderArticleInModal(articleCache[id]);
            return;
        }
        fetchArticle(id, fallbackUrl);
    }

    function closeArticleModal() {
        $articleModal.classList.remove('is-open');
        $articleModal.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('article-modal-open');
        document.body.style.overflow = '';
        currentArticle = null;
    }

    async function fetchArticle(id, fallbackUrl) {
        try {
            const res = await fetch(`/api/article/${id}`);
            if (!res.ok) {
                throw new Error('http ' + res.status);
            }
            const data = await res.json();
            articleCache[id] = data;
            renderArticleInModal(data);
        } catch (err) {
            console.error('fetchArticle failed', err);
            $articleLoading.style.display = 'none';
            $articleContent.style.display = 'none';
            $articleError.style.display = 'block';
            $articleErrorLink.href = fallbackUrl || '#';
        }
    }

    function renderArticleInModal(data) {
        currentArticle = data;
        // Hero image
        if (data.image) {
            $articleImage.src = data.image;
            $articleImage.alt = data.title_pl || '';
            $articleImage.style.display = 'block';
        } else {
            $articleImage.style.display = 'none';
        }
        // Category badge
        const catText = `${data.icon || ''} ${data.category_name || ''}`.trim();
        $articleCategory.textContent = catText;
        $articleCategory.style.display = catText ? 'inline-flex' : 'none';

        // Body (rendered markdown)
        $articleBody.innerHTML = renderMarkdown(data.content_md || '');

        // Saturce link
        $articleSaturceName.textContent = data.source || 'Original source';
        $articleSaturceLink.href = data.url || '#';
        // Next article card (inject after source footer)
        renderNextArticleInModal(data);

        // Add favorite button next to share button in article actions
        injectFavButtonInModal(data);

        $articleLoading.style.display = 'none';
        $articleError.style.display = 'none';
        $articleContent.style.display = 'block';
        // Update bottom reader nav (prev/next buttons)
        updateReaderNavButtons();
        // Scroll modal to top
        $articleModal.scrollTop = 0;
    }

    function renderNextArticleInModal(data) {
        // Remove any existing next-article card from previous render
        const existing = document.querySelector('#article-content .next-article-card');
        if (existing) existing.remove();

        if (!data.next_id) return;

        const img = data.next_image
            ? `<div class="next-article-image"><img src="${escapeHtml(data.next_image)}" alt="" loading="lazy"></div>`
            : '';
        const cat = data.next_category
            ? `<span class="next-article-category">${escapeHtml(data.next_icon || '')} ${escapeHtml(data.next_category)}</span>`
            : '';
        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'next-article-card';
        card.setAttribute('data-next-id', data.next_id);
        card.innerHTML = `
            <div class="next-article-label">→ Next article</div>
            <div class="next-article-inner">
                ${img}
                <div class="next-article-text">
                    ${cat}
                    <h3 class="next-article-title">${escapeHtml(data.next_title || '')}</h3>
                    <span class="next-article-cta">Thuytaj dalej →</span>
                </div>
            </div>
        `;
        card.addEventListener('click', (e) => {
            e.preventDefault();
            // Re-open modal with next article
            openArticleModal(data.next_id, '');
            // Scroll modal back to top
            $articleModal.scrollTop = 0;
        });
        // Insert after the source footer (which is the last element in article-content's structure)
        const footer = document.querySelector('#article-content .article-source-footer');
        if (footer && footer.parentNode) {
            footer.parentNode.insertBefore(card, footer.nextSibling);
        } else {
            $articleContent.appendChild(card);
        }
    }

    function injectFavButtonInModal(data) {
        // Find the article actions container in the modal
        const actions = document.querySelector('#article-content .article-actions');
        if (!actions) return;
        // Remove any existing fav btn from previous render
        const existing = actions.querySelector('.article-fav-btn');
        if (existing) existing.remove();
        const isSaved = isFavorite(data.id);
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'article-fav-btn' + (isSaved ? ' is-saved' : '');
        btn.innerHTML = isSaved ? '♥ Saved' : '♡ Save for later';
        btn.addEventListener('click', () => {
            const item = {
                id: data.id,
                title_pl: data.title_pl,
                summary_pl: '',
                image: data.image,
                source: data.source,
                category_name: data.category_name,
                icon: data.icon,
                url: data.url,
                published: data.published,
            };
            const nowSaved = toggleFavorite(item);
            btn.classList.toggle('is-saved', nowSaved);
            btn.innerHTML = nowSaved ? '♥ Saved' : '♡ Save for later';
            // Also update card fav button if visible on the page
            document.querySelectorAll(`[data-fav-id="${data.id}"]`).forEach(b => {
                b.classList.toggle('is-saved', nowSaved);
                if (b.classList.contains('card-fav-btn')) {
                    b.textContent = nowSaved ? '♥' : '♡';
                }
            });
        });
        // Insert before the share button
        actions.insertBefore(btn, actions.firstChild);
    }

    function renderSavedView() {
        $loading.style.display = 'none';
        $container.style.display = 'flex';
        const items = getFavoritesList();
        // Update allItems so reader-list-panel and prev/next work
        allItems = items.map(it => ({ ...it, category_key: it.category_key || it.category_name }));
        allItemsById = {};
        items.forEach(it => { allItemsById[it.id] = it; });

        if (!items.length) {
            $container.innerHTML = `
                <div style="text-align:center; padding:80px 20px; color:var(--c-text-soft);">
                    <div style="font-size:80px; margin-bottom:20px;">💖</div>
                    <h2 style="font-family:var(--f-serif); font-size:28px; margin-bottom:12px; color:var(--c-text);">No saved articles</h2>
                    <p style="font-family:var(--f-serif); font-style:italic; font-size:18px;">Click ♡ on articles to save them for later</p>
                </div>`;
            return;
        }
        // Render as a single 'category section'
        const cardsHtml = items.map(it => renderCard({
            ...it,
            title_en: '',
            summary_en: it.summary_pl || '',
            is_fun: false,
        })).join('');
        $container.innerHTML = `
            <section class="category-section">
                <header class="category-header">
                    <span class="category-icon">💖</span>
                    <h2 class="category-title">Saved articles</h2>
                    <span class="category-count">${items.length} ${items.length === 1 ? 'article' : 'articles'}</span>
                </header>
                <div class="news-grid">${cardsHtml}</div>
            </section>`;
        attachShareHandlers();
        attachArticleHandlers();
        attachFavHandlers();
    }


    function shareCurrentArticle() {
        if (!currentArticle) return;
        const title = currentArticle.title_pl || 'The Ones AI Feed';
        const articleUrl = window.location.origin + '/a/' + currentArticle.id;
        const fullText = mdToPlain(currentArticle.content_md || '');
        openShareModal(title, articleUrl, fullText);
    }

    // ----------------------------------------------------------
    // CATEGORY NAVIGATION (header pills) + READER NAV (bottom)
    // ----------------------------------------------------------
    const $categoryNav = document.getElementById('category-nav');
    const $readerNav = document.getElementById('reader-nav');
    const $readerPrevBtn = document.getElementById('reader-prev-btn');
    const $readerNextBtn = document.getElementById('reader-next-btn');
    const $readerListBtn = document.getElementById('reader-list-btn');
    const $readerListPanel = document.getElementById('reader-list-panel');
    const $readerListClose = document.getElementById('reader-list-close');
    const $readerListItems = document.getElementById('reader-list-items');
    const $readerListTabs = document.getElementById('reader-list-tabs');

    let listPanelFilter = 'all';
    let listBackdrop = null;

    function attachCategoryNavHandlers() {
        if (!$categoryNav) return;
        $categoryNav.querySelectorAll('.cat-pill').forEach(btn => {
            btn.addEventListener('click', () => {
                const cat = btn.dataset.cat;
                $categoryNav.querySelectorAll('.cat-pill').forEach(b => b.classList.remove('is-active'));
                btn.classList.add('is-active');
                loadNews(cat);
            });
        });
    }

    function updateReaderNavButtons() {
        if (!currentArticle) return;
        const prevId = currentArticle.prev_id;
        const nextId = currentArticle.next_id;
        $readerPrevBtn.disabled = !prevId;
        $readerNextBtn.disabled = !nextId;
        $readerPrevBtn.dataset.targetId = prevId || '';
        $readerNextBtn.dataset.targetId = nextId || '';
    }

    function attachReaderNavHandlers() {
        if ($readerPrevBtn) {
            $readerPrevBtn.addEventListener('click', () => {
                const target = $readerPrevBtn.dataset.targetId;
                if (target) openArticleModal(target, '');
            });
        }
        if ($readerNextBtn) {
            $readerNextBtn.addEventListener('click', () => {
                const target = $readerNextBtn.dataset.targetId;
                if (target) openArticleModal(target, '');
            });
        }
        if ($readerListBtn) {
            $readerListBtn.addEventListener('click', openListPanel);
        }
    }

    // ----------------------------------------------------------
    // ARTICLE LIST PANEL
    // ----------------------------------------------------------
    function ensureBackdrop() {
        if (!listBackdrop) {
            listBackdrop = document.createElement('div');
            listBackdrop.className = 'reader-list-backdrop';
            listBackdrop.addEventListener('click', closeListPanel);
            document.body.appendChild(listBackdrop);
        }
        return listBackdrop;
    }

    function openListPanel() {
        ensureBackdrop().classList.add('is-open');
        $readerListPanel.classList.add('is-open');
        $readerListPanel.setAttribute('aria-hidden', 'false');
        renderListPanel();
    }

    function closeListPanel() {
        if (listBackdrop) listBackdrop.classList.remove('is-open');
        $readerListPanel.classList.remove('is-open');
        $readerListPanel.setAttribute('aria-hidden', 'true');
    }

    function renderListPanel() {
        if (!$readerListItems) return;
        const items = listPanelFilter === 'all'
            ? allItems
            : allItems.filter(it => it.category_key === listPanelFilter || it.category === listPanelFilter);
        if (!items.length) {
            $readerListItems.innerHTML = '<p style="text-align:center;color:var(--c-text-mute);padding:40px 0;">Brak articles w tej kategorii</p>';
            return;
        }
        const currentId = currentArticle ? currentArticle.id : null;
        $readerListItems.innerHTML = items.map(it => {
            const isCurrent = it.id === currentId ? 'is-current' : '';
            const img = it.image
                ? `<div class="reader-list-item-img"><img src="${escapeHtml(it.image)}" alt="" loading="lazy" onerror="this.parentNode.style.display='none'"></div>`
                : '';
            return `
                <button class="reader-list-item ${isCurrent}" data-jump-id="${escapeHtml(it.id)}">
                    ${img}
                    <div class="reader-list-item-text">
                        <div class="reader-list-item-cat">${escapeHtml((it.icon || '') + ' ' + (it.category_name || it.category || ''))}</div>
                        <div class="reader-list-item-title">${escapeHtml(it.title_pl || it.title_en || '')}</div>
                    </div>
                </button>
            `;
        }).join('');
        $readerListItems.querySelectorAll('[data-jump-id]').forEach(btn => {
            btn.addEventListener('click', () => {
                const id = btn.dataset.jumpId;
                closeListPanel();
                openArticleModal(id, '');
            });
        });
    }

    function attachListPanelHandlers() {
        if ($readerListClose) {
            $readerListClose.addEventListener('click', closeListPanel);
        }
        if ($readerListTabs) {
            $readerListTabs.querySelectorAll('.reader-list-tab').forEach(tab => {
                tab.addEventListener('click', () => {
                    $readerListTabs.querySelectorAll('.reader-list-tab').forEach(t => t.classList.remove('is-active'));
                    tab.classList.add('is-active');
                    listPanelFilter = tab.dataset.listCat;
                    renderListPanel();
                });
            });
        }
    }

    // ----------------------------------------------------------
    // INIT
    // ----------------------------------------------------------
    function init() {
        // Share modal close handlers
        document.querySelector('.share-close').addEventListener('click', closeShareModal);
        document.querySelector('.share-modal-backdrop').addEventListener('click', closeShareModal);
        $modal.addEventListener('click', handleShareClick);

        // Article modal close handlers
        document.querySelector('.article-close').addEventListener('click', closeArticleModal);
        document.querySelector('.article-modal-backdrop').addEventListener('click', closeArticleModal);
        if ($articleShareBtn) {
            $articleShareBtn.addEventListener('click', shareCurrentArticle);
        }

        // Header category navigation pills
        attachCategoryNavHandlers();

        // Bottom reader navigation (prev / list / next)
        attachReaderNavHandlers();

        // Article list panel (slide-up)
        attachListPanelHandlers();

        // Global Escape handler
        document.addEventListener('keydown', (e) => {
            if (e.key !== 'Escape') return;
            if ($readerListPanel && $readerListPanel.classList.contains('is-open')) {
                closeListPanel();
            } else if ($articleModal.classList.contains('is-open')) {
                closeArticleModal();
            } else if ($modal.classList.contains('is-open')) {
                closeShareModal();
            }
        });

        // Keyboard navigation for article modal: arrow keys for prev/next
        document.addEventListener('keydown', (e) => {
            if (!$articleModal.classList.contains('is-open')) return;
            if (e.key === 'ArrowLeft' && $readerPrevBtn && !$readerPrevBtn.disabled) {
                $readerPrevBtn.click();
            } else if (e.key === 'ArrowRight' && $readerNextBtn && !$readerNextBtn.disabled) {
                $readerNextBtn.click();
            }
        });

        // Initialize favorites badge
        updateFavBadge();

        loadNews();

        // Auto-refresh news every 30 minutes
        setInterval(() => loadNews(currentFilter), 30 * 60 * 1000);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
