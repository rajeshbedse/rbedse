/* RYB Finserv — main.js  (site-wide: nav toggle, footer year) */
(function () {
  'use strict';

  // ── Mobile nav toggle ──────────────────────────────────────────────────────
  var toggle = document.getElementById('nav-toggle');
  var nav    = document.getElementById('site-nav');
  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      var open = nav.classList.toggle('nav-open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      document.body.classList.toggle('nav-open', open);
    });

    // close on outside click
    document.addEventListener('click', function (e) {
      if (!nav.contains(e.target) && !toggle.contains(e.target)) {
        nav.classList.remove('nav-open');
        toggle.setAttribute('aria-expanded', 'false');
        document.body.classList.remove('nav-open');
      }
    });

    // close on Escape
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        nav.classList.remove('nav-open');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.focus();
      }
    });
  }

  // ── Current year in footer ─────────────────────────────────────────────────
  // Jinja injects {{ now_year }}, but keep this as a JS fallback.

  // ── Stock detail terminology ───────────────────────────────────────────────
  // scan.js owns detail-tab navigation and dynamically renders the detail panel.
  // Update only the heading after a tab click; do not observe the panel, since
  // changing text inside a MutationObserver would retrigger the observer.
  document.addEventListener('click', function (e) {
    var tab = e.target.closest ? e.target.closest('.detail-tab') : null;
    if (!tab) return;

    var tabName = tab.getAttribute('data-detail-tab') || '';
    if (tabName !== 'promoter' && tabName !== 'risk') return;

    window.setTimeout(function () {
      var panel = document.getElementById('detail-panel');
      if (!panel) return;
      var heading = panel.querySelector('h3');
      if (!heading) return;
      heading.textContent = tabName === 'promoter' ? 'Promotor indicators' : 'Risk signals';
    }, 0);
  });
})();
