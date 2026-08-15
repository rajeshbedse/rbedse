/* RYB Finserv — scan.js  v2 */
(function () {
  'use strict';

  /* ── helpers ──────────────────────────────────────────────────────────────── */
  function qs(sel, ctx) { return (ctx || document).querySelector(sel); }
  function qsa(sel, ctx) { return Array.from((ctx || document).querySelectorAll(sel)); }

  function debounce(fn, ms) {
    var t;
    return function () { clearTimeout(t); t = setTimeout(fn, ms); };
  }

  /* ── tab switching — Audit §12: click + keyboard ←→ Home End ──────────────── */
  var tabBtns   = qsa('.tab-btn');
  var tabPanels = { shortlist: qs('#panel-shortlist'), candidates: qs('#panel-candidates') };

  function activateTab(btn) {
    tabBtns.forEach(function (b) {
      b.classList.remove('active');
      b.setAttribute('aria-selected', 'false');
      b.setAttribute('tabindex', '-1');
    });
    btn.classList.add('active');
    btn.setAttribute('aria-selected', 'true');
    btn.setAttribute('tabindex', '0');
    btn.focus();
    var panelId = btn.getAttribute('aria-controls');
    Object.values(tabPanels).forEach(function (p) { if (p) p.hidden = true; });
    var panel = qs('#' + panelId);
    if (panel) panel.hidden = false;
  }

  tabBtns.forEach(function (btn) {
    btn.addEventListener('click', function () { activateTab(btn); });
    btn.addEventListener('keydown', function (e) {
      var idx = tabBtns.indexOf(btn);
      if (e.key === 'ArrowRight') { e.preventDefault(); activateTab(tabBtns[(idx + 1) % tabBtns.length]); }
      if (e.key === 'ArrowLeft')  { e.preventDefault(); activateTab(tabBtns[(idx - 1 + tabBtns.length) % tabBtns.length]); }
      if (e.key === 'Home')       { e.preventDefault(); activateTab(tabBtns[0]); }
      if (e.key === 'End')        { e.preventDefault(); activateTab(tabBtns[tabBtns.length - 1]); }
    });
  });
  /* init tabindex for roving tabindex pattern */
  tabBtns.forEach(function (b, i) { b.setAttribute('tabindex', i === 0 ? '0' : '-1'); });

  /* ── generic sortable table ─────────────────────────────────────────────── */
  function initSortableTable(tableId) {
    var table = qs('#' + tableId);
    if (!table) return;
    var panel  = table.closest('[role="tabpanel"]');
    var tbody  = qs('#tbody-' + tableId.replace('table-', ''));
    if (!tbody) return;

    /* JSON data embedded in sibling <script> tag */
    var rawScript = qs('#data-' + tableId.replace('table-', ''));
    var data = [];
    if (rawScript) {
      try { data = JSON.parse(rawScript.textContent); } catch (e) { data = []; }
    }

    /*
     * Build row maps ONCE at init time, before any DOM manipulation.
     * rowByIndex : "0" → <tr data-row-index="0">   (data rows only)
     * drawerById : "trades-0" → <tr id="trades-0"> (drawer rows)
     * Both are captured before renderAll ever touches the DOM.
     */
    var rowByIndex  = {};
    var drawerById  = {};
    var rowBySymbol = {};

    qsa('tr', tbody).forEach(function (row) {
      if (row.classList.contains('trades-drawer')) {
        drawerById[row.id] = row;
      } else {
        if (row.dataset.rowIndex !== undefined) {
          rowByIndex[String(row.dataset.rowIndex)] = row;
        }
        if (row.dataset.symbol) {
          rowBySymbol[row.dataset.symbol] = row;
        }
      }
    });

    var sortState      = { col: null, dir: 1 };
    var currentSearch  = '';
    var currentBand    = 'all';
    var currentCategory = 'all';

    /* category chips — only chips that carry data-category */
    var catChips = panel ? qsa('.chip[data-category]', panel) : [];
    catChips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        catChips.forEach(function (c) { c.classList.remove('chip--active'); });
        chip.classList.add('chip--active');
        currentCategory = chip.dataset.category || 'all';
        renderAll();
      });
    });

    /* sort header clicks */
    var ths = qsa('.th-sort', table);
    ths.forEach(function (th) {
      th.addEventListener('click', function () { sortBy(th.dataset.col); });
      th.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sortBy(th.dataset.col); }
      });
    });

    function sortBy(col) {
      if (sortState.col === col) { sortState.dir *= -1; }
      else { sortState.col = col; sortState.dir = 1; }
      ths.forEach(function (th) { th.setAttribute('aria-sort', 'none'); });
      var activeTh = qsa('.th-sort[data-col="' + col + '"]', table)[0];
      if (activeTh) {
        activeTh.setAttribute('aria-sort', sortState.dir === 1 ? 'ascending' : 'descending');
      }
      renderAll();
    }

    /* search */
    var searchInput = qs('#search-' + tableId.replace('table-', ''), panel || document);
    if (searchInput) {
      searchInput.addEventListener('input', debounce(function () {
        currentSearch = searchInput.value.toLowerCase().trim();
        renderAll();
      }, 180));
    }

    /* band chips — only chips that carry data-band */
    var bandChips = panel ? qsa('.chip[data-band]', panel) : [];
    bandChips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        bandChips.forEach(function (c) { c.classList.remove('chip--active'); });
        chip.classList.add('chip--active');
        currentBand = chip.dataset.band || 'all';
        renderAll();
      });
    });

    /* ── render ─────────────────────────────────────────────────────────────── */
    function renderAll() {
      /* 1. filter */
      var filtered = data.slice();

      if (currentSearch) {
        filtered = filtered.filter(function (r) {
          return r.symbol.toLowerCase().includes(currentSearch) ||
                 (r.company || '').toLowerCase().includes(currentSearch);
        });
      }

      if (currentBand !== 'all') {
        if (currentBand === 'below') {
          filtered = filtered.filter(function (r) { return r.price_diff_pct < 0; });
        } else {
          filtered = filtered.filter(function (r) { return r.band === currentBand; });
        }
      }

      if (currentCategory && currentCategory !== 'all') {
        filtered = filtered.filter(function (r) { return r.category === currentCategory; });
      }

      /* 2. sort */
      if (sortState.col) {
        var col = sortState.col;
        filtered.sort(function (a, b) {
          var av = a[col], bv = b[col];
          if (av === null || av === undefined) return 1;
          if (bv === null || bv === undefined) return -1;
          if (col === 'acq_to_dt') {
            var toNum = function (s) {
              var p = String(s).split('-');
              return p.length === 3 ? parseInt(p[2] + p[1] + p[0], 10) : 0;
            };
            av = toNum(av); bv = toNum(bv);
          } else if (typeof av === 'string') {
            av = av.toLowerCase(); bv = bv.toLowerCase();
          }
          return av < bv ? -sortState.dir : av > bv ? sortState.dir : 0;
        });
      }

      /* 3. reorder DOM — move each filtered data row + its drawer into place */
      var shownIdxSet = {};
      filtered.forEach(function (r) {
        var idx    = r._row_index !== undefined ? String(r._row_index) : null;
        var row    = idx !== null ? rowByIndex[idx] : rowBySymbol[r.symbol];
        if (!row) return;

        var drawer = idx !== null ? (drawerById['trades-' + idx] || null) : null;

        tbody.appendChild(row);
        if (drawer) tbody.appendChild(drawer);

        shownIdxSet[idx || r.symbol] = true;
      });

      /* 4. show/hide data rows */
      data.forEach(function (r) {
        var idx = r._row_index !== undefined ? String(r._row_index) : null;
        var row = idx !== null ? rowByIndex[idx] : rowBySymbol[r.symbol];
        if (!row) return;
        var key  = idx || r.symbol;
        var show = !!shownIdxSet[key];
        row.style.display = show ? '' : 'none';

        /* 5. collapse drawer if its row is filtered out */
        var drawer = idx !== null ? (drawerById['trades-' + idx] || null) : null;
        if (drawer && !show) {
          drawer.classList.remove('drawer-open');
          var btn = row.querySelector('.expand-btn');
          if (btn) btn.setAttribute('aria-expanded', 'false');
          row.classList.remove('row-expanded');
        }
        /* if show: leave drawer in whatever open/closed state the user left it */
      });

      /* 6. count note */
      var noteEl = qs('#' + tableId.replace('table-', '') + '-count-note');
      if (noteEl) {
        noteEl.textContent = filtered.length === data.length
          ? ''
          : 'Showing ' + filtered.length + ' of ' + data.length + ' stocks';
      }
    }
  }

  initSortableTable('table-shortlist');
  initSortableTable('table-candidates');

  /* ── Promoter trades drawer (expand/collapse) ──────────────────────────── */
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.expand-btn');
    if (!btn) return;

    var isExpanded = btn.getAttribute('aria-expanded') === 'true';
    var drawerId   = btn.getAttribute('aria-controls');
    var drawer     = drawerId ? document.getElementById(drawerId) : null;
    var parentRow  = btn.closest('tr');

    if (!drawer) return;

    if (isExpanded) {
      btn.setAttribute('aria-expanded', 'false');
      drawer.classList.remove('drawer-open');
      if (parentRow) parentRow.classList.remove('row-expanded');
    } else {
      btn.setAttribute('aria-expanded', 'true');
      drawer.classList.add('drawer-open');
      if (parentRow) parentRow.classList.add('row-expanded');
    }
  });

  /* ── Symbol tooltips — position fixed tooltip under hovered symbol ───────── */
  document.addEventListener('mouseover', function (e) {
    var wrap = e.target.closest('.symbol-wrap');
    if (!wrap) return;
    var tip = wrap.querySelector('.company-tooltip');
    if (!tip) return;
    var rect = wrap.getBoundingClientRect();
    tip.style.top  = (rect.bottom + 6) + 'px';
    tip.style.left = rect.left + 'px';
  });

  /* ── Fundamental metric tooltips — viewport-clamped fixed positioning ─────── */
  document.addEventListener('mouseover', function (e) {
    var wrap = e.target.closest('.fs-tip-wrap');
    if (!wrap) return;
    var box = wrap.querySelector('.fs-tip-box');
    if (!box) return;

    var iconRect = wrap.getBoundingClientRect();
    var boxW     = box.offsetWidth || 310;
    var boxH     = box.offsetHeight || 200;
    var vw       = window.innerWidth;
    var gap      = 8;   /* px between arrow tip and icon top */

    /* Preferred: above the icon, left-aligned to icon */
    var top  = iconRect.top - boxH - gap;
    var left = iconRect.left;

    /* If box goes above viewport, flip below the icon instead */
    if (top < 8) {
      top = iconRect.bottom + gap;
      box.setAttribute('data-flip', 'down');
    } else {
      box.removeAttribute('data-flip');
    }

    /* Clamp horizontally so box never escapes left or right edge */
    if (left + boxW > vw - 8) { left = vw - boxW - 8; }
    if (left < 8)              { left = 8; }

    box.style.top  = top  + 'px';
    box.style.left = left + 'px';
  });

})();
