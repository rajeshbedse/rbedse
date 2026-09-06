/* RYB Finserv — promoter timing presentation layer
 * Descriptive only: this file never changes score, category, filtering or sorting.
 *
 * DEV refinement: consolidate promoter information into one activity/timing block
 * and keep the Overview focused on price + thesis. Fundamental metrics live in
 * the Fundamentals tab rather than being repeated on Overview.
 */
(function () {
  'use strict';
  const root = document.querySelector('.scan-page');
  if (!root) return;
  const date = root.dataset.scanDate;
  const esc = v => String(v ?? '').replace(/[&<>\'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;',"\"":'&quot;'}[c]));
  const money = v => v == null || v === '' ? '—' : '₹' + Number(v).toLocaleString('en-IN', {maximumFractionDigits: 2});
  const crMoney = v => v == null || v === '' || !Number.isFinite(Number(v)) ? '—' : '₹' + Number(v).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' Cr';
  const num = v => v == null || v === '' ? '—' : Number(v).toLocaleString('en-IN', {maximumFractionDigits: 2});
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
    .timing-summary-head{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:12px}.timing-summary-head strong{font-size:.9rem}.timing-summary-head span{font-size:.72rem;color:#64748b}
    .timing-subhead{display:block;margin:12px 0 8px;color:#64748b;font-size:.68rem;font-weight:800;letter-spacing:.05em;text-transform:uppercase}
    .timing-activity-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:4px}
    .timing-summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.timing-summary-grid div,.timing-activity-grid div{min-width:0}.timing-summary-grid small,.timing-activity-grid small{display:block;color:#64748b;font-size:.68rem;margin-bottom:3px}.timing-summary-grid b,.timing-activity-grid b{font-size:.84rem}
    .fundamental-metrics-section{margin-bottom:14px}
    @media(max-width:600px){.timing-activity-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.timing-summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.timing-summary-head{align-items:flex-start;flex-direction:column;gap:4px}}
  `;
  document.head.appendChild(style);

  let timingRows = new Map();
  let currentDetailRow = null;

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
    return `<section id="timing-summary" class="timing-summary" aria-label="Promoter activity and timing">
      <div class="timing-summary-head"><strong>Promoter activity &amp; timing</strong><span>Descriptive entry timing — does not change RYB Score</span></div>
      <span class="timing-subhead">Current promoter activity</span>
      <div class="timing-activity-grid">
        <div><small>Promoter holding</small><b>${row.promo_holding == null ? '—' : num(row.promo_holding) + '%'}</b></div>
        <div><small>Buying value</small><b>${crMoney(row.value_cr)}</b></div>
        <div><small>Transactions</small><b>${row.num_buy_txn == null ? '—' : esc(row.num_buy_txn)}</b></div>
      </div>
      <span class="timing-subhead">Entry timing</span>
      <div class="timing-summary-grid">
        <div><small>Signal stage</small><b class="${cls}">${esc(row.signal_stage)}</b></div>
        <div><small>Freshness</small><b>${esc(row.freshness || '—')}</b></div>
        <div><small>Avg buy price</small><b>${money(row.promoter_avg_price)}</b></div>
        <div><small>CMP vs avg buy</small><b>${pct(row.cmp_vs_promoter_avg_pct)}</b></div>
        <div><small>First buy</small><b>${esc(row.first_buy_date || '—')}</b></div>
        <div><small>Latest buy</small><b>${esc(row.last_buy_date || '—')}</b></div>
        <div><small>Accumulation</small><b>${row.accumulation_days == null ? '—' : esc(row.accumulation_days + ' days')}</b></div>
        <div><small>Buys · 30D</small><b>${row.buy_txn_30d == null ? '—' : esc(row.buy_txn_30d)}</b></div>
      </div>
    </section>`;
  }

  function metric(label, value) {
    return `<div class="detail-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
  }

  function fundamentalMetrics(row) {
    return `<div class="detail-section fundamental-metrics-section"><h3>Key metrics</h3><div class="detail-metric-grid">
      ${metric('Market cap', money(row.market_cap_cr) + (row.market_cap_cr != null ? ' Cr' : ''))}
      ${metric('P/E', num(row.pe))}
      ${metric('Revenue growth', row.rev_growth_pct == null ? '—' : pct(row.rev_growth_pct))}
      ${metric('PAT growth', row.pat_growth_pct == null ? '—' : pct(row.pat_growth_pct))}
      ${metric('ROCE', row.roce_pct == null ? '—' : pct(row.roce_pct))}
      ${metric('Debt / Equity', num(row.de_ratio))}
    </div></div>`;
  }

  function removeOverviewFundamentals() {
    document.querySelectorAll('#detail-panel .detail-section').forEach(section => {
      const heading = section.querySelector('h3');
      if (heading && heading.textContent.trim() === 'Key fundamentals') section.remove();
    });
  }

  function syncDetailPanel() {
    const panel = document.querySelector('#detail-panel');
    const active = document.querySelector('.detail-tab.is-active')?.dataset.detailTab;
    if (!panel || !active) return;
    if (active === 'overview') {
      removeOverviewFundamentals();
      return;
    }
    if (active === 'fundamentals' && currentDetailRow && !panel.querySelector('.fundamental-metrics-section')) {
      panel.insertAdjacentHTML('afterbegin', fundamentalMetrics(currentDetailRow));
    }
  }

  async function decorateDetail(symbol) {
    try {
      const res = await fetch(`/api/scan/${date}/stock/${encodeURIComponent(symbol)}`, {headers:{'Accept':'application/json'}});
      if (!res.ok) return;
      const row = await res.json();
      currentDetailRow = row;
      const content = document.querySelector('#detail-content');
      const priceGrid = document.querySelector('#detail-price-grid');
      if (!content || !priceGrid) return;

      // Overview keeps only market-price context; promoter information is consolidated below.
      priceGrid.innerHTML = `
        <div class="detail-metric"><span>CMP</span><strong>${money(row.last_price)}</strong></div>
        <div class="detail-metric"><span>Reference price</span><strong>${money(row.avg_price)}</strong></div>
        <div class="detail-metric"><span>vs reference</span><strong>${pct(row.price_diff_pct)}</strong></div>`;

      document.querySelector('#timing-summary')?.remove();
      priceGrid.insertAdjacentHTML('afterend', timingPanel(row));
      syncDetailPanel();
    } catch (_) { /* core detail view remains authoritative */ }
  }

  const cardsObserver = new MutationObserver(decorateCards);
  const cards = document.querySelector('#stock-cards');
  if (cards) cardsObserver.observe(cards, {childList:true});

  const detailPanel = document.querySelector('#detail-panel');
  if (detailPanel) {
    const observer = new MutationObserver(syncDetailPanel);
    observer.observe(detailPanel, {childList:true,subtree:true});
  }

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
