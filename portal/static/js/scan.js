/* RYB Finserv — scan UX v4: robust stock detail + executive overview */
(function () {
  'use strict';
  const root = document.querySelector('.scan-page');
  if (!root) return;
  const date = root.dataset.scanDate;
  const $ = (s, c = document) => c.querySelector(s);
  const $$ = (s, c = document) => Array.from(c.querySelectorAll(s));
  const esc = v => String(v ?? '').replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
  const money = v => v == null || v === '' || !Number.isFinite(Number(v)) ? '—' : '₹' + Number(v).toLocaleString('en-IN', {maximumFractionDigits: 2});
  const num = v => v == null || v === '' || !Number.isFinite(Number(v)) ? '—' : Number(v).toLocaleString('en-IN', {maximumFractionDigits: 2});
  const pct = v => v == null || v === '' || !Number.isFinite(Number(v)) ? '—' : `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(1)}%`;
  const crMoney = v => v == null || v === '' || !Number.isFinite(Number(v)) ? '—' : '₹' + Number(v).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' Cr';
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
    return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString('en-GB', {day:'2-digit', month:'short', year:'numeric'});
  };
  const parseDMY = value => {
    if (!value) return 0;
    const p = String(value).split('-');
    if (p.length !== 3) return 0;
    const t = new Date(Number(p[2]), Number(p[1]) - 1, Number(p[0])).getTime();
    return Number.isFinite(t) ? t : 0;
  };

  let state = { view: 'shortlist', rows: [], search: '', band: 'all', category: 'all', sort: 'date-desc' };
  let lastFocused = null;
  let detailAbort = null;

  function injectDetailStyles() {
    if ($('#ryb-detail-v4-style')) return;
    const style = document.createElement('style');
    style.id = 'ryb-detail-v4-style';
    style.textContent = `
      .overview-score-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:.55rem;margin-top:.75rem}
      .overview-score-card{border:1px solid #e5e7eb;border-radius:12px;padding:.75rem;background:#fff;min-width:0}
      .overview-score-card .ov-label{display:block;font-size:.68rem;color:#64748b;font-weight:750;text-transform:uppercase;letter-spacing:.05em}
      .overview-score-card .ov-value{display:flex;align-items:baseline;gap:.18rem;margin-top:.22rem}
      .overview-score-card .ov-value strong{font-size:1.15rem}.overview-score-card .ov-value span{font-size:.68rem;color:#94a3b8}
      .overview-score-card .ov-bar{height:5px;border-radius:99px;background:#edf0f4;margin-top:.55rem;overflow:hidden}.overview-score-card .ov-bar i{display:block;height:100%;width:var(--ov);background:#1f4b8f;border-radius:99px}
      .overview-score-card.risk .ov-bar i{background:#2e7d6b}.overview-score-card.risk.has-risk .ov-bar i{background:#b5474d}
      .overview-score-card.risk .ov-caption{color:#2e7d6b}.overview-score-card.risk.has-risk .ov-caption{color:#b5474d}
      .ov-caption{display:block;font-size:.65rem;margin-top:.35rem;font-weight:700}
      .overview-two-col{display:grid;grid-template-columns:1fr 1fr;gap:.75rem;margin-top:1rem}
      .overview-subcard{border:1px solid #e5e7eb;border-radius:12px;padding:.85rem;background:#fff}.overview-subcard h4{font-size:.82rem;margin:0}.overview-subcard p{font-size:.72rem;color:#64748b;margin:.15rem 0 .65rem}
      .overview-signal{display:flex;gap:.5rem;align-items:flex-start;padding:.48rem .55rem;border-radius:9px;background:#f8fafc;margin-top:.4rem}.overview-signal .ov-icon{width:20px;height:20px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex:0 0 20px;font-size:.7rem;font-weight:900;background:#dcfce7;color:#15803d}.overview-signal.risk .ov-icon{background:#fee2e2;color:#b5474d}.overview-signal strong{font-size:.72rem;display:block}.overview-signal small{display:block;color:#64748b;font-size:.65rem;line-height:1.3;margin-top:.08rem}
      .overview-fund-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem;margin-top:.7rem}.overview-fund{padding:.65rem .7rem;border:1px solid #eef2f7;border-radius:10px}.overview-fund span{display:block;color:#64748b;font-size:.65rem}.overview-fund strong{display:block;margin-top:.12rem;font-size:.78rem}
      .detail-fallback{padding:.8rem;border:1px solid #e5e7eb;border-radius:10px;background:#f8fafc;color:#64748b;font-size:.75rem}
      @media(max-width:760px){.overview-score-grid{grid-template-columns:repeat(2,1fr)}.overview-two-col{grid-template-columns:1fr}.overview-fund-grid{grid-template-columns:repeat(2,1fr)}}
    `;
    document.head.appendChild(style);
  }

  async function getJSON(url, signal) {
    const res = await fetch(url, {headers:{'Accept':'application/json'}, signal});
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (!data || typeof data !== 'object') throw new Error('Invalid JSON response');
    return data;
  }

  function visibleRows() {
    let rows = state.rows.slice();
    const q = state.search.toLowerCase();
    if (q) rows = rows.filter(r => `${r.symbol} ${r.company}`.toLowerCase().includes(q));
    if (state.band !== 'all') rows = rows.filter(r => state.band === 'below' ? Number(r.price_diff_pct) < 0 : r.band === state.band);
    if (state.category !== 'all') rows = rows.filter(r => r.category === state.category);
    const [field, direction] = state.sort.split('-');
    rows.sort((a,b) => {
      let av,bv;
      if(field==='score'){av=a.score??-Infinity;bv=b.score??-Infinity}
      else if(field==='value'){av=a.value_cr??-Infinity;bv=b.value_cr??-Infinity}
      else if(field==='diff'){av=a.price_diff_pct??-Infinity;bv=b.price_diff_pct??-Infinity}
      else if(field==='symbol'){av=a.symbol||'';bv=b.symbol||''}
      else {av=parseDMY(a.acq_to_dt);bv=parseDMY(b.acq_to_dt)}
      return typeof av==='string' ? (direction==='asc'?av.localeCompare(bv):bv.localeCompare(av)) : (direction==='asc'?av-bv:bv-av);
    });
    return rows;
  }

  function stockCard(r) {
    const cls=categoryClass(r.category), diffCls=Number(r.price_diff_pct)<0?'negative':'positive';
    return `<article class="stock-card research-card ${r.is_shortlisted?'is-shortlisted':''}" data-symbol="${esc(r.symbol)}"><button class="stock-card-main research-card-main" type="button" data-stock="${esc(r.symbol)}" aria-label="View analysis for ${esc(r.symbol)}"><div class="research-card-head"><div class="research-card-identity"><div class="research-card-symbol">${esc(r.symbol)}</div><div class="stock-company">${esc(r.company)}</div></div><div class="research-card-decision"><div class="stock-score ${scoreClass(r.score)}">${r.score??'—'}<small>/100</small></div><span class="table-category category-${cls}"><span class="category-dot category-dot--${cls}"></span>${esc(r.category||'Unclassified')}</span></div></div>${scoreMeter(r.score)}<div class="research-card-evidence"><div><span>CMP</span><strong>${money(r.last_price)}</strong></div><div><span>Reference</span><strong>${money(r.avg_price)}</strong></div><div><span>vs Reference</span><strong class="${diffCls}">${pct(r.price_diff_pct)}</strong></div><div><span>Promoter</span><strong>${r.promo_holding==null?'—':num(r.promo_holding)+'%'}</strong></div><div><span>Buying</span><strong>${crMoney(r.value_cr)}</strong></div><div><span>Transactions</span><strong>${r.num_buy_txn||0}</strong></div></div><div class="research-card-footer"><span>Latest buying: <strong>${fmtDate(r.acq_to_dt)}</strong></span><span class="view-link">View analysis <span aria-hidden="true">→</span></span></div></button></article>`;
  }

  function tableRow(r) {
    const cls=categoryClass(r.category), diffCls=Number(r.price_diff_pct)<0?'negative':'positive';
    return `<tr class="${r.is_shortlisted?'is-shortlisted':''}"><td><div class="table-stock"><span class="stock-symbol">${esc(r.symbol)}</span><span>${esc(r.company)}</span></div></td><td><div class="table-score-wrap"><span class="table-score ${scoreClass(r.score)}">${r.score??'—'}</span>${scoreMeter(r.score,true)}</div></td><td><span class="table-category category-${cls}">${esc(r.category||'—')}</span></td><td>${money(r.last_price)}</td><td>${money(r.avg_price)}</td><td class="${diffCls}">${pct(r.price_diff_pct)}</td><td>${r.promo_holding==null?'—':num(r.promo_holding)+'%'}</td><td>${crMoney(r.value_cr)}</td><td>${fmtDate(r.acq_to_dt)}</td><td><button class="view-stock-btn" type="button" data-stock="${esc(r.symbol)}">View →</button></td></tr>`;
  }

  function render() {
    const rows=visibleRows();
    $('#scan-error').hidden=true; $('#result-count').textContent=`${rows.length} stock${rows.length===1?'':'s'}`; $('#result-note').textContent=rows.length!==state.rows.length?` · ${state.rows.length} total`:'';
    $('#stock-cards').innerHTML=rows.map(stockCard).join(''); $('#scan-tbody').innerHTML=rows.map(tableRow).join('');
    $('#scan-empty').hidden=rows.length!==0; $('#stock-cards').hidden=rows.length===0; $('.desktop-table-wrap').hidden=rows.length===0;
    $$('#stock-cards [data-stock], #scan-tbody [data-stock]').forEach(b=>b.addEventListener('click',()=>openDetail(b.dataset.stock))); updateFilterCount();
  }

  function updateFilterCount(){const n=(state.band!=='all'?1:0)+(state.category!=='all'?1:0);$('#filter-count').hidden=n===0;$('#filter-count').textContent=n;}

  async function loadView(view){
    state.view=view; $('#scan-loading').hidden=false; $('#scan-error').hidden=true; $('#stock-cards').hidden=true; $('.desktop-table-wrap').hidden=true;
    try{const data=await getJSON(`/api/scan/${date}/summary?view=${view}`);state.rows=Array.isArray(data.rows)?data.rows:[];render();}
    catch(e){console.error(e);$('#scan-error').hidden=false;$('#result-count').textContent='Unable to load';}
    finally{$('#scan-loading').hidden=true;}
  }

  function setFilter(group,value){state[group]=value;$$(`.filter-option[data-filter="${group}"]`).forEach(b=>b.classList.toggle('is-active',b.dataset.value===value));}
  $$('.scan-tab').forEach(tab=>tab.addEventListener('click',()=>{$$('.scan-tab').forEach(t=>{t.classList.remove('is-active');t.setAttribute('aria-selected','false')});tab.classList.add('is-active');tab.setAttribute('aria-selected','true');state.search='';$('#scan-search').value='';$('#clear-search').hidden=true;loadView(tab.dataset.view);}));
  $('#scan-search').addEventListener('input',e=>{state.search=e.target.value.trim();$('#clear-search').hidden=!state.search;render();});
  $('#clear-search').addEventListener('click',()=>{$('#scan-search').value='';state.search='';$('#clear-search').hidden=true;render();$('#scan-search').focus();});
  $('#scan-sort').value=state.sort; $('#scan-sort').addEventListener('change',e=>{state.sort=e.target.value;render();});
  $$('.filter-option').forEach(b=>b.addEventListener('click',()=>setFilter(b.dataset.filter,b.dataset.value)));
  $('#filter-toggle').addEventListener('click',()=>{const open=$('#filter-toggle').getAttribute('aria-expanded')==='true';$('#filter-toggle').setAttribute('aria-expanded',String(!open));$('#filter-sheet').hidden=open;});
  $('#filter-close').addEventListener('click',()=>{$('#filter-toggle').setAttribute('aria-expanded','false');$('#filter-sheet').hidden=true;});
  $('#filter-apply').addEventListener('click',()=>{$('#filter-toggle').setAttribute('aria-expanded','false');$('#filter-sheet').hidden=true;render();});
  $('#filter-reset').addEventListener('click',()=>{setFilter('band','all');setFilter('category','all');render();});
  $('#empty-reset').addEventListener('click',()=>{setFilter('band','all');setFilter('category','all');state.search='';$('#scan-search').value='';render();});

  function signalList(items, risk=false){
    return (items||[]).map(s=>{
      const danger=risk && !!s.triggered;
      const safe=risk ? !s.triggered : !!s.triggered;
      const cls=safe?'on':'off';
      return `<li class="signal ${cls}${danger?' risk-active':''}"><span>${safe?'✓':'×'}</span><div><strong>${esc(s.label)}</strong><small>${esc(s.note||'')}</small></div></li>`;
    }).join('');
  }
  function metric(label,value,note=''){return `<div class="detail-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong>${note?`<small>${esc(note)}</small>`:''}</div>`;}

  function pillarScore(value,max,label,risk=false){
    if(value==null || value==='') return `<div class="overview-score-card${risk?' risk':''}"><span class="ov-label">${esc(label)}</span><div class="ov-value"><strong>—</strong><span>/ ${max}</span></div><div class="ov-bar"><i style="--ov:0%"></i></div><span class="ov-caption">Not available</span></div>`;
    const n=Number(value), ratio=Math.max(0,Math.min(1,risk?1-Math.max(0,n)/max:n/max));
    const hasRisk=risk && Number(n)>0;
    const display=risk ? Math.abs(n) : n;
    return `<div class="overview-score-card${risk?' risk':''}${hasRisk?' has-risk':''}"><span class="ov-label">${esc(label)}</span><div class="ov-value"><strong>${display}</strong><span>/ ${max}${risk?' risk':''}</span></div><div class="ov-bar"><i style="--ov:${ratio*100}%"></i></div><span class="ov-caption">${risk?(hasRisk?'Risk deduction':'No risk deduction'):'Contribution'}</span></div>`;
  }

  function overviewSignalItems(row){
    const positive=[...(row.promo_signals||[]),...(row.fund_signals||[]),...(row.tech_signals||[])].filter(s=>s.triggered).slice(0,4);
    const risks=(row.risk_signals||[]).filter(s=>s.triggered);
    return {positive,risks};
  }

  function overviewPanel(row){
    const {positive,risks}=overviewSignalItems(row);
    const score=Number(row.score);
    const strengths=positive.length?positive.map(s=>`<div class="overview-signal"><span class="ov-icon">✓</span><div><strong>${esc(s.label)}</strong><small>${esc(s.note||'Signal triggered')}</small></div></div>`).join(''):`<div class="detail-fallback">No positive signals were triggered.</div>`;
    const riskHtml=risks.length?risks.map(s=>`<div class="overview-signal risk"><span class="ov-icon">!</span><div><strong>${esc(s.label)}</strong><small>${esc(s.note||'Risk condition detected')}</small></div></div>`).join(''):`<div class="overview-signal"><span class="ov-icon">✓</span><div><strong>No active risk deduction</strong><small>The risk checks currently do not reduce the RYB score.</small></div></div>`;
    return `<div class="detail-section"><h3>Score composition</h3><p style="margin:.15rem 0 0;color:#64748b;font-size:.72rem">How the ${Number.isFinite(score)?score:'current'} RYB Score is built across the four pillars.</p><div class="overview-score-grid">${pillarScore(row.score_promo,25,'Promoter')}${pillarScore(row.score_fund,35,'Fundamentals')}${pillarScore(row.score_tech,30,'Technical')}${pillarScore(row.score_risk,10,'Risk',true)}</div></div>
      <div class="overview-two-col"><div class="overview-subcard"><h4>What supports the setup</h4><p>Signals contributing positively to the current view.</p>${strengths}</div><div class="overview-subcard"><h4>What to watch</h4><p>Only active risk conditions are shown here.</p>${riskHtml}</div></div>
      <div class="detail-section"><h3>Key fundamentals</h3><div class="overview-fund-grid">${metric('Market cap',row.market_cap_cr!=null?money(row.market_cap_cr)+' Cr':'—')}${metric('P/E',num(row.pe))}${metric('Revenue growth',row.rev_growth_pct==null?'—':pct(row.rev_growth_pct))}${metric('PAT growth',row.pat_growth_pct==null?'—':pct(row.pat_growth_pct))}${metric('ROCE',row.roce_pct==null?'—':pct(row.roce_pct))}${metric('Debt / Equity',num(row.de_ratio))}</div></div>`;
  }

  function detailPanel(row,tab){
    if(tab==='overview') return overviewPanel(row);
    if(tab==='transactions'){
      const trades=row.trades||[];
      return `<div class="detail-section"><div class="section-heading-row"><div><h3>Promoter buying</h3><span>${trades.length} transaction${trades.length===1?'':'s'}</span></div></div>${trades.length?`<div class="transaction-list">${trades.map(t=>`<article class="transaction-card"><div><strong>${esc(t['Name of Person']||'Promoter')}</strong><span>${esc(t['Category of Person']||'')}</span></div><div class="transaction-grid"><div><small>Shares</small><strong>${num(t['Securities Acquired/Disposed (No.)'])}</strong></div><div><small>Value</small><strong>${money(t['Securities Acquired/Disposed (Value)']?Number(String(t['Securities Acquired/Disposed (Value)']).replace(/,/g,'')):null)}</strong></div><div><small>Post holding</small><strong>${esc(t['Securities Held Post (%)']||'—')}</strong></div><div><small>Date</small><strong>${esc(t['Date To']||t['Date From']||'—')}</strong></div></div>${t['Details URL']?`<a href="${esc(t['Details URL'])}" target="_blank" rel="noopener noreferrer">View NSE filing ↗</a>`:''}</article>`).join('')}</div>`:'<div class="empty-detail">No transaction details available.</div>'}</div>`;
    }
    const groups={promoter:row.promo_signals,fundamentals:row.fund_signals,technical:row.tech_signals,risk:row.risk_signals};
    const title=tab==='fundamentals'?'Fundamental signals':tab==='technical'?'Technical signals':tab==='risk'?'Risk signals':'Promoter signals';
    const empty=tab==='risk'?'<div class="detail-fallback">No active risk deductions. A green check means the risk condition is clear.</div>':'<div class="detail-fallback">No signals are available for this section.</div>';
    const list=signalList(groups[tab],tab==='risk');
    return `<div class="detail-section"><h3>${title}</h3>${list?`<ul class="signal-list">${list}</ul>`:empty}</div>`;
  }

  function populateDetail(row, fallback=false){
    $('#detail-loading').hidden=true; $('#detail-content').hidden=false;
    $('#detail-title').textContent=row.symbol||'—'; $('#detail-company').textContent=row.company||'';
    $('#detail-category').textContent=row.category||'Research candidate'; $('#detail-category').className=`detail-category category-${categoryClass(row.category)}`;
    $('#detail-score').textContent=row.score??'—'; $('#detail-score').className=scoreClass(row.score); $('#detail-score-meter').innerHTML=scoreMeter(row.score);
    $('#detail-nse').href=`https://www.nseindia.com/get-quotes/equity?symbol=${encodeURIComponent(row.symbol||'')}`;
    const diffCls=Number(row.price_diff_pct)<0?'negative':'positive';
    $('#detail-price-grid').innerHTML=`${metric('CMP',money(row.last_price))}${metric('Promoter reference',money(row.avg_price))}${metric('vs reference',pct(row.price_diff_pct))}${metric('Promoter holding',row.promo_holding==null?'—':num(row.promo_holding)+'%')}${metric('Buying value',crMoney(row.value_cr))}${metric('Transactions',row.num_buy_txn||0)}`;
    const positives=overviewSignalItems(row).positive;
    $('#detail-why').innerHTML=`<div><span class="why-eyebrow">WHY THIS STOCK?</span><strong>${esc(row.category||'Research candidate')}</strong></div><ul>${positives.slice(0,4).map(s=>`<li>✓ ${esc(s.label)}</li>`).join('')||'<li>Analysis available in the sections below.</li>'}</ul>`;
    $$('.detail-tab').forEach(t=>{t.classList.toggle('is-active',t.dataset.detailTab==='overview');t.setAttribute('aria-selected',t.dataset.detailTab==='overview'?'true':'false');});
    $('#detail-panel').innerHTML=detailPanel(row,'overview');
    $$('.detail-tab').forEach(t=>t.onclick=()=>{$$('.detail-tab').forEach(x=>{x.classList.remove('is-active');x.setAttribute('aria-selected','false')});t.classList.add('is-active');t.setAttribute('aria-selected','true');$('#detail-panel').innerHTML=detailPanel(row,t.dataset.detailTab);});
    if(fallback){$('#detail-panel').insertAdjacentHTML('afterbegin','<div class="detail-fallback" style="margin-bottom:.75rem">Detailed signal data could not be loaded from the analysis endpoint. The summary data is shown below; please refresh to retry the full analysis.</div>');}
  }

  async function openDetail(symbol){
    lastFocused=document.activeElement;
    const modal=$('#stock-modal'); modal.hidden=false; modal.setAttribute('aria-hidden','false'); document.body.classList.add('modal-open');
    injectDetailStyles();
    $('#detail-loading').hidden=false; $('#detail-loading').textContent='Loading analysis…'; $('#detail-content').hidden=true; $('#detail-title').textContent=symbol; $('#detail-panel').innerHTML='';
    if(detailAbort) detailAbort.abort(); detailAbort=new AbortController();
    try{
      const row=await getJSON(`/api/scan/${date}/stock/${encodeURIComponent(symbol)}`,detailAbort.signal);
      populateDetail(row,false);
    }catch(e){
      if(e.name==='AbortError') return;
      console.error('Stock detail load failed:',e);
      try{
        const data=await getJSON(`/api/scan/${date}/summary?view=candidates`,detailAbort.signal);
        const row=(data.rows||[]).find(r=>String(r.symbol).toUpperCase()===String(symbol).toUpperCase());
        if(!row) throw new Error('Stock not found in summary');
        populateDetail(row,true);
      }catch(fallbackError){
        console.error('Stock detail fallback failed:',fallbackError);
        $('#detail-loading').textContent='Unable to load this stock analysis. Please try again.';
      }
    }
  }
  function closeDetail(){if(detailAbort) detailAbort.abort();$('#stock-modal').hidden=true;$('#stock-modal').setAttribute('aria-hidden','true');document.body.classList.remove('modal-open');if(lastFocused)lastFocused.focus();}
  $('#detail-back').addEventListener('click',closeDetail); $('[data-close-modal]').addEventListener('click',closeDetail);
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#stock-modal').hidden)closeDetail();});

  loadView('shortlist');
})();