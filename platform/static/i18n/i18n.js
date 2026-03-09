/**
 * Lightweight client-side i18n module.
 *
 * Usage:
 *   1. Include this script in your page.
 *   2. Add data-i18n="key" attributes to elements whose textContent should be translated.
 *   3. Add data-i18n-placeholder="key" for placeholder attributes.
 *   4. Add data-i18n-title="key" for title attributes.
 *   5. Call i18n.t('key') for programmatic translation (e.g. in JS-generated HTML).
 *   6. Call i18n.init() after DOM is ready (auto-called on DOMContentLoaded).
 *
 * The user's locale is persisted in localStorage('locale').
 * Arabic ('ar') automatically sets dir="rtl" and injects RTL CSS overrides.
 */
(function () {
    'use strict';

    const SUPPORTED = ['en', 'fr', 'ar'];
    const DEFAULT_LOCALE = 'en';
    const CACHE = {};      // locale → dict
    let _locale = DEFAULT_LOCALE;
    let _ready = false;

    // ── Public API ──────────────────────────────────────────────
    const i18n = {
        /** Current locale code */
        get locale() { return _locale; },

        /** All supported locale codes */
        get supported() { return SUPPORTED.slice(); },

        /** Translate a key. Returns the key itself if not found. */
        t(key, fallback) {
            const dict = CACHE[_locale] || CACHE[DEFAULT_LOCALE] || {};
            return dict[key] ?? fallback ?? key;
        },

        /** Change locale, reload translations, re-apply to DOM. */
        async setLocale(code) {
            if (!SUPPORTED.includes(code)) return;
            _locale = code;
            localStorage.setItem('locale', code);
            await _loadDict(code);
            _applyDir();
            _translateDOM();
        },

        /** Initialise (called automatically on DOMContentLoaded). */
        async init() {
            if (_ready) return;
            _ready = true;
            const stored = localStorage.getItem('locale');
            if (stored && SUPPORTED.includes(stored)) _locale = stored;
            await _loadDict(_locale);
            if (_locale !== DEFAULT_LOCALE) await _loadDict(DEFAULT_LOCALE); // fallback
            _applyDir();
            _translateDOM();
        },

        /** Build a language-switcher <select> and insert it. */
        renderSwitcher(container) {
            if (!container) return;
            const labels = { en: 'EN', fr: 'FR', ar: 'AR' };
            const select = document.createElement('select');
            select.className = 'form-select form-select-sm';
            select.style.cssText = 'width:auto;flex-shrink:0;font-size:13px;padding:4px 28px 4px 8px;background-color:rgba(255,255,255,0.12);color:#fff;border:1px solid rgba(255,255,255,0.25);border-radius:6px';
            SUPPORTED.forEach(code => {
                const opt = document.createElement('option');
                opt.value = code;
                opt.textContent = labels[code] || code.toUpperCase();
                opt.style.color = '#000';
                if (code === _locale) opt.selected = true;
                select.appendChild(opt);
            });
            select.addEventListener('change', () => i18n.setLocale(select.value));
            container.appendChild(select);
        }
    };

    // ── Internal ────────────────────────────────────────────────
    function _basePath() {
        // Works whether the page is served from / or /t/<slug>/myfomo etc.
        return '/static/i18n/';
    }

    async function _loadDict(code) {
        if (CACHE[code]) return;
        try {
            const res = await fetch(_basePath() + code + '.json');
            if (!res.ok) throw new Error(res.status);
            CACHE[code] = await res.json();
        } catch (e) {
            console.warn('[i18n] Could not load ' + code + '.json', e);
            CACHE[code] = {};
        }
    }

    function _applyDir() {
        const isRTL = _locale === 'ar';
        document.documentElement.setAttribute('dir', isRTL ? 'rtl' : 'ltr');
        document.documentElement.setAttribute('lang', _locale);
        // Inject/remove RTL stylesheet
        let rtlLink = document.getElementById('i18n-rtl-css');
        if (isRTL) {
            if (!rtlLink) {
                rtlLink = document.createElement('link');
                rtlLink.id = 'i18n-rtl-css';
                rtlLink.rel = 'stylesheet';
                rtlLink.href = _basePath() + 'rtl.css';
                document.head.appendChild(rtlLink);
            }
        } else if (rtlLink) {
            rtlLink.remove();
        }
    }

    function _translateDOM() {
        // data-i18n → textContent
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            el.textContent = i18n.t(key);
        });
        // data-i18n-placeholder → placeholder
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            el.placeholder = i18n.t(el.getAttribute('data-i18n-placeholder'));
        });
        // data-i18n-title → title
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            el.title = i18n.t(el.getAttribute('data-i18n-title'));
        });
        // data-i18n-html → innerHTML (use sparingly)
        document.querySelectorAll('[data-i18n-html]').forEach(el => {
            el.innerHTML = i18n.t(el.getAttribute('data-i18n-html'));
        });
    }

    // Auto-init
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => i18n.init());
    } else {
        i18n.init();
    }

    window.i18n = i18n;
})();
