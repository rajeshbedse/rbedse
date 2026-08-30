/* RYB Finserv — main.js  (site-wide: nav toggle, footer year, detail heading) */
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
  // The detail panel is populated dynamically by scan.js, so observe it and
  // rename the promoter-tab heading without changing any report data.
  var detailPanel = document.getElementById('detail-panel');
  if (detailPanel && window.MutationObserver) {
    var renamePromoterHeading = function () {
      var headings = detailPanel.querySelectorAll('h3');
      headings.forEach(function (heading) {
        if (heading.textContent.trim() === 'Risk signals') {
          heading.textContent = 'Promoter indicators';
        }
      });
    };
    renamePromoterHeading();
    new MutationObserver(renamePromoterHeading).observe(detailPanel, {
      childList: true,
      subtree: true
    });
  }
})();
