/* RYB Finserv — promoter timing presentation layer
 * Descriptive only: this file never changes score, category, filtering or sorting.
 * DEV refinement: Overview is a compact decision dashboard; detailed metrics remain
 * in their specialist tabs. Optional 52-week price fields are presentation-only.
 */
(function () {
  'use strict';
  const root = document.querySelector('.scan-page');
  if (!root) return;
  const date = root.dataset.scanDate;
  const esc = v => String(v ?? '').replace(/[&<>\'\"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;',"\"":'&quot;'}[c]));
  const money = v => v == null || v === '' || !Number.isFinite(Number(v)) ? '—' : '₹' + Number(v).toLocaleString('en-IN', {maximumFractionDigits: 2});
  const crMoney = v => v == null || v === '' || !Number.isFinite(Number(v)) ? '—' : '₹' + Number(v).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' Cr';
  const num = v => v == null || v === '' || !Number.isFinite(Number(v)) ? '—' : Number(v).toLocaleString('en-IN', {maximumFractionDigits: 2});
  const pct = v => v == null || v === '' || !Number.isFinite(Number(v)) ? '—' : `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(1)}%`;
  const fmtDate = s => {
    if (!s) return '—';
    const value = String(s).trim();
    const m = value.match(/^(\d{1,2})-(\d{1,2})-(\d{4})$/);
    if (!m) return value;
    const d = new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1]));
    return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString('en-GB', {day:'2-digit', month:'short', year:'numeric'});
  };
  const stageClass = stage => ({
    'Early Accumulation': 'timing-early',
    'Confirmed Accumulation': 'timing-confirmed',
    'Mature — Wait for Pullback': 'timing-mature',
    'Late — Poor Entry': 'timing-late',
    'No Signal': 'timing-none'
  }[stage] || 'timing-none');

  const style = document.createElement('style');
  style.textContent = `
    .overview-market{margin:0 0 14px;padding:18px 20px;border:1px solid #e2e8f0;border-radius:14px;background:#fff}
    .overview-market-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}.overview-market-head strong{font-size:.78rem;letter-spacing:.05em;text-transform:uppercase;color:#475569}.overview-market-head span{font-size:.72rem;color:#64748b}
    .overview-market-grid{display:grid;grid-template-columns:1fr 1.5fr 1fr 1fr;align-items:center}.overview-market-item{min-width:0;padding:0 18px;border-left:1px solid #e2e8f0}.overview-market-item:first-child{padding-left:0;border-left:0}.overview-market-item:last-child{padding-right:0}.overview-market-item small{display:block;color:#64748b;font-size:.7rem;margin-bottom:5px}.overview-market-item b{font-size:1.12rem;color:#0f1f3d}.overview-market-up b{color:#15803d}
    .range-value{display:flex;justify-content:space-between;gap:8px;font-size:.68rem;color:#64748b;margin-bottom:4px}.range-track{position:relative;height:7px;border-radius:999px;background:#e2e8f0}.range-fill{position:absolute;left:0;top:0;height:100%;border-radius:999px;background:#bfdbfe}.range-marker{position:absolute;top:50%;width:13px;height:13px;border:2px solid #fff;border-radius:50%;background:#1a56db;box-shadow:0 1px 3px rgba(15,31,61,.25);transform:translate(-50%,-50%)}.range-position{margin-top:5px;font-size:.68rem;color:#64748b}
    .why-card{margin-bottom:14px}.why-card .detail-section{margin:0}
    .timing-summary{margin:0 0 14px;padding:18px 20px;border:1px solid #dbe4ef;border-radius:14px;background:#f8fafc}.timing-summary-head{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:14px}.timing-summary-head strong{font-size:1rem;color:#0f1f3d}.timing-summary-head span{font-size:.7rem;color:#64748b}.timing-subhead{display:block;margin:12px 0 8px;color:#64748b;font-size:.68rem;font-weight:800;letter-spacing:.05em;text-transform:uppercase}.timing-activity-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:5px}.timing-summary-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.timing-summary-grid div,.timing-activity-grid div{min-width:0}.timing-summary-grid small,.timing-activity-grid small{display:block;color:#64748b;font-size:.68rem;margin-bottom:3px}.timing-summary-grid b,.timing-activity-grid b{font-size:.84rem;color:#0f1f3d}.timing-confirmed{color:#166534!important}.timing-early{color:#15803d!important}.timing-mature{color:#a16207!important}.timing-late{color:#b91c1c!important}.timing-none{color:#64748b!important}
    .timing-activity-grid{padding-bottom:14px;border-bottom:1px solid #e2e8f0}.timing-summary-grid .timing-highlight{font-size:.84rem}
    .key-takeaways{margin:0 0 14px;padding:18px 20px;border:1px solid #e2e8f0;border-radius:14px;background:#fff}.key-takeaways h3{margin:0 0 14px;font-size:1rem;color:#0f1f3d}.takeaway-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))}.takeaway{padding:0 18px;border-left:1px solid #e2e8f0}.takeaway:first-child{padding-left:0;border-left:0}.takeaway:last-child{padding-right:0}.takeaway small{display:block;color:#64748b;font-size:.68rem;font-weight:800;letter-spacing:.04em;text-transform:uppercase;margin-bottom:5px}.takeaway strong{display:block;color:#0f1f3d;font-size:.82rem;line-height:1.45;font-weight:600}
    .detail-explore{margin:0 0 10px;padding:12px 16px;border:1px solid #e2e8f0;border-radius:12px;background:#f8fafc;color:#475569;font-size:.74rem}.detail-explore strong{display:block;color:#0f1f3d;font-size:.82rem;margin-bottom:2px}.detail-explore span{line-height:1.4}
    .fundamental-metrics-section{margin-bottom:14px}
    @media(max-width:700px){.overview-market-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.overview-market-item:nth-child(3){border-left:0;padding-left:0}.overview-market-item:nth-child(3),.overview-market-item:nth-child(4){padding-top:12px;border-top:1px solid #e2e8f0}.timing-summary-head{align-items:flex-start;flex-direction:column;gap:4px}.timing-summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.takeaway-grid{grid-template-columns:1fr;gap:12px}.takeaway{padding:0;border-left:0}.takeaway + .takeaway{padding-top:12px;border-top:1px solid #e2e8f0}.detail-explore{display:none}}
    @media(max-width:430px){.overview-market{padding:15px}.overview-market-item{padding:0 10px}.overview-market-item b{font-size:1rem}.timing-summary{padding:15px}.timing-activity-grid{gap:8px}.timing-summary-grid{gap:10px}.timing-summary-grid b,.timing-activity-grid b{font-size:.78rem}}
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
    } catch (_) {}
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

  function field(row, names) {
    for (const name of names) {
      const value = row?.[name];
      if (value != null && value !== '' && Number.isFinite(Number(value))) return Number(value);
    }
    return null;
  }

  function marketSnapshot(row) {
    const high = field(row, ['week52_high','week_52_high','fifty_two_week_high','fiftyTwoWeekHigh','52_week_high','52WeekHigh']);
    const low = field(row, ['week52_low','week_52_low','fifty_two_week_low','fiftyTwoWeekLow','52_week_low','52WeekLow']);
    const cmp = Number(row.last_price);
    let range = '';
    if (high != null && low != null && high > low && Number.isFinite(cmp)) {
      const pos = Math.max(0, Math.min(100, ((cmp - low) / (high - low)) * 100));
      range = `<div class="overview-market-item"><small>52-week range</small><div class="range-value"><span>${money(low)}</span><span>${money(high)}</span></div><div class="range-track"><span class="range-fill" style="width:${pos.toFixed(1)}%"></span><span class="range-marker" style="left:${pos.toFixed(1)}%"></span></div><div class="range-position">CMP at ${pos.toFixed(0)}% of range</div></div>`;
    } else {
      range = `<div class="overview-market-item"><small>52-week range</small><b>—</b><div class="range-position">52W high / low not available in this snapshot</div></div>`;
    }
    return `<section class="overview-market" aria-label="Market snapshot"><div class="overview-market-head"><strong>Market snapshot</strong><span>Current price context</span></div><div class="overview-market-grid">
      <div class="overview-market-item"><small>CMP</small><b>${money(row.last_price)}</b></div>
      ${range}
      <div class="overview-market-item"><small>Promoter reference</small><b>${money(row.avg_price)}</b></div>
      <div class="overview-market-item overview-market-up"><small>Upside vs reference</small><b>${pct(row.price_diff_pct)}</b></div>
    </div></section>`;
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
        <div><small>CMP vs reference</small><b class="timing-highlight">${pct(row.cmp_vs_promoter_avg_pct)}</b></div>
        <div><small>First buy</small><b>${esc(row.first_buy_date || '—')}</b></div>
        <div><small>Latest buy</small><b>${esc(row.last_buy_date || '—')}</b></div>
        <div><small>Accumulation</small><b>${row.accumulation_days == null ? '—' : esc(row.accumulation_days + ' days')}</b></div>
        <div><small>Buys · 30D</small><b>${row.buy_txn_30d == null ? '—' : esc(row.buy_txn_30d)}</b></div>
      </div>
    </section>`;
  }

  function fundamentalMetrics(row) {
    const metric = (label, value) => `<div class="detail-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
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

  function takeaways(row) {
    const diff = row.cmp_vs_promoter_avg_pct ?? row.price_diff_pct;
    const stage = row.signal_stage || row.accumulation_stage || 'No Signal';
    const txns = row.num_buy_txn == null ? '—' : row.num_buy_txn;
    const first = fmtDate(row.first_buy_date);
    const latest = fmtDate(row.last_buy_date);
    const high = field(row, ['week52_high','week_52_high','fifty_two_week_high','fiftyTwoWeekHigh','52_week_high','52WeekHigh']);
    const low = field(row, ['week52_low','week_52_low','fifty_two_week_low','fiftyTwoWeekLow','52_week_low','52WeekLow']);
    const cmp = Number(row.last_price);
    let priceContext = 'Current price vs promoter reference';
    if (high != null && low != null && high > low && Number.isFinite(cmp)) {
      const pos = Math.max(0, Math.min(100, ((cmp-low)/(high-low))*100));
      priceContext = `CMP is at ${pos.toFixed(0)}% of its 52-week range`;
    }
    return `<section class="key-takeaways" aria-label="Key takeaways"><h3>Key takeaways</h3><div class="takeaway-grid">
      <div class="takeaway"><small>Valuation</small><strong>${diff == null ? 'Reference comparison unavailable' : `${pct(diff)} vs promoter reference`}</strong></div>
      <div class="takeaway"><small>Promoter intent</small><strong>${esc(stage)}${txns !== '—' ? ` · ${esc(txns)} transaction${Number(txns)===1?'':'s'}` : ''}${first !== '—' && latest !== '—' ? ` · ${first} → ${latest}` : ''}</strong></div>
      <div class="takeaway"><small>Price context</small><strong>${esc(priceContext)}</strong></div>
    </div></section>`;
  }

  function syncDetailPanel() {
    const panel = document.querySelector('#detail-panel');
    const active = document.querySelector('.detail-tab.is-active')?.dataset.detailTab;
    if (!panel || !active) return;
    if (active === 'overview') { removeOverviewFundamentals(); return; }
    if (active === 'fundamentals' && currentDetailRow && !panel.querySelector('.fundamental-metrics-section')) panel.insertAdjacentHTML('afterbegin', fundamentalMetrics(currentDetailRow));
  }

  function decorateDetail(symbol) {
    fetch(`/api/scan/${date}/stock/${encodeURIComponent(symbol)}`, {headers:{'Accept':'application/json'}})
      .then(res => res.ok ? res.json() : null)
      .then(row => {
        if (!row) return;
        currentDetailRow = row;
        const content = document.querySelector('#detail-content');
        const priceGrid = document.querySelector('#detail-price-grid');
        const why = document.querySelector('#detail-why');
        const tabs = document.querySelector('.detail-tabs');
        if (!content || !priceGrid || !why || !tabs) return;

        priceGrid.innerHTML = '';
        priceGrid.insertAdjacentHTML('afterend', marketSnapshot(row));
        document.querySelector('#timing-summary')?.remove();
        document.querySelector('.key-takeaways')?.remove();
        document.querySelector('.detail-explore')?.remove();
        document.querySelector('.detail-price-grid')?.style.setProperty('display','none');
        why.insertAdjacentHTML('afterend', timingPanel(row) + takeaways(row) + `<div class="detail-explore"><strong>Explore more details</strong><span>Fundamentals, technicals, risks and full promoter transaction history are available in the tabs below.</span></div>`);
        syncDetailPanel();
      })
      .catch(() => {});
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
      currentDetailRow = null;
      document.querySelector('#detail-panel')?.querySelector('.fundamental-metrics-section')?.remove();
      document.querySelector('.overview-market')?.remove();
      document.querySelector('#timing-summary')?.remove();
      document.querySelector('.key-takeaways')?.remove();
      document.querySelector('.detail-explore')?.remove();
      document.querySelector('.detail-price-grid')?.style.removeProperty('display');
      if (symbol) decorateDetail(symbol);
    });
    observer.observe(title, {childList:true, characterData:true, subtree:true});
  }

  document.querySelectorAll('.scan-tab').forEach(tab => tab.addEventListener('click', () => setTimeout(loadTimingRows, 0)));
  loadTimingRows();
})();
