/* RYB Finserv — watermark visibility / transparent cards + DMA display fix v6 */
(function () {
  'use strict';

  function apply() {
    if (!document.head || document.getElementById('scan-watermark-visibility-hotfix')) return;
    var style = document.createElement('style');
    style.id = 'scan-watermark-visibility-hotfix';
    style.textContent = [
      '.stock-detail>.detail-watermark{position:absolute!important;inset:0!important;z-index:0!important;opacity:1!important;display:block!important}',
      '.stock-detail>.detail-watermark>svg{position:absolute!important;top:50%!important;left:50%!important;width:78%!important;height:78%!important;transform:translate(-50%,-42%)!important;opacity:.16!important;z-index:0!important}',
      '.stock-detail .detail-hero{background:transparent!important}',
      '.stock-detail .detail-score-block{background:rgba(248,251,255,.52)!important}',
      '.stock-detail .detail-tabs{background:transparent!important}',
      '.stock-detail .detail-panel{background:transparent!important}',
      '.stock-detail .overview-card{background:rgba(255,255,255,.42)!important}',
      '.stock-detail .dd-card{background:rgba(255,255,255,.42)!important}',
      '.stock-detail .dd-card.promoter{background:rgba(246,255,250,.46)!important}',
      '.stock-detail .activity-grid{background:rgba(255,255,255,.36)!important}',
      '.stock-detail-header,.stock-detail .detail-hero,.stock-detail .detail-decision-flow,.stock-detail .detail-tabs,.stock-detail .detail-panel{position:relative!important;z-index:1!important}',
      '@media(max-width:640px){.stock-detail>.detail-watermark>svg{width:125%!important;height:68%!important;opacity:.13!important}.stock-detail .overview-card{background:rgba(255,255,255,.40)!important}.stock-detail .dd-card{background:rgba(255,255,255,.40)!important}.stock-detail .dd-card.promoter{background:rgba(246,255,250,.44)!important}.stock-detail .activity-grid{background:rgba(255,255,255,.34)!important}}'
    ].join('');
    document.head.appendChild(style);
  }

  function patchDmaValues() {
    var page = document.querySelector('.scan-page');
    var title = document.querySelector('#detail-title');
    var panel = document.querySelector('#detail-panel');
    if (!page || !title || !panel || !title.textContent.trim()) return;

    var technical = Array.prototype.slice.call(panel.querySelectorAll('.overview-card')).find(function (card) {
      var h = card.querySelector('.ov-head strong');
      return h && h.textContent.trim().toUpperCase() === 'TECHNICAL';
    });
    if (!technical) return;

    var dmaRows = Array.prototype.slice.call(technical.querySelectorAll('.ov-row')).filter(function (rowEl) {
      var labelEl = rowEl.querySelector('span');
      return labelEl && (labelEl.textContent.trim() === '50 DMA' || labelEl.textContent.trim() === '200 DMA');
    });
    if (!dmaRows.length) return;

    var symbol = title.textContent.trim().split(/\s+/)[0].toUpperCase();
    var date = page.dataset.scanDate;
    if (!symbol || !date) return;

    var requestKey = symbol + '|' + date;
    if (panel.dataset.dmaRequestKey === requestKey) return;
    panel.dataset.dmaRequestKey = requestKey;

    fetch('/api/scan/' + date + '/stock/' + encodeURIComponent(symbol))
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (row) {
        var signals = Array.isArray(row.tech_signals) ? row.tech_signals : [];
        function signalValue(label, directKey) {
          var direct = Number(row[directKey]);
          if (Number.isFinite(direct) && direct > 0) return direct;
          var signal = signals.find(function (s) { return s && s.label === label; });
          var note = signal && String(signal.note || '');
          var match = note.match(/₹\s*([0-9]+(?:\.[0-9]+)?)/);
          return match ? Number(match[1]) : null;
        }

        var dma50 = signalValue('Price > 50 DMA', 'DMA50');
        var dma200 = signalValue('Price > 200 DMA', 'DMA200');
        Array.prototype.forEach.call(technical.querySelectorAll('.ov-row'), function (rowEl) {
          var labelEl = rowEl.querySelector('span');
          var valueEl = rowEl.querySelector('b');
          if (!labelEl || !valueEl) return;
          var label = labelEl.textContent.trim();
          var value = label === '50 DMA' ? dma50 : label === '200 DMA' ? dma200 : null;
          if (value !== null && Number.isFinite(value)) {
            valueEl.textContent = '₹' + value.toLocaleString('en-IN', { maximumFractionDigits: 2 });
          }
        });
      })
      .catch(function (e) {
        delete panel.dataset.dmaRequestKey;
        console.warn('DMA display patch failed', e);
      });
  }

  function start() {
    apply();
    var observer = new MutationObserver(function () {
      window.setTimeout(patchDmaValues, 0);
    });
    var target = document.querySelector('.stock-modal') || document.body;
    observer.observe(target, { childList: true, subtree: true });
    window.setTimeout(patchDmaValues, 250);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, { once: true });
  else start();
})();
