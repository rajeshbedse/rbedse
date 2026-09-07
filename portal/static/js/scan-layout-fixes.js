/* RYB Finserv — scan/detail presentation */
(function () {
  'use strict';

  function installPresentationStyle() {
    if (!document.head || document.getElementById('scan-detail-presentation-style')) return;
    var style = document.createElement('style');
    style.id = 'scan-detail-presentation-style';
    style.textContent = [
      'html,body{margin:0!important;padding:0!important}',
      'body:has(.scan-page)>svg{display:none!important}',
      'body>.skip-link{position:absolute!important;top:-40px!important}',
      'body>.site-header{position:sticky!important;top:0!important;margin-top:0!important}',
      'body>main{margin-top:0!important;padding-top:0!important}',
      '.scan-page{margin-top:0!important}',
      '.scan-page .page-header{margin-top:0!important;padding:1.55rem 0 1.45rem!important}',
      '.scan-page .breadcrumb{margin-bottom:.85rem!important}',
      '.scan-page .page-title{font-size:clamp(2rem,3.2vw,2.6rem)!important;line-height:1.04!important}',
      '.scan-page .page-title-weekday{font-size:var(--text-xs)!important;margin-bottom:.22rem!important}',
      '.scan-page .page-sub{font-size:var(--text-base)!important;margin-top:.4rem!important}',
      '.scan-page .page-header-content{gap:1rem!important}',
      '.scan-page .page-header-stats{gap:2.1rem!important}',
      '.scan-page .stat-num{font-size:2.35rem!important}',
      '.scan-page .stat-lbl{font-size:var(--text-xxs)!important}',
      '.stock-modal{z-index:1000!important;background:transparent!important}',
      '.stock-modal-backdrop{background:#f7f9fc!important}',
      '.stock-detail{background:#fff!important;position:relative!important;isolation:isolate!important}',
      '.stock-detail>.detail-watermark{position:absolute!important;inset:0!important;width:100%!important;height:100%!important;margin:0!important;display:block!important;pointer-events:none!important;z-index:0!important;overflow:hidden!important}',
      '.stock-detail>.detail-watermark>svg{position:absolute!important;top:50%!important;left:50%!important;width:72%!important;height:72%!important;transform:translate(-50%,-42%)!important;margin:0!important;pointer-events:none!important;opacity:.045!important;z-index:0!important}',
      '.stock-detail>:not(.detail-watermark){position:relative!important;z-index:1!important}',
      '.stock-modal .stock-detail .overview-grid{display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:16px!important}',
      '.stock-modal .stock-detail .overview-card{border:1px solid #d9e2ef!important;border-radius:14px!important;background:#fff!important;padding:16px!important;box-shadow:none!important}',
      '.stock-modal .stock-detail .ov-head{margin-bottom:12px!important}',
      '.stock-modal .stock-detail .ov-head strong{font-size:1rem!important;font-weight:800!important;color:#102052!important;text-transform:uppercase!important;letter-spacing:.02em!important}',
      '.stock-modal .stock-detail .ov-head small{font-size:.78rem!important;color:#64748b!important;text-transform:none!important;letter-spacing:normal!important}',
      '.stock-modal .stock-detail .ov-row{font-size:.78rem!important;padding:8px 0!important}',
      '.stock-modal .stock-detail .ov-row span{color:#64748b!important;text-transform:uppercase!important;letter-spacing:.045em!important}',
      '.stock-modal .stock-detail .ov-row b{font-size:.8rem!important;color:#172554!important;text-transform:none!important;letter-spacing:normal!important}',
      '.stock-modal .stock-detail .ov-row b.signed-positive{color:#15803d!important}',
      '.stock-modal .stock-detail .ov-row b.signed-negative{color:#b91c1c!important}',
      '.stock-modal .stock-detail .market-sub.signed-positive{color:#15803d!important}',
      '.stock-modal .stock-detail .market-sub.signed-negative{color:#b91c1c!important}',
      '.stock-modal .stock-detail .timing b.signed-positive{color:#15803d!important}',
      '.stock-modal .stock-detail .timing b.signed-negative{color:#b91c1c!important}',
      '.stock-modal .stock-detail .market-cell label,.stock-modal .stock-detail .activity label,.stock-modal .stock-detail .timing label,.stock-modal .stock-detail .dd-section,.stock-modal .stock-detail .range-values small{display:block!important;text-transform:uppercase!important;letter-spacing:.045em!important}',
      '.stock-modal .stock-detail .market-big,.stock-modal .stock-detail .market-sub,.stock-modal .stock-detail .activity b,.stock-modal .stock-detail .timing b,.stock-modal .stock-detail .range-values b{ text-transform:none!important;letter-spacing:normal!important}',
      '.signed-positive{color:#15803d!important}',
      '.signed-negative{color:#b91c1c!important}',
      '.stock-modal .stock-detail,.stock-modal .stock-detail button,.stock-modal .stock-detail a{font-family:var(--font-sans)!important}',
      '.stock-modal .stock-detail .transaction-link,.stock-modal .stock-detail .transaction-back-link{font-size:var(--text-sm)!important;line-height:1.4!important;font-weight:700!important}',
      '@media(max-width:900px){.stock-modal .stock-detail .overview-grid{grid-template-columns:1fr!important}}',
      '@media(max-width:640px){.scan-page .page-header{padding:1.35rem 0 1.15rem!important}.scan-page .breadcrumb{margin-bottom:.7rem!important}.scan-page .page-title{font-size:clamp(1.75rem,6vw,2.1rem)!important}.scan-page .page-sub{font-size:.82rem!important}.scan-page .stat-num{font-size:1.9rem!important}.stock-modal .stock-detail .overview-grid{gap:10px!important}.stock-modal .stock-detail .overview-card{padding:12px!important}.stock-modal .stock-detail .ov-head strong{font-size:.78rem!important}.stock-modal .stock-detail .ov-head small{font-size:.62rem!important}.stock-modal .stock-detail .ov-row{font-size:.66rem!important}.stock-modal .stock-detail .ov-row b{font-size:.68rem!important}}'
    ].join('');
    document.head.appendChild(style);
  }

  function applyAnalysisScroll() {
    document.querySelectorAll('.stock-detail').forEach(function (el) {
      el.style.setProperty('overflow-y', 'auto', 'important');
      el.style.setProperty('overflow-x', 'hidden', 'important');
      el.style.setProperty('-webkit-overflow-scrolling', 'touch');
    });
  }

  function signedClass(text) {
    var t = (text || '').trim();
    if (/^\+\s*(?:₹|[$€£])?\d/.test(t)) return 'signed-positive';
    if (/^-\s*(?:₹|[$€£])?\d/.test(t)) return 'signed-negative';
    return '';
  }

  function applySignedNumberColors() {
    var roots = document.querySelectorAll('.stock-modal .stock-detail, .stock-cards, .desktop-table-wrap');
    roots.forEach(function (root) {
      root.querySelectorAll('*').forEach(function (el) {
        if (el.children.length) return;
        var cls = signedClass(el.textContent || '');
        if (!cls) return;
        el.classList.add(cls);
        el.classList.remove(cls === 'signed-positive' ? 'signed-negative' : 'signed-positive');
      });
    });
  }

  function applyPromoterReferenceConsistency() {
    document.querySelectorAll('.stock-modal .stock-detail').forEach(function (detail) {
      var currentCell = Array.prototype.find.call(detail.querySelectorAll('.market-cell'), function (cell) {
        var label = cell.querySelector('label');
        return label && label.textContent.trim().toUpperCase() === 'CURRENT PRICE (CMP)';
      });
      if (!currentCell) return;
      var cmpEl = currentCell.querySelector('.market-big');
      var subEl = currentCell.querySelector('.market-sub');
      if (!cmpEl || !subEl) return;

      var avgEl = Array.prototype.find.call(detail.querySelectorAll('.timing'), function (cell) {
        var label = cell.querySelector('label');
        return label && label.textContent.trim().toUpperCase() === 'AVG BUY PRICE';
      });
      var avgValue = avgEl && avgEl.querySelector('b');
      if (!avgValue) return;

      var cmp = parseFloat((cmpEl.textContent || '').replace(/[^0-9.]/g, ''));
      var avg = parseFloat((avgValue.textContent || '').replace(/[^0-9.]/g, ''));
      if (!Number.isFinite(cmp) || !Number.isFinite(avg) || avg === 0) return;

      var diff = ((cmp - avg) / avg) * 100;
      var text = (diff > 0 ? '+' : '') + diff.toFixed(1) + '% vs promoter avg';
      subEl.textContent = text;
      var cls = signedClass(text);
      subEl.classList.remove('signed-positive', 'signed-negative');
      if (cls) subEl.classList.add(cls);
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
      });
      panel.insertBefore(back, panel.firstChild);
    }

    document.querySelectorAll('.dd-card.promoter .dd-title strong').forEach(function (heading) {
      if (heading.textContent.trim() === 'Promoter Activity & Timing') heading.textContent = 'Promoter Activity';
    });
  }

  function applyAll() {
    installPresentationStyle();
    applyAnalysisScroll();
    initTransactionNavigation();
    applySignedNumberColors();
    applyPromoterReferenceConsistency();
  }

  applyAll();
  if (document.body) {
    var observer = new MutationObserver(function () {
      applyAll();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }
})();