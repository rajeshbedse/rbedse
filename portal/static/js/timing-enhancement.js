/* RYB Finserv — stock detail presentation layer
 * Descriptive only: never changes score, category, filtering or sorting.
 * DEV UI: consolidate the Overview into a single decision-oriented flow.
 */
(function () {
  'use strict';
  const root = document.querySelector('.scan-page');
  if (!root) return;
  const date = root.dataset.scanDate;
  const esc = v => String(v ?? '').replace(/[&<>'\"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));
  const finite = v => v != null && v !== '' && Number.isFinite(Number(v));
  const money = v => !finite(v) ? '—' : '₹' + Number(v).toLocaleString('en-IN', {maximumFractionDigits: 2});
  const crMoney = v => !finite(v) ? '—' : '₹' + Number(v).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' Cr';
  const num = v => !finite(v) ? '—' : Number(v).toLocaleString('en-IN', {maximumFractionDigits: 2});
  const pct = v => !finite(v) ? '—' : `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(1)}%`;
  const fmtDate = s => {
    if (!s) return '—';
    const value = String(s).trim();
    const m = value.match(/^(\d{1,2})-(\d{1,2})-(\d{4})$/);
    if (!m) return value;
    const d = new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1]));
    return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString('en-GB', {day:'2-digit', month:'short', year:'numeric'});
  };
  const stageClass = stage => ({
    'Early Accumulation':'timing-early',
    'Confirmed Accumulation':'timing-confirmed',
    'Mature — Wait for Pullback':'timing-mature',
    'Late — Poor Entry':'timing-late',
    'No Signal':'timing-none'
  }[stage] || 'timing-none');

  const style = document.createElement('style');
  style.textContent = `
    #detail-price-grid{display:none!important}
    #detail-why{display:none!important}
    .detail-decision-flow{display:flex;flex-direction:column;gap:12px;margin:0 0 14px}
    .price-context,.timing-summary{border:1px solid #dbe4ef;border-radius:14px;background:#fff;overflow:hidden}
    .flow-head{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:13px 16px;border-bottom:1px solid #e8eef5}
    .flow-head strong{font-size:.78rem;letter-spacing:.04em;text-transform:uppercase;color:#334155}
    .flow-head span{font-size:.65rem;color:#64748b}
    .price-grid{display:grid;grid-template-columns:1fr 1.35fr 1fr;align-items:stretch}
    .price-item{padding:13px 16px;min-width:0;border-left:1px solid #e8eef5}
    .price-item:first-child{border-left:0}
    .price-item small{display:block;color:#64748b;font-size:.64rem;margin-bottom:4px}
    .price-item b{display:block;color:#0f1f3d;font-size:1rem;line-height:1.2}
    .price-item em{display:block;font-style:normal;color:#64748b;font-size:.62rem;margin-top:3px}
    .price-item--range b{font-size:.76rem;color:#334155}
    .price-unavailable{color:#94a3b8;font-weight:500}
    .timing-summary{background:#f8fafc}
    .timing-summary .flow-head{background:#fff}
    .timing-stage{display:flex;align-items:center;gap:8px;padding:12px 16px 9px}
    .timing-stage-label{font-size:.62rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em;font-weight:800}
    .timing-stage-value{font-size:.76rem;font-weight:800}
    .timing-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:currentColor;margin-right:5px;vertical-align:1px}
    .timing-confirmed{color:#166534!important}.timing-early{color:#15803d!important}.timing-mature{color:#a16207!important}.timing-late{color:#b91c1c!important}.timing-none{color:#64748b!important}
    .timing-section-title{padding:0 16px 7px;font-size:.62rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em;font-weight:800}
    .activity-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin:0 16px 12px;border:1px solid #e2e8f0;border-radius:10px;background:#fff}
    .activity-item{padding:10px 11px;min-width:0}.activity-item+.activity-item{border-left:1px solid #e2e8f0}
    .activity-item small,.timing-metric small{display:block;color:#64748b;font-size:.61rem;margin-bottom:3px}.activity-item b,.timing-metric b{font-size:.78rem;color:#0f1f3d}
    .timing-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0 16px;padding:0 16px 15px}
    .timing-metric{padding:8px 0;border-top:1px solid #e2e8f0;min-width:0}
    .timing-metric--emphasis b{font-size:.86rem}
    .detail-explore{display:none!important}
    .key-takeaways{display:none!important}
    .overview-market{display:none!important}
    .fundamental-metrics-section{margin-bottom:14px}
    @media(max-width:700px){
      .flow-head{padding:12px 13px}.flow-head span{font-size:.6rem}
      .price-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.price-item{padding:12px 10px}.price-item b{font-size:.9rem}
      .activity-grid{margin-left:12px;margin-right:12px}.timing-section-title{padding-left:12px;padding-right:12px}.timing-stage{padding-left:12px;padding-right:12px}.timing-metrics{padding-left:12px;padding-right:12px;grid-template-columns:repeat(2,minmax(0,1fr))}
    }
    @media(max-width:430px){.price-item small,.activity-item small,.timing-metric small{font-size:.58rem}.price-item b{font-size:.84rem}.activity-item b,.timing-metric b{font-size:.74rem}}
  `;
  document.head.appendChild(style);

  let timingRows = new Map();
  let currentDetailRow = null;
  let detailRequest = 0;

  function field(row, names) {
    for (const name of names) if (finite(row?.[name])) return Number(row[name]);
    return null;
  }

  function removeGenerated() {
    ['.detail-decision-flow','.overview-market','.timing-summary','.key-takeaways','.detail-explore'].forEach(sel => document.querySelectorAll(sel).forEach(el => el.remove()));
  }

  function timingPanel(row) {
    if (!row) return '';
    const stage = row.signal_stage || row.accumulation_stage || 'No Signal';
    const cls = stageClass(stage);
    return `<section class="timing-summary" aria-label="Promoter activity and entry timing">
      <div class="flow-head"><strong>Promoter activity &amp; timing</strong><span>Descriptive only · does not change RYB Score</span></div>
      <div class="timing-stage"><span class="timing-stage-label">Entry signal</span><b class="timing-stage-value ${cls}"><span class="timing-dot"></span>${esc(stage)}</b><span class="timing-stage-label">${esc(row.freshness || 'No freshness signal')}</span></div>
      <div class="timing-section-title">Current promoter activity</div>
      <div class="activity-grid">
        <div class="activity-item"><small>Holding</small><b>${finite(row.promo_holding) ? num(row.promo_holding)+'%' : '—'}</b></div>
        <div class="activity-item"><small>Buying value</small><b>${crMoney(row.value_cr)}</b></div>
        <div class="activity-item"><small>Transactions</small><b>${row.num_buy_txn == null ? '—' : esc(row.num_buy_txn)}</b></div>
      </div>
      <div class="timing-section-title">Entry timing</div>
      <div class="timing-metrics">
        <div class="timing-metric timing-metric--emphasis"><small>CMP vs promoter avg</small><b class="${Number(row.cmp_vs_promoter_avg_pct) >= 0 ? 'timing-confirmed' : 'timing-late'}">${pct(row.cmp_vs_promoter_avg_pct)}</b></div>
        <div class="timing-metric"><small>Avg buy price</small><b>${money(row.promoter_avg_price)}</b></div>
        <div class="timing-metric"><small>First buy</small><b>${fmtDate(row.first_buy_date)}</b></div>
        <div class="timing-metric"><small>Latest buy</small><b>${fmtDate(row.last_buy_date)}</b></div>
        <div class="timing-metric"><small>Accumulation</small><b>${row.accumulation_days == null ? '—' : esc(row.accumulation_days+' days')}</b></div>
        <div class="timing-metric"><small>Buys · 30D</small><b>${row.buy_txn_30d == null ? '—' : esc(row.buy_txn_30d)}</b></div>
      </div>
    </section>`;
  }

  function priceContext(row) {
    const cmp = Number(row.last_price);
    const high = field(row, ['week52_high','week_52_high','fifty_two_week_high','fiftyTwoWeekHigh','52_week_high','52WeekHigh']);
    const low = field(row, ['week52_low','week_52_low','fifty_two_week_low','fiftyTwoWeekLow','52_week_low','52WeekLow']);
    let range = '<span class="price-unavailable">52W range unavailable</span>';
    if (high != null && low != null && high > low && Number.isFinite(cmp)) {
      const pos = Math.max(0, Math.min(100, ((cmp-low)/(high-low))*100));
      range = `<span>${money(low)} — ${money(high)}</span><div class="reference-bar" aria-hidden="true"><span style="left:${pos.toFixed(1)}%"></span></div><em>CMP at ${pos.toFixed(0)}% of range</em>`;
    }
    return `<section class="price-context" aria-label="Price context"><div class="flow-head"><strong>Price context</strong><span>Where the stock trades today</span></div><div class="price-grid">
      <div class="price-item"><small>Current price</small><b>${money(row.last_price)}</b></div>
      <div class="price-item price-item--range"><small>52-week range</small><b>${range}</b></div>
      <div class="price-item"><small>RYB Score</small><b>${finite(row.score) ? esc(row.score)+'/100' : '—'}</b><em>${esc(row.category || 'Research candidate')}</em></div>
    </div></section>`;
  }

  function decisionFlow(row) {
    return `<div class="detail-decision-flow">${priceContext(row)}${timingPanel(row)}</div>`;
  }

  function fundamentalMetrics(row) {
    const metric = (label, value) => `<div class="detail-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
    return `<div class="detail-section fundamental-metrics-section"><h3>Key metrics</h3><div class="detail-metric-grid">${metric('Market cap', finite(row.market_cap_cr) ? money(row.market_cap_cr)+' Cr' : '—')}${metric('P/E', num(row.pe))}${metric('Revenue growth', finite(row.rev_growth_pct) ? pct(row.rev_growth_pct) : '—')}${metric('PAT growth', finite(row.pat_growth_pct) ? pct(row.pat_growth_pct) : '—')}${metric('ROCE', finite(row.roce_pct) ? pct(row.roce_pct) : '—')}${metric('Debt / Equity', num(row.de_ratio))}</div></div>`;
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
    if (active === 'overview') { removeOverviewFundamentals(); return; }
    if (active === 'fundamentals' && currentDetailRow && !panel.querySelector('.fundamental-metrics-section')) panel.insertAdjacentHTML('afterbegin', fundamentalMetrics(currentDetailRow));
  }

  async function decorateDetail(symbol) {
    const request = ++detailRequest;
    try {
      const res = await fetch(`/api/scan/${date}/stock/${encodeURIComponent(symbol)}`, {headers:{'Accept':'application/json'}});
      if (!res.ok) return;
      const row = await res.json();
      if (request !== detailRequest || String(row.symbol || '').toUpperCase() !== String(symbol).toUpperCase()) return;
      currentDetailRow = row;
      const priceGrid = document.querySelector('#detail-price-grid');
      const why = document.querySelector('#detail-why');
      const panel = document.querySelector('#detail-panel');
      if (!priceGrid || !why || !panel) return;
      removeGenerated();
      priceGrid.style.display = 'none';
      why.insertAdjacentHTML('afterend', decisionFlow(row));
      removeOverviewFundamentals();
      syncDetailPanel();
    } catch (_) {}
  }

  function decorateCards() {
    document.querySelectorAll('#stock-cards .stock-card').forEach(card => {
      if (card.querySelector('.timing-badge')) return;
      const row = timingRows.get(String(card.dataset.symbol || '').toUpperCase());
      if (!row?.timing_stage) return;
      const footer = card.querySelector('.research-card-footer');
      if (!footer) return;
      const badge = document.createElement('span');
      badge.className = `timing-badge ${stageClass(row.timing_stage)}`;
      badge.innerHTML = `<span class="timing-dot" aria-hidden="true"></span>${esc(row.timing_stage)}`;
      footer.insertBefore(badge, footer.firstChild);
    });
  }

  async function loadTimingRows() {
    try {
      const view = document.querySelector('.scan-tab.is-active')?.dataset.view || 'shortlist';
      const res = await fetch(`/api/scan/${date}/summary?view=${encodeURIComponent(view)}`, {headers:{'Accept':'application/json'}});
      if (!res.ok) return;
      const data = await res.json();
      timingRows = new Map((data.rows || []).map(r => [String(r.symbol || '').toUpperCase(), r]));
      decorateCards();
    } catch (_) {}
  }

  const cards = document.querySelector('#stock-cards');
  if (cards) new MutationObserver(decorateCards).observe(cards, {childList:true});

  const detailPanel = document.querySelector('#detail-panel');
  if (detailPanel) new MutationObserver(syncDetailPanel).observe(detailPanel, {childList:true,subtree:true});

  const title = document.querySelector('#detail-title');
  if (title) new MutationObserver(() => {
    const symbol = title.textContent.trim();
    currentDetailRow = null;
    detailRequest += 1;
    removeGenerated();
    document.querySelector('#detail-price-grid')?.style.removeProperty('display');
    if (symbol) decorateDetail(symbol);
  }).observe(title, {childList:true,characterData:true,subtree:true});

  document.querySelectorAll('.scan-tab').forEach(tab => tab.addEventListener('click', () => setTimeout(loadTimingRows, 0)));
  loadTimingRows();
})();
