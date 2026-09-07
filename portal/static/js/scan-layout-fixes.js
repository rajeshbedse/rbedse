/* RYB Finserv — scan/detail layout and transaction navigation fixes */
(function () {
  'use strict';

  function installDetailPresentationStyle() {
    if (!document.head || document.getElementById('detail-presentation-style')) return;
    var style = document.createElement('style');
    style.id = 'detail-presentation-style';
    style.textContent = [
      'body>svg{position:fixed!important;inset:0!important;width:100vw!important;height:100vh!important;margin:0!important;padding:0!important;pointer-events:none!important;z-index:0!important;opacity:.06!important;overflow:visible!important}',
      'body>.skip-link,body>.site-header,body>main,body>.site-footer{position:relative;z-index:1}',
      '.stock-modal .stock-detail{background:transparent!important}',
      '.stock-modal .stock-detail>.detail-watermark{z-index:0!important;pointer-events:none!important}',
      '.stock-modal .stock-detail>.detail-watermark svg{z-index:0!important;pointer-events:none!important}',
      '.stock-modal .stock-detail>.stock-detail-header,.stock-modal .stock-detail>.detail-hero,.stock-modal .stock-detail>.detail-decision-flow,.stock-modal .stock-detail>.detail-tabs,.stock-modal .stock-detail>.detail-panel{position:relative;z-index:1}',
      '.stock-modal .stock-detail .dd-card,.stock-modal .stock-detail .overview-card,.stock-modal .stock-detail .activity-grid{background:rgba(255,255,255,.72)!important}',
      '.stock-modal .stock-detail .dd-card.promoter{background:rgba(246,255,250,.72)!important}',
      '.stock-modal .stock-detail .market-cell label,.stock-modal .stock-detail .activity label,.stock-modal .stock-detail .timing label,.stock-modal .stock-detail .transaction-grid small{display:block!important;text-transform:uppercase!important;letter-spacing:.045em!important}',
      '.stock-modal .stock-detail .market-cell .market-big,.stock-modal .stock-detail .market-cell .market-sub,.stock-modal .stock-detail .activity b,.stock-modal .stock-detail .timing b,.stock-modal .stock-detail .transaction-grid strong{ text-transform:none!important;letter-spacing:normal!important}',
      '.stock-modal .stock-detail .transaction-card>div:first-child span{ text-transform:none!important}',
      '.stock-modal .stock-detail .dd-head strong,.stock-modal .stock-detail .dd-section,.stock-modal .stock-detail .ov-head strong{ text-transform:none!important}',
      '.stock-modal .stock-detail .dd-section{letter-spacing:.04em!important}'
    ].join('');
    document.head.appendChild(style);
  }

  function applyAnalysisScroll() {
    document.querySelectorAll('.stock-detail').forEach(function (el) {
      if (getComputedStyle(el).overflowY !== 'auto') el.style.setProperty('overflow-y', 'auto', 'important');
      if (getComputedStyle(el).overflowX !== 'hidden') el.style.setProperty('overflow-x', 'hidden', 'important');
      el.style.setProperty('-webkit-overflow-scrolling', 'touch');
    });
  }

  function applyMarketDirectionColors() {
    document.querySelectorAll('.stock-modal .market-grid .market-cell:first-child .market-sub').forEach(function (el) {
      var text = el.textContent.trim();
      var negative = /^-/.test(text);
      el.classList.toggle('market-negative', negative);
      el.classList.toggle('market-positive', !negative && /^\+|^0(?:\.0+)?%/.test(text));
    });
  }

  function initTransactionNavigation() {
    if (!document.head) return;
    if (!document.getElementById('transaction-navigation-style')) {
      var style = document.createElement('style');
      style.id = 'transaction-navigation-style';
      style.textContent = '.detail-tabs{display:none!important}.ov-link{display:none!important}.transaction-link{display:inline-block;margin-top:14px;color:#155eef;font-size:.72rem;font-weight:850;text-decoration:none}.transaction-link:after{content:" →";font-size:1rem}.transaction-link:hover{text-decoration:underline}.transaction-back-link{display:inline-block;margin-bottom:14px;color:#155eef;font-size:.72rem;font-weight:850;text-decoration:none}.transaction-back-link:before{content:"← ";font-size:1rem}.transaction-back-link:hover{text-decoration:underline}.market-grid .market-cell:first-child .market-sub.market-negative{color:#b91c1c!important}.market-grid .market-cell:first-child .market-sub.market-positive{color:#15803d!important}';
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

    document.querySelectorAll('.dd-card.promoter .dd-title strong').forEach(function (heading) {
      if (heading.textContent.trim() === 'Promoter Activity & Timing') {
        heading.textContent = 'Promoter Activity';
      }
    });

    applyMarketDirectionColors();
  }

  function applyAll() {
    installDetailPresentationStyle();
    applyAnalysisScroll();
    initTransactionNavigation();
    applyMarketDirectionColors();
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
