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
  // scan.js dynamically renders the detail panel. Keep the terminology tied
  // to the active tab so Risk remains "Risk signals" and Promoter uses the
  // requested "Promotor indicators" heading.
  var detailPanel = document.getElementById('detail-panel');
  if (detailPanel && window.MutationObserver) {
    var syncDetailHeading = function () {
      var activeTab = document.querySelector('.detail-tab.is-active');
      var tabName = activeTab ? activeTab.getAttribute('data-detail-tab') : '';
      var heading = detailPanel.querySelector('h3');
      if (!heading) return;

      if (tabName === 'promoter') {
        heading.textContent = 'Promotor indicators';
      } else if (tabName === 'risk') {
        heading.textContent = 'Risk signals';
      }
    };

    syncDetailHeading();
    new MutationObserver(syncDetailHeading).observe(detailPanel, {
      childList: true,
      subtree: true
    });
  }
})();
