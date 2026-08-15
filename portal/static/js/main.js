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
})();
