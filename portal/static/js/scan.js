/* RYB Finserv — scan UX v3: mobile cards + lazy stock detail */
(function () {
  'use strict';
  const root = document.querySelector('.scan-page');
  if (!root) return;
  const date = root.dataset.scanDate;
  const $ = (s, c = document) => c.querySelector(s);
  const $$ = (s, c = document) => Array.from(c.querySelectorAll(s));
  const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const money = v => v == null || v === '' ? '—' : '₹' + Number(v).toLocaleString('en-IN', {maximumFractionDigits: 2});
  const num = v => v == null || v === '' ? '—' : Number(v).toLocaleString('en-IN', {maximumFractionDigits: 2});
  const pct = v => v == null || v === '' ? '—' : `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(1)}%`;
  const scoreClass = s => Number(s) >= 65 ? 'score-high' : Number(s) >= 50 ? 'score-mid' : Number(s) >= 40 ? 'score-ok' : 'score-low';
  const scoreValue = s => { const n = Number(s); return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : null; };
  const scoreMeter = (s, compact = false) => { const n = scoreValue(s); if (n == null) return ''; return `<div class="ryb-score-meter${compact ? ' ryb-score-meter--compact' : ''}" role="meter" aria-label="RYB Score" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${n}" style="--score:${n}%"><div class="ryb-score-track"><span class="ryb-score-marker"></span></div><div class="ryb-score-scale"><span>R</span><span>Y</span><span>B</span></div></div>`; };
  const categoryClass = c => ({'Strong Buy Setup':'strong-buy','Buy on Breakout':'buy-breakout','Watchlist':'watchlist','Fundamental Watch':'fund-watch','Avoid':'avoid'}[c] || '');
  const fmtDate = s => {
    if (!s) return '—';
    const value = String(s).trim();
    const m = value.match(/^(\d{1,2})-(\d{1,2})-(\d{4})$/);
    if (!m) return value;
    const d = new Date(Number(m[3]), Number(m[2]) - 1, Number(m[1]));
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleDateString('en-GB', {day:'2-digit', month:'short', year:'numeric'});
  };
  const crMoney = v => v == null || v === '' || !Number.isFinite(Number(v)) ? '—' : '₹' + Number(v).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' Cr';
  const parseDMY = value => {
    if (!value) return 0;
    const parts = String(value).split('-');
    if (parts.length !== 3) return 0;
    const day = Number(parts[0]);
    const month = Number(parts[1]);
    const year = Number(parts[2]);
    if (!day || !month || !year) return 0;
    return new Date(year, month - 1, day).getTime();
  };

  let state = { view: 'shortlist', rows: [], search: '', band: 'all', category: 'all', sort: 'date-desc' };
  let lastFocused = null;

  async function getJSON(url) {
    const res = await fetch(url, {headers: {'Accept':'application/json'}});
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  function visibleRows() {
    let rows = state.rows.slice();
    const q = state.search.toLowerCase();
    if (q) rows = rows.filter(r => `${r.symbol} ${r.company}`.toLowerCase().includes(q));
    if (state.band !== 'all') rows = rows.filter(r => state.band === 'below' ? r.price_diff_pct < 0 : r.band === state.band);
    if (state.category !== 'all') rows = rows.filter(r => r.category === state.category);
    const [field, direction] = state.sort.split('-');
    rows.sort((a, b) => {
      let av, bv;
      if (field === 'score') { av = a.score ?? -Infinity; bv = b.score ?? -Infinity; }
      else if (field === 'value') { av = a.value_cr ?? -Infinity; bv = b.value_cr ?? -Infinity; }
      else if (field === 'diff') { av = a.price_diff_pct ?? -Infinity; bv = b.price_diff_pct ?? -Infinity; }
      else if (field === 'symbol') { av = a.symbol || ''; bv = b.symbol || ''; }
      else if (field === 'date') { av = parseDMY(a.acq_to_dt); bv = parseDMY(b.acq_to_dt); }
      else { av = parseDMY(a.acq_to_dt); bv = parseDMY(b.acq_to_dt); }
      if (typeof av === 'string') return direction === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      return direction === 'asc' ? av - bv : bv - av;
    });
    return rows;
  }

  function stockCard(r) {
    const cls = categoryClass(r.category);
    const diffCls = Number(r.price_diff_pct) < 0 ? 'negative' : 'positive';
    const score = r.score ?? '—';
    return `<article class="stock-card research-card" data-symbol="${esc(r.symbol)}">
      <button class="stock-card-main research-card-main" type="button" data-stock="${esc(r.symbol)}" aria-label="View analysis for ${esc(r.symbol)}">
        <div class="research-card-head">
          <div class="research-card-identity">
            <div class="research-card-symbol">${esc(r.symbol)}</div>
            <div class="stock-company">${esc(r.company)}</div>
          </div>
          <div class="research-card-decision">
            <div class="stock-score ${scoreClass(r.score)}">${score}<small>/100</small></div>
            <span class="table-category category-${cls}"><span class="category-dot category-dot--${cls}"></span>${esc(r.category || 'Unclassified')}</span>
          </div>
        </div>

        ${scoreMeter(r.score, false)}

        <div class="research-card-evidence">
          <div><span>CMP</span><strong>${money(r.last_price)}</strong></div>
          <div><span>Reference</span><strong>${money(r.avg_price)}</strong></div>
          <div><span>vs Reference</span><strong class="${diffCls}">${pct(r.price_diff_pct)}</strong></div>
          <div><span>Promoter</span><strong>${r.promo_holding == null ? '—' : num(r.promo_holding) + '%'}</strong></div>
          <div><span>Buying</span><strong>${crMoney(r.value_cr)}</strong></div>
          <div><span>Transactions</span><strong>${r.num_buy_txn || 0}</strong></div>
        </div>

        <div class="research-card-footer">
          <span>Latest buying: <strong>${fmtDate(r.acq_to_dt)}</strong></span>
          <span class="view-link">View analysis <span aria-hidden="true">→</span></span>
        </div>
      </button>
    </article>`;
  }

  function tableRow(r) {
    const cls = categoryClass(r.category);
    const diffCls = Number(r.price_diff_pct) < 0 ? 'negative' : 'positive';
    return `<tr><td><div class="table-stock"><span class="stock-symbol">${esc(r.symbol)}</span><span>${esc(r.company)}</span></div></td><td><div class="table-score-wrap"><span class="table-score ${scoreClass(r.score)}">${r.score ?? '—'}</span>${scoreMeter(r.score, true)}</div></td><td><span class="table-category category-${cls}">${esc(r.category || '—')}</span></td><td>${money(r.last_price)}</td><td>${money(r.avg_price)}</td><td class="${diffCls}">${pct(r.price_diff_pct)}</td><td>${r.promo_holding == null ? '—' : num(r.promo_holding)+'%'}</td><td>${crMoney(r.value_cr)}</td><td>${fmtDate(r.acq_to_dt)}</td><td><button class="view-stock-btn" type="button" data-stock="${esc(r.symbol)}">View →</button></td></tr>`;
  }

  function render() {
    const rows = visibleRows();
    $('#scan-error').hidden = true;
    $('#result-count').textContent = `${rows.length} stock${rows.length === 1 ? '' : 's'}`;
    $('#result-note').textContent = rows.length !== state.rows.length ? ` · ${state.rows.length} total` : '';
    $('#stock-cards').innerHTML = rows.map(stockCard).join('');
    $('#scan-tbody').innerHTML = rows.map(tableRow).join('');
    $('#scan-empty').hidden = rows.length !== 0;
    $('#stock-cards').hidden = rows.length === 0;
    $('.desktop-table-wrap').hidden = rows.length === 0;
    $$('#stock-cards [data-stock], #scan-tbody [data-stock]').forEach(b => b.addEventListener('click', () => openDetail(b.dataset.stock)));
    updateFilterCount();
  }

  function updateFilterCount() {
    const n = (state.band !== 'all' ? 1 : 0) + (state.category !== 'all' ? 1 : 0);
    $('#filter-count').hidden = n === 0; $('#filter-count').textContent = n;
  }

  async function loadView(view) {
    state.view = view;
    $('#scan-loading').hidden = false; $('#scan-error').hidden = true; $('#stock-cards').hidden = true; $('.desktop-table-wrap').hidden = true;
    try { const data = await getJSON(`/api/scan/${date}/summary?view=${view}`); state.rows = data.rows || []; render(); }
    catch (e) { console.error(e); $('#scan-error').hidden = false; $('#result-count').textContent = 'Unable to load'; }
    finally { $('#scan-loading').hidden = true; }
  }

  function setFilter(group, value) {
    state[group] = value;
    $$(`.filter-option[data-filter="${group}"]`).forEach(b => b.classList.toggle('is-active', b.dataset.value === value));
  }

  $$('.scan-tab').forEach(tab => tab.addEventListener('click', () => {
    $$('.scan-tab').forEach(t => { t.classList.remove('is-active'); t.setAttribute('aria-selected','false'); });
    tab.classList.add('is-active'); tab.setAttribute('aria-selected','true');
    state.search = ''; $('#scan-search').value = ''; $('#clear-search').hidden = true;
    loadView(tab.dataset.view);
  }));

  $('#scan-search').addEventListener('input', e => { state.search = e.target.value.trim(); $('#clear-search').hidden = !state.search; render(); });
  $('#clear-search').addEventListener('click', () => { $('#scan-search').value = ''; state.search = ''; $('#clear-search').hidden = true; render(); $('#scan-search').focus(); });
  $('#scan-sort').value = state.sort;
  $('#scan-sort').addEventListener('change', e => { state.sort = e.target.value; render(); });
  $$('.filter-option').forEach(b => b.addEventListener('click', () => setFilter(b.dataset.filter, b.dataset.value)));
  $('#filter-toggle').addEventListener('click', () => { const open = $('#filter-toggle').getAttribute('aria-expanded') === 'true'; $('#filter-toggle').setAttribute('aria-expanded', String(!open)); $('#filter-sheet').hidden = open; });
  $('#filter-close').addEventListener('click', () => { $('#filter-toggle').setAttribute('aria-expanded','false'); $('#filter-sheet').hidden = true; });
  $('#filter-apply').addEventListener('click', () => { $('#filter-toggle').setAttribute('aria-expanded','false'); $('#filter-sheet').hidden = true; render(); });
  $('#filter-reset').addEventListener('click', () => { setFilter('band','all'); setFilter('category','all'); render(); });
  $('#empty-reset').addEventListener('click', () => { setFilter('band','all'); setFilter('category','all'); state.search=''; $('#scan-search').value=''; render(); });

  function signalList(items) {
    return (items || []).map(s => `<li class="signal ${s.triggered ? 'on' : 'off'}"><span>${s.triggered ? '✓' : '×'}</span><div><strong>${esc(s.label)}</strong><small>${esc(s.note || '')}</small></div></li>`).join('');
  }
  function metric(label, value, note='') { return `<div class="detail-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong>${note ? `<small>${esc(note)}</small>` : ''}</div>`; }
  function detailPanel(row, tab) {
    const groups = {promoter: row.promo_signals, fundamentals: row.fund_signals, technical: row.tech_signals, risk: row.risk_signals};
    if (tab === 'overview') {
      return `<div class="detail-section"><h3>Why this stock?</h3><ul class="signal-list">${signalList([...(row.promo_signals||[]).filter(s=>s.triggered).slice(0,2), ...(row.fund_signals||[]).filter(s=>s.triggered).slice(0,2), ...(row.tech_signals||[]).filter(s=>s.triggered).slice(0,1)]) || '<li>No positive signals available.</li>'}</ul></div>
      <div class="detail-section"><h3>Key fundamentals</h3><div class="detail-metric-grid">${metric('Market cap', money(row.market_cap_cr) + (row.market_cap_cr != null ? ' Cr' : ''))}${metric('P/E', num(row.pe))}${metric('Revenue growth', row.rev_growth_pct == null ? '—' : pct(row.rev_growth_pct))}${metric('PAT growth', row.pat_growth_pct == null ? '—' : pct(row.pat_growth_pct))}${metric('ROCE', row.roce_pct == null ? '—' : pct(row.roce_pct))}${metric('Debt / Equity', num(row.de_ratio))}</div></div>`;
    }
    if (tab === 'transactions') {
      const trades = row.trades || [];
      return `<div class="detail-section"><div class="section-heading-row"><div><h3>Promoter buying</h3><span>${trades.length} transaction${trades.length===1?'':'s'}</span></div></div>${trades.length ? `<div class="transaction-list">${trades.map(t=>`<article class="transaction-card"><div><strong>${esc(t['Name of Person'] || 'Promoter')}</strong><span>${esc(t['Category of Person'] || '')}</span></div><div class="transaction-grid"><div><small>Shares</small><strong>${num(t['Securities Acquired/Disposed (No.)'])}</strong></div><div><small>Value</small><strong>${money(t['Securities Acquired/Disposed (Value)'] ? Number(String(t['Securities Acquired/Disposed (Value)']).replace(/,/g,'')) : null)}</strong></div><div><small>Post holding</small><strong>${esc(t['Securities Held Post (%)'] || '—')}</strong></div><div><small>Date</small><strong>${esc(t['Date To'] || t['Date From'] || '—')}</strong></div></div>${t['Details URL'] ? `<a href="${esc(t['Details URL'])}" target="_blank" rel="noopener noreferrer">View NSE filing ↗</a>` : ''}</article>`).join('')}</div>` : '<div class="empty-detail">No transaction details available.</div>'}</div>`;
    }
    return `<div class="detail-section"><h3>${tab === 'fundamentals' ? 'Fundamental signals' : tab === 'technical' ? 'Technical signals' : 'Risk signals'}</h3><ul class="signal-list">${signalList(groups[tab])}</ul></div>`;
  }

  function openDetail(symbol) {
    lastFocused = document.activeElement;
    const modal = $('#stock-modal'); modal.hidden = false; modal.setAttribute('aria-hidden','false'); document.body.classList.add('modal-open');
    $('#detail-loading').hidden = false; $('#detail-content').hidden = true; $('#detail-title').textContent = symbol; $('#detail-panel').innerHTML = '';
    fetch(`/api/scan/${date}/stock/${encodeURIComponent(symbol)}`).then(r => { if(!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }).then(row => {
      $('#detail-loading').hidden = true; $('#detail-content').hidden = false;
      $('#detail-title').textContent = row.symbol; $('#detail-company').textContent = row.company;
      $('#detail-category').textContent = row.category || 'Research candidate'; $('#detail-category').className = `detail-category category-${categoryClass(row.category)}`;
      $('#detail-score').textContent = row.score ?? '—'; $('#detail-score').className = scoreClass(row.score);
      $('#detail-score-meter').innerHTML = scoreMeter(row.score);
      $('#detail-nse').href = `https://www.nseindia.com/get-quotes/equity?symbol=${encodeURIComponent(row.symbol)}`;
      const diffCls = Number(row.price_diff_pct) < 0 ? 'negative' : 'positive';
      $('#detail-price-grid').innerHTML = `${metric('CMP', money(row.last_price))}${metric('Promoter reference', money(row.avg_price))}${metric('vs reference', pct(row.price_diff_pct))}${metric('Promoter holding', row.promo_holding == null ? '—' : num(row.promo_holding)+'%')}${metric('Buying value', crMoney(row.value_cr))}${metric('Transactions', row.num_buy_txn || 0)}`;
      const positives = [...(row.promo_signals||[]), ...(row.fund_signals||[]), ...(row.tech_signals||[])].filter(s=>s.triggered).slice(0,5);
      $('#detail-why').innerHTML = `<div><span class="why-eyebrow">WHY THIS STOCK?</span><strong>${esc(row.category || 'Research candidate')}</strong></div><ul>${positives.map(s=>`<li>✓ ${esc(s.label)}</li>`).join('')}</ul>`;
      $$('.detail-tab').forEach(t=>{t.classList.toggle('is-active',t.dataset.detailTab==='overview');t.setAttribute('aria-selected',t.dataset.detailTab==='overview'?'true':'false');});
      $('#detail-panel').innerHTML = detailPanel(row,'overview');
      $$('.detail-tab').forEach(t=>t.onclick=()=>{ $$('.detail-tab').forEach(x=>{x.classList.remove('is-active');x.setAttribute('aria-selected','false')}); t.classList.add('is-active');t.setAttribute('aria-selected','true');$('#detail-panel').innerHTML=detailPanel(row,t.dataset.detailTab); });
      $('#detail-back').focus();
    }).catch(e => { console.error(e); $('#detail-loading').textContent = 'Unable to load this stock analysis. Please try again.'; });
  }
  function closeDetail() { $('#stock-modal').hidden=true; $('#stock-modal').setAttribute('aria-hidden','true'); document.body.classList.remove('modal-open'); if(lastFocused) lastFocused.focus(); }
  $('#detail-back').addEventListener('click', closeDetail); $('[data-close-modal]').addEventListener('click', closeDetail);
  document.addEventListener('keydown', e => { if(e.key==='Escape' && !$('#stock-modal').hidden) closeDetail(); });

  loadView('shortlist');
})();
