/* RYB Finserv — scan/detail layout fixes */
(function () {
  'use strict';

  function applyAnalysisScroll() {
    document.querySelectorAll('.stock-detail').forEach(function (el) {
      el.style.overflowY = 'auto';
      el.style.overflowX = 'hidden';
      el.style.webkitOverflowScrolling = 'touch';
    });
  }

  applyAnalysisScroll();
  if (document.body) {
    new MutationObserver(applyAnalysisScroll).observe(document.body, { childList: true, subtree: true });
  } else {
    document.addEventListener('DOMContentLoaded', applyAnalysisScroll, { once: true });
  }
})();
