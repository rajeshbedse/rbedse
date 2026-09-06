/* RYB Finserv — scan/detail layout fixes */
(function () {
  'use strict';

  function applyAnalysisScroll() {
    document.querySelectorAll('.stock-detail').forEach(function (el) {
      if (getComputedStyle(el).overflowY !== 'auto') {
        el.style.setProperty('overflow-y', 'auto', 'important');
      }
      if (getComputedStyle(el).overflowX !== 'hidden') {
        el.style.setProperty('overflow-x', 'hidden', 'important');
      }
      el.style.setProperty('-webkit-overflow-scrolling', 'touch');
    });
  }

  applyAnalysisScroll();
  if (document.body) {
    new MutationObserver(applyAnalysisScroll).observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['class', 'style']
    });
  } else {
    document.addEventListener('DOMContentLoaded', applyAnalysisScroll, { once: true });
  }
})();
