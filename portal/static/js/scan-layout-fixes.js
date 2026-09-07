/* RYB Finserv — scan/detail layout and transaction navigation fixes */
(function () {
  'use strict';

  function installPresentationStyle() {
    if (!document.head || document.getElementById('scan-detail-presentation-style')) return;
    var style = document.createElement('style');
    style.id = 'scan-detail-presentation-style';
    style.textContent = [
      'html,body{margin:0!important;padding:0!important}',
      'body>svg{position:fixed!important;top:0!important;left:0!important;width:100vw!important;height:100vh!important;margin:0!important;padding:0!important;display:block!important;pointer-events:none!important;z-index:0!important;opacity:.055!important;overflow:visible!important}',
      'body>.skip-link,body>.site-header,body>main,body>.site-footer{position:relative;z-index:1}',
      '.scan-page .page-header{padding:1.55rem 0 1.45rem!important}',
      '.scan-page .breadcrumb{margin-bottom:.85rem!important}',
      '.scan-page .page-title{font-size:clamp(2rem,3.2vw,2.6rem)!important;line-height:1.04!important}',
      '.scan-page .page-title-weekday{font-size:var(--text-xs)!important;margin-bottom:.22rem!important}',
      '.scan-page .page-sub{font-size:var(--text-base)!important;margin-top:.4rem!important}',
      '.scan-page .page-header-content{gap:1rem!important}',
      '.scan-page .page-header-stats{gap:2.1rem!important}',
      '.scan-page .stat-num{font-size:2.35rem!important}',
      '.scan-page .stat-lbl{font-size:var(--text-xxs)!important}',
      '.stock-modal .stock-detail .overview-grid{grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:1rem!important}',
      '.stock-modal .stock-detail .overview-card{border:1px solid #d9e2ef!important;border-radius:14px!important;background:rgba(255,255,255,.78)!important;padding:16px!important;box-shadow:none!important}',
      '.stock-modal .stock-detail .ov-head{margin-bottom:12px!important}',
      '.stock-modal .stock-detail .ov-head strong{font-size:1rem!important;font-weight:800!important;color:#102052!important}',
      '.stock-modal .stock-detail .ov-head small{font-size:.78rem!important;color:#64748b!important}',
      '.stock-modal .stock-detail .ov-row{font-size:.78rem!important;padding:8px 0!important}',
      '.stock-modal .stock-detail .ov-row span{color:#64748b!important}',
      '.stock-modal .stock-detail .ov-row b{font-size:.8rem!important;color:#172554!important}',
      '.stock-modal .stock-detail .ov-row b.good{color:#15803d!important}',
      '.stock-modal .stock-detail .badge{font-size:.68rem!important;padding:5px 9px!important}',
      '.stock-modal .stock-detail .data-note{font-size:.72rem!important;margin-top:18px!important}',
      '.stock-modal .stock-detail .market-cell label,.stock-modal .stock-detail .activity label,.stock-modal .stock-detail .timing label,.stock-modal .stock-detail .dd-section,.stock-modal .stock-detail .range-values small{display:block!important;text-transform:uppercase!important;letter-spacing:.045em!important}',
      '.stock-modal .stock-detail .market-big,.stock-modal .stock-detail .market-sub,.stock-modal .stock-detail .activity b,.stock-modal .stock-detail .timing b,.stock-modal .stock-detail .range-values b,.stock-modal .stock-detail .ov-row span,.stock-modal .stock-detail .ov-row b{text-transform:none!important;letter-spacing:normal!important}',
      '.stock-modal .stock-detail,.stock-modal .stock-detail button,.stock-modal .stock-detail a{font-family:var(--font-sans)!important}',
      '.stock-modal .stock-detail .transaction-link,.stock-modal .stock-detail .transaction-back-link,.stock-modal .stock-detail .view-link{font-size:var(--text-sm)!important;line-height:1.4!important;font-weight:700!important}',
      '.stock-modal .stock-detail>.detail-watermark{position:absolute!important;inset:0!important;width:100%!important;height:100%!important;display:block!important;pointer-events:none!important;z-index:0!important;overflow:hidden!important}',
      '.stock-modal .stock-detail>.detail-watermark svg{position:absolute!important;top:50%!important;left:50%!important;width:72%!important;height:72%!important;transform:translate(-50%,-42%)!important;margin:0!important;pointer-events:none!important;z-index:0!important;opacity:.045!important}',
      '.stock-modal .stock-detail>.stock-detail-header,.stock-modal .stock-detail>.detail-hero,.stock-modal .stock-detail>.detail-decision-flow,.stock-modal .stock-detail>.detail-tabs,.stock-modal .stock-detail>.detail-panel{position:relative!important;z-index:1!important}',
      '@media(max-width:900px){.stock-modal .stock-detail .overview-grid{grid-template-columns:1fr!important}}',
      '@media(max-width:640px){.scan-page .page-header{padding:1.35rem 0 1.15rem!important}.scan-page .breadcrumb{margin-bottom:.7rem!important}.scan-page .page-title{font-size:clamp(1.75rem,6vw,2.1rem)!important}.scan-page .page-sub{font-size:.82rem!important}.scan-page .stat-num{font-size:1.9rem!important}.stock-modal .stock-detail .overview-grid{gap:.65rem!important}.stock-modal .stock-detail .overview-card{padding:12px!important}.stock-modal .stock-detail .ov-head strong{font-size:.78rem!important}.stock-modal .stock-detail .ov-head small{font-size:.62rem!important}.stock-modal .stock-detail .ov-row{font-size:.66rem!important}.stock-modal .stock-detail .ov-row b{font-size:.68rem!important}.stock-modal .stock-detail .data-note{font-size:.62rem!important}}'
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
    installPresentationStyle();
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
