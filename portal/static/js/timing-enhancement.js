/* RYB Finserv — promoter timing presentation layer
 * Descriptive only: this file never changes score, category, filtering or sorting.
 */
(function () {
  'use strict';
  const root = document.querySelector('.scan-page');
  if (!root) return;
  const date = root.dataset.scanDate;
  const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const money = v => v == null || v === '' ? '—' : '₹' + Number(v).toLocaleString('en-IN', {maximumFractionDigits: 2});
  const pct = v => v == null || v === '' ? '—' : `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(1)}%`;

  const stageClass = stage => ({
    'Early Accumulation': 'timing-early',
    'Confirmed Accumulation': 'timing-confirmed',
    'Mature — Wait for Pullback': 'timing-mature',
    'Late — Poor Entry': 'timing-late',
    'No Signal': 'timing-none'
  }[stage] || 'timing-none');

  const style = document.createElement('style');
  style.textContent = `
    .timing-badge{display:inline-flex;align-items:center;gap:6px;margin-top:8px;padding:4px 9px;border-radius:999px;font-size:.72rem;font-weight:700;line-height:1.2;border:1px solid currentColor}
    .timing-early{color:#15803d;background:#f0fdf4}.timing-confirmed{color:#166534;background:#f0fdf4}.timing-mature{color:#a16207;background:#fffbeb}.timing-late{color:#b91c1c;background:#fef2f2}.timing-none{color:#64748b;background:#f8fafc}
    .timing-dot{width:7px;height:7px;border-radius:50%;background:currentColor}
    .timing-summary{margin:14px 0;padding:14px 16px;border:1px solid #e2e8f0;border-radius:12px;background:#f8fafc}
    .timing-summary-head{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:10px}.timing-summary-head strong{font-size:.9rem}.timing-summary-head span{font-size:.72rem;color:#64748b}
    .timing-summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.timing-summary-grid div{min-width:0}.timing-summary-grid small{display:block;color:#64748b;font-size:.68rem;margin-bottom:3px}.timing-summary-grid b{font-size:.84rem}
    @media(max-width:600px){.timing-summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
  `;
  document.head.appendChild(style);

  let timingRows = new Map();

  async function loadTimingRows() {
    try {
      const res = await fetch(`/api/scan/${date}/summary?view=${encodeURIComponent(document.querySelector('.scan-tab.is-active')?.dataset.view || 'shortlist')}`, {headers:{'Accept':'application/json'}});
      if (!res.ok) return;
      const data = await res.json();
      timingRows = new Map((data.rows || []).map(r => [String(r.symbol || '').toUpperCase(), r]));
      decorateCards();
    } catch (_) { /* core scan UX remains authoritative */ }
  }

  function decorateCards() {
    document.querySelectorAll('#stock-cards .stock-card').forEach(card => {
      if (card.querySelector('.timing-badge')) return;
      const row = timingRows.get(String(card.dataset.symbol || '').toUpperCase());
      if (!row || !row.timing_stage) return;
      const footer = card.querySelector('.research-card-footer');
      if (!footer) return;
      const badge = document.createElement('span');
      badge.className = `timing-badge ${stageClass(row.timing_stage)}`;
      badge.innerHTML = `<span class="timing-dot" aria-hidden="true"></span>${esc(row.timing_stage)}`;
      footer.insertBefore(badge, footer.firstChild);
    });
  }

  function timingPanel(row) {
    if (!row || !row.signal_stage) return '';
    const cls = stageClass(row.signal_stage);
    return `<section id="timing-summary" class="timing-summary" aria-label="Promoter timing">
      <div class="timing-summary-head"><strong>Promoter timing</strong><span>Descriptive entry timing — does not change RYB Score</span></div>
      <div class="timing-summary-grid">
        <div><small>Signal stage</small><b class="${cls}">${esc(row.signal_stage)}</b></div>
        <div><small>Freshness</small><b>${esc(row.freshness || '—')}</b></div>
        <div><small>Promoter avg</small><b>${money(row.promoter_avg_price)}</b></div>
        <div><small>CMP vs avg</small><b>${pct(row.cmp_vs_promoter_avg_pct)}</b></div>
        <div><small>First buy</small><b>${esc(row.first_buy_date || '—')}</b></div>
        <div><small>Latest buy</small><b>${esc(row.last_buy_date || '—')}</b></div>
        <div><small>Accumulation</small><b>${row.accumulation_days == null ? '—' : esc(row.accumulation_days + ' days')}</b></div>
        <div><small>Buys · 30D</small><b>${row.buy_txn_30d == null ? '—' : esc(row.buy_txn_30d)}</b></div>
      </div>
    </section>`;
  }

  async function decorateDetail(symbol) {
    try {
      const res = await fetch(`/api/scan/${date}/stock/${encodeURIComponent(symbol)}`, {headers:{'Accept':'application/json'}});
      if (!res.ok) return;
      const row = await res.json();
      const content = document.querySelector('#detail-content');
      const priceGrid = document.querySelector('#detail-price-grid');
      if (!content || !priceGrid) return;
      document.querySelector('#timing-summary')?.remove();
      priceGrid.insertAdjacentHTML('afterend', timingPanel(row));
    } catch (_) { /* core detail view remains authoritative */ }
  }

  const cardsObserver = new MutationObserver(decorateCards);
  const cards = document.querySelector('#stock-cards');
  if (cards) cardsObserver.observe(cards, {childList:true});

  const title = document.querySelector('#detail-title');
  if (title) {
    const observer = new MutationObserver(() => {
      const symbol = title.textContent.trim();
      if (symbol) decorateDetail(symbol);
    });
    observer.observe(title, {childList:true, characterData:true, subtree:true});
  }

  document.querySelectorAll('.scan-tab').forEach(tab => tab.addEventListener('click', () => setTimeout(loadTimingRows, 0)));
  loadTimingRows();
})();
