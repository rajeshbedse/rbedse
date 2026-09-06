/* RYB Finserv — scan/detail layout and transaction navigation fixes */
(function () {
  'use strict';

  function applyAnalysisScroll() {
    document.querySelectorAll('.stock-detail').forEach(function (el) {
      if (getComputedStyle(el).overflowY !== 'auto') el.style.setProperty('overflow-y', 'auto', 'important');
      if (getComputedStyle(el).overflowX !== 'hidden') el.style.setProperty('overflow-x', 'hidden', 'important');
      el.style.setProperty('-webkit-overflow-scrolling', 'touch');
    });
  }

  function initTransactionNavigation() {
    if (!document.head) return;
    if (!document.getElementById('transaction-navigation-style')) {
      var style = document.createElement('style');
      style.id = 'transaction-navigation-style';
      style.textContent = '.detail-tabs{display:none!important}.ov-link{display:none!important}.transaction-link{display:inline-block;margin-top:14px;color:#155eef;font-size:.72rem;font-weight:850;text-decoration:none}.transaction-link:after{content:" →";font-size:1rem}.transaction-link:hover{text-decoration:underline}.transaction-back-link{display:inline-block;margin-bottom:14px;color:#155eef;font-size:.72rem;font-weight:850;text-decoration:none}.transaction-back-link:before{content:"← ";font-size:1rem}.transaction-back-link:hover{text-decoration:underline}';
      document.head.appendChild(style);
    }

    var flow = document.querySelector('.detail-decision-flow');
    if (flow) {
      var promoter = flow.querySelector('.dd-card.promoter .promoter-inner');
      if (promoter && !promoter.querySelector('.transaction-link')) {
        var link = document.createElement('a');
        link.href = '#';
        link.className = 'transaction-link';
        link.textContent = 'View promoter transactions';
        link.addEventListener('click', function (e) {
          e.preventDefault();
          var tab = document.querySelector('.detail-tab[data-detail-tab="transactions"]');
          if (tab) tab.click();
        });
        promoter.appendChild(link);
      }
    }

    var active = document.querySelector('.detail-tab.is-active[data-detail-tab="transactions"]');
    var panel = document.querySelector('#detail-panel');
    if (active && panel && !panel.querySelector('.transaction-back-link')) {
      var back = document.createElement('a');
      back.href = '#';
      back.className = 'transaction-back-link';
      back.textContent = 'Back to stock overview';
      back.addEventListener('click', function (e) {
        e.preventDefault();
        var tab = document.querySelector('.detail-tab[data-detail-tab="overview"]');
        if (tab) tab.click();
        var detail = document.querySelector('.stock-detail');
        if (detail) detail.scrollTop = 0;
        window.scrollTo(0, 0);
      });
      panel.insertBefore(back, panel.firstChild);
    }
  }

  function applyAll() {
    applyAnalysisScroll();
    initTransactionNavigation();
  }

  applyAll();
  if (document.body) {
    new MutationObserver(applyAll).observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['class', 'style']
    });
  } else {
    document.addEventListener('DOMContentLoaded', applyAll, { once: true });
  }
})();
