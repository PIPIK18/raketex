(() => {
  'use strict';
  const measurementId = 'G-VZ21P594BP';
  const storageKey = 'raketex-analytics-consent-v1';
  const trackPage = document.currentScript.dataset.trackPage === 'true';
  const banner = document.getElementById('cookie-banner');
  const settings = document.getElementById('cookie-settings');
  const accept = document.getElementById('cookie-accept');
  const reject = document.getElementById('cookie-reject');
  let started = false;
  let returnFocus = false;

  function readChoice() {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey));
      if (saved && saved.expires > Date.now() && ['granted', 'denied'].includes(saved.choice)) return saved.choice;
    } catch (_) { /* Unavailable storage means ask again. */ }
    return null;
  }

  function startAnalytics() {
    if (started || !trackPage) return;
    started = true;
    window['ga-disable-' + measurementId] = false;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('consent', 'default', {
      analytics_storage: 'denied', ad_storage: 'denied',
      ad_user_data: 'denied', ad_personalization: 'denied'
    });
    window.gtag('consent', 'update', { analytics_storage: 'granted' });
    window.gtag('js', new Date());
    window.gtag('config', measurementId, {
      allow_google_signals: false,
      allow_ad_personalization_signals: false,
      // Keep search text, URL tokens and fragments out of page URLs.
      page_location: window.location.origin + window.location.pathname,
      page_referrer: document.referrer.split(/[?#]/)[0]
    });
    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://www.googletagmanager.com/gtag/js?id=' + measurementId;
    document.head.appendChild(script);
  }

  function stopAnalytics() {
    window['ga-disable-' + measurementId] = true;
    if (started) window.gtag('consent', 'update', { analytics_storage: 'denied' });
    // Remove GA cookies both on this host and any parent domain.
    const parts = window.location.hostname.split('.');
    const domains = ['', ...parts.map((_, i) => '; domain=' + parts.slice(i).join('.'))];
    document.cookie.split(';').forEach(cookie => {
      const name = cookie.split('=')[0].trim();
      if (name === '_ga' || name.startsWith('_ga_')) {
        domains.forEach(domain => {
          document.cookie = name + '=; Max-Age=0; path=/' + domain;
        });
      }
    });
  }

  function applyChoice(choice) {
    banner.hidden = choice !== null;
    if (choice === 'granted') startAnalytics();
    else stopAnalytics();
  }

  function choose(choice) {
    try {
      localStorage.setItem(storageKey, JSON.stringify({ choice, expires: Date.now() + 180 * 86400000 }));
    } catch (_) { /* Honor the choice for this page even without storage. */ }
    const needsReload = started && choice === 'denied';
    applyChoice(choice);
    if (returnFocus || banner.contains(document.activeElement)) settings.focus();
    // Unload the Google library after withdrawal, including its event listeners.
    if (needsReload) window.location.reload();
  }

  settings.hidden = false;
  settings.addEventListener('click', () => {
    returnFocus = true;
    banner.hidden = false;
    accept.focus();
  });
  accept.addEventListener('click', () => choose('granted'));
  reject.addEventListener('click', () => choose('denied'));
  window.addEventListener('storage', event => {
    if (event.key !== storageKey && event.key !== null) return;
    const choice = readChoice();
    const needsReload = started && choice !== 'granted';
    applyChoice(choice);
    if (needsReload) window.location.reload();
  });
  applyChoice(readChoice());
})();
