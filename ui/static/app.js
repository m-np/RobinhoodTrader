document.addEventListener('DOMContentLoaded', async () => {
  await loadAll();
  setInterval(pollAlerts, 30000);
  setInterval(loadWatchlist, 5000);    // quotes: 5 s (1 MCP call)
  setInterval(loadPortfolio, 15000);  // holdings + P&L: 15 s (3 MCP calls)
});

async function loadAll() {
  await Promise.all([
    loadRobinhoodStatus(),
    loadWallet(),
    loadPortfolio(),
    loadAlerts(),
    loadWatchlist(),
    loadBlocklist(),
    loadMirrors(),
    loadKnobs(),
  ]);
}

// Robinhood connection status
async function loadRobinhoodStatus() {
  const connectBanner = document.getElementById('connect-banner');
  const connectedBanner = document.getElementById('connected-banner');
  if (!connectBanner && !connectedBanner) return;
  try {
    const res = await fetch('/api/robinhood/status');
    const data = await res.json();
    const dot = document.getElementById('status-dot');
    const txt = document.getElementById('status-text');
    if (data.connected) {
      if (connectBanner) connectBanner.style.display = 'none';
      if (connectedBanner) {
        const freshConnect = new URLSearchParams(window.location.search).get('connected');
        if (freshConnect === 'true') {
          connectedBanner.style.display = 'flex';
          setTimeout(() => { connectedBanner.style.display = 'none'; }, 4000);
          window.history.replaceState({}, '', '/');
        }
      }
      if (dot) dot.style.background = '#2d7a4f';
      if (txt) txt.textContent = 'Agent running';
    } else {
      if (connectBanner) connectBanner.style.display = 'flex';
      if (connectedBanner) connectedBanner.style.display = 'none';
      if (dot) dot.style.background = '#854f0b';
      if (txt) txt.textContent = 'Not connected to Robinhood';
    }
  } catch (e) {
    console.error('loadRobinhoodStatus:', e);
  }
}

// Wallet
async function loadWallet() {
  try {
    const res = await fetch('/api/wallet');
    const data = await res.json();
    const el = document.getElementById('m-wallet');
    if (el) el.textContent = '$' + data.balance.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    if (data.balance === 0) {
      const banner = document.getElementById('wallet-banner');
      if (banner) banner.style.display = 'flex';
    }
    const dot = document.getElementById('status-dot');
    const txt = document.getElementById('status-text');
    if (dot && txt) {
      if (data.balance > 0) {
        dot.style.background = '#2d7a4f';
        txt.textContent = 'Agent running';
      } else {
        dot.style.background = '#854f0b';
        txt.textContent = 'Agent paused — wallet empty';
      }
    }
  } catch (e) {
    const dot = document.getElementById('status-dot');
    const txt = document.getElementById('status-text');
    if (dot) dot.style.background = '#a32d2d';
    if (txt) txt.textContent = 'Connection error';
  }
}

// Portfolio
async function loadPortfolio() {
  try {
    const res = await fetch('/api/portfolio');
    const data = await res.json();
    const total = document.getElementById('m-total');
    const equity = document.getElementById('m-equity');
    const pnl = document.getElementById('m-pnl');
    const ret = document.getElementById('m-return');
    const trd = document.getElementById('m-trades');
    if (total && data.total_value != null) {
      total.textContent = '$' + data.total_value.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    }
    if (equity && data.equity_value != null) {
      equity.textContent = '$' + data.equity_value.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
    }
    if (pnl) {
      const v = data.today_pnl || 0;
      pnl.textContent = (v >= 0 ? '+' : '') + '$' + Math.abs(v).toFixed(2);
      pnl.className = 'metric-value ' + (v >= 0 ? 'positive' : 'negative');
    }
    if (ret) {
      const v = data.total_return_pct || 0;
      ret.textContent = (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
      ret.className = 'metric-value ' + (v >= 0 ? 'positive' : 'negative');
    }
    if (trd) trd.textContent = data.trades_today ?? '0';
    const table = document.getElementById('portfolio-table');
    if (table && data.holdings) {
      if (data.holdings.length === 0) {
        table.innerHTML = '<p style="color:var(--text-3);font-size:13px;padding:12px 0">No holdings yet.</p>';
      } else {
        table.innerHTML = data.holdings.map(h => `
          <div class="holding-row">
            <span class="holding-ticker">${h.ticker}</span>
            <div class="holding-bar-wrap">
              <div class="holding-bar" style="width:${Math.min(h.pct_of_portfolio || 0, 100)}%;background:${(h.pnl || 0) >= 0 ? 'var(--green)' : 'var(--red)'}"></div>
            </div>
            <span class="holding-pnl ${(h.pnl || 0) >= 0 ? 'positive' : 'negative'}">${(h.pnl || 0) >= 0 ? '+' : ''}$${Math.abs(h.pnl || 0).toFixed(0)}</span>
            <span class="holding-pct">${(h.pct_of_portfolio || 0).toFixed(0)}%</span>
          </div>
        `).join('');
      }
    }
  } catch (e) { console.error('loadPortfolio:', e); }
}

// Alerts — full action buttons for all signal types
async function loadAlerts() {
  try {
    const res = await fetch('/api/alerts');
    const alerts = await res.json();
    const feed = document.getElementById('signals-feed');
    if (!feed) return;
    if (!alerts.length) {
      feed.innerHTML = '<p style="color:var(--text-3);font-size:13px;padding:12px 0">No active signals.</p>';
      return;
    }
    const canTrade = typeof openQuickTrade === 'function';
    feed.innerHTML = alerts.map(a => {
      let actions = '';
      if (a.alert_type === 'approval_request' && a.trade_id) {
        actions = `<button class="btn-primary btn-sm" onclick="approveTrade('${a.trade_id}')">Approve</button>
                   <button class="btn-danger btn-sm" onclick="rejectTrade('${a.trade_id}')">Reject</button>`;
      } else if (a.alert_type === 'market_wave' && a.ticker) {
        actions = canTrade
          ? `<button class="btn-primary btn-sm" onclick="openQuickTrade('${a.ticker}','buy',null)">Buy</button>
             <button class="btn-danger btn-sm" onclick="openQuickTrade('${a.ticker}','sell',null)">Sell</button>
             <button class="btn-sm" onclick="ackAlert('${a.id}')">Dismiss</button>`
          : `<button class="btn-sm" onclick="ackAlert('${a.id}')">Dismiss</button>`;
      } else if (a.alert_type === 'mirror_trade' && a.ticker) {
        actions = canTrade
          ? `<button class="btn-primary btn-sm" onclick="openQuickTrade('${a.ticker}','buy',null)">Mirror buy</button>
             <button class="btn-sm" onclick="ackAlert('${a.id}')">Skip</button>`
          : `<button class="btn-sm" onclick="ackAlert('${a.id}')">Dismiss</button>`;
      } else {
        actions = `<button class="btn-sm" onclick="ackAlert('${a.id}')">Dismiss</button>`;
      }
      return `
        <div class="signal-card" data-severity="${a.severity}">
          <div class="signal-top">
            <div>
              ${a.ticker ? `<span class="signal-ticker">${a.ticker}</span>` : ''}
              <span class="badge ${badgeClass(a.alert_type)}">${alertLabel(a.alert_type)}</span>
            </div>
            <span class="signal-time">${timeAgo(a.created_at)}</span>
          </div>
          <p class="signal-body">${a.message}</p>
          <div class="signal-actions">${actions}</div>
        </div>`;
    }).join('');
  } catch (e) { console.error('loadAlerts:', e); }
}

async function pollAlerts() { await loadAlerts(); }

async function ackAlert(id) {
  await fetch(`/api/alerts/${id}/ack`, { method: 'POST' });
  await loadAlerts();
}

async function approveTrade(id) {
  await fetch(`/api/trades/${id}/approve`, { method: 'POST' });
  await loadAlerts();
  await loadPortfolio();
}

async function rejectTrade(id) {
  await fetch(`/api/trades/${id}/reject`, { method: 'POST' });
  await loadAlerts();
}

// Watchlist — updates both sidebar widget (#watchlist-widget) and full table (#watchlist-tbody)
async function loadWatchlist() {
  try {
    const res = await fetch('/api/watchlist');
    if (!res.ok) { console.error('loadWatchlist HTTP', res.status); return; }
    const rows = await res.json();

    // Detect whether live prices came back
    const hasLivePrices = rows.some(r => r.price != null);
    const statusEl = document.getElementById('watchlist-status');
    if (statusEl) {
      if (!hasLivePrices && rows.length > 0) {
        statusEl.textContent = 'Connect Robinhood to see live prices.';
        statusEl.style.color = 'var(--amber)';
      } else if (hasLivePrices) {
        const t = new Date().toLocaleTimeString('en-US', {hour:'numeric', minute:'2-digit'});
        statusEl.textContent = 'Live · updated ' + t;
        statusEl.style.color = 'var(--text-3)';
      }
    }

    const widget = document.getElementById('watchlist-widget');
    if (widget) {
      widget.innerHTML = rows.length === 0
        ? '<p style="color:var(--text-3);font-size:12px;padding:6px 0">Empty watchlist.</p>'
        : rows.map(r => `
          <div class="watch-row">
            <span class="watch-ticker">${r.ticker}</span>
            <div class="watch-right">
              <span class="watch-price">${r.price != null ? '$'+r.price.toFixed(2) : '—'}</span>
              <span class="watch-chg ${(r.change_pct || 0) >= 0 ? 'positive' : 'negative'}">${r.change_pct != null ? (r.change_pct >= 0 ? '+' : '')+r.change_pct.toFixed(1)+'%' : ''}</span>
            </div>
          </div>
        `).join('');
    }
    const tbody = document.getElementById('watchlist-tbody');
    if (tbody) {
      tbody.innerHTML = rows.length === 0
        ? '<tr><td colspan="6" style="color:var(--text-3);text-align:center;padding:20px">No tickers yet. Add one above.</td></tr>'
        : rows.map(r => `
          <tr>
            <td><strong>${r.ticker}</strong></td>
            <td style="color:var(--text-2)">${r.notes || '—'}</td>
            <td style="color:var(--text-3)">${formatDate(r.added_at)}</td>
            <td>${r.price != null ? '$'+r.price.toFixed(2) : '—'}</td>
            <td class="${(r.change_pct || 0) >= 0 ? 'positive' : 'negative'}">${r.change_pct != null ? (r.change_pct >= 0 ? '+' : '')+r.change_pct.toFixed(1)+'%' : '—'}</td>
            <td><button class="btn-remove" onclick="removeFromWatchlist('${r.ticker}')">Remove</button></td>
          </tr>
        `).join('');
    }
  } catch (e) { console.error('loadWatchlist:', e); }
}

async function addToWatchlist() {
  const ticker = document.getElementById('new-ticker')?.value.trim().toUpperCase();
  const notes = document.getElementById('new-notes')?.value.trim();
  if (!ticker) return;
  const res = await fetch('/api/watchlist', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ticker, notes})
  });
  if (res.status === 409) { alert(ticker + ' is already on your watchlist.'); return; }
  await loadWatchlist();
  const form = document.getElementById('add-watch-form');
  if (form) form.style.display = 'none';
  const t = document.getElementById('new-ticker');
  const n = document.getElementById('new-notes');
  if (t) t.value = '';
  if (n) n.value = '';
}

async function removeFromWatchlist(ticker) {
  await fetch(`/api/watchlist/${ticker}`, { method: 'DELETE' });
  await loadWatchlist();
}

// Toggle the search form — works on both dashboard sidebar (#watch-search-wrap) and watchlist page
function showAddWatch() {
  const wrap = document.getElementById('watch-search-wrap');
  if (!wrap) return;
  const open = wrap.style.display === 'none' || wrap.style.display === '';
  wrap.style.display = open ? 'block' : 'none';
  if (open) {
    const inp = document.getElementById('watch-search-input');
    if (inp) inp.focus();
  }
}

function showAddBlock() {
  const wrap = document.getElementById('block-search-wrap');
  if (!wrap) return;
  const open = wrap.style.display === 'none' || wrap.style.display === '';
  wrap.style.display = open ? 'block' : 'none';
  if (open) {
    const inp = document.getElementById('block-search-input');
    if (inp) inp.focus();
  }
}

// Ticker search — shared by watchlist + blocklist search dropdowns
let _searchTimer = null;
async function onTickerSearch(q, target) {
  clearTimeout(_searchTimer);
  const dropdown = document.getElementById(target + '-search-dropdown');
  if (!dropdown) return;
  if (!q || q.length < 1) { dropdown.innerHTML = ''; return; }
  _searchTimer = setTimeout(async () => {
    try {
      const res = await fetch('/api/search?q=' + encodeURIComponent(q));
      const items = await res.json();
      dropdown.innerHTML = items.map(i => `
        <div class="search-result" onclick="selectTicker('${i.symbol}','${(i.name||'').replace(/'/g,"\\'")}','${target}')">
          <strong>${i.symbol}</strong> <span>${i.name || ''}</span>
        </div>
      `).join('') || '<div class="search-result" style="color:var(--text-3)">No results</div>';
    } catch (e) { console.error('onTickerSearch:', e); }
  }, 250);
}

function selectTicker(symbol, name, target) {
  if (target === 'watch') {
    addToWatchlistDirect(symbol);
  } else {
    addToBlocklistDirect(symbol);
  }
  const inp = document.getElementById(target + '-search-input');
  const dd = document.getElementById(target + '-search-dropdown');
  const wrap = document.getElementById(target + '-search-wrap');
  if (inp) inp.value = '';
  if (dd) dd.innerHTML = '';
  if (wrap) wrap.style.display = 'none';
}

async function addToWatchlistDirect(ticker) {
  const notes = document.getElementById('watch-notes')?.value || '';
  const res = await fetch('/api/watchlist', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ticker, notes})
  });
  if (res.status === 409) { alert(ticker + ' is already on your watchlist.'); }
  await loadWatchlist();
}

async function addToBlocklistDirect(ticker) {
  const reason = document.getElementById('block-reason')?.value || '';
  const res = await fetch('/api/blocklist', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ticker, reason})
  });
  if (res.status === 409) { alert(ticker + ' is already on your Don\'t Buy list.'); }
  await loadBlocklist();
}

// Blocklist
async function loadBlocklist() {
  try {
    const res = await fetch('/api/blocklist');
    const rows = await res.json();
    const widget = document.getElementById('blocklist-widget');
    if (widget) {
      widget.innerHTML = rows.map(r => `
        <span class="pill pill-red" title="${r.reason || ''}">${r.ticker}
          <button onclick="removeBlock('${r.ticker}')" aria-label="Remove ${r.ticker}">×</button>
        </span>
      `).join('');
    }
  } catch (e) { console.error('loadBlocklist:', e); }
}

async function removeBlock(ticker) {
  await fetch(`/api/blocklist/${ticker}`, { method: 'DELETE' });
  await loadBlocklist();
}

// Mirrors — renders full mirror list on the mirrors page (#mirrors-list)
async function loadMirrors() {
  try {
    const res = await fetch('/api/mirrors');
    const mirrors = await res.json();
    const container = document.getElementById('mirrors-list');
    if (container) {
      container.innerHTML = mirrors.map(m => `
        <div class="mirror-full-card">
          <div class="mirror-full-header">
            <div class="avatar avatar-lg">${initials(m.name)}</div>
            <div class="mirror-info">
              <div class="mirror-full-name">${m.name}</div>
              <div class="mirror-full-meta">${m.source_type === 'congressional' ? 'Congressional disclosure · up to 45-day filing lag' : 'Institutional 13F filing · quarterly'}</div>
            </div>
            <label class="toggle">
              <input type="checkbox" id="tog-${m.slug}" ${m.enabled ? 'checked' : ''} onchange="toggleMirror('${m.slug}', this.checked)">
              <span class="toggle-slider"></span>
            </label>
          </div>
          <div class="mirror-scale-row">
            <label class="field-label">Scale factor</label>
            <input type="range" min="0.005" max="0.1" step="0.005" value="${m.scale_factor}" id="scale-${m.slug}"
                   oninput="document.getElementById('scale-label-${m.slug}').textContent = (parseFloat(this.value)*100).toFixed(1)+'%'"
                   onchange="setMirrorScale('${m.slug}', this.value)">
            <span id="scale-label-${m.slug}">${(m.scale_factor * 100).toFixed(1)}%</span>
            <span class="field-hint">of portfolio per trade</span>
          </div>
          <div class="mirror-recent">
            <div class="section-title" style="margin-bottom:8px">Recent disclosures</div>
            <div id="disclosures-${m.slug}" style="font-size:12px;color:var(--text-3)">${m.last_checked_at ? 'Last checked: ' + formatDate(m.last_checked_at) : 'Not yet checked'}</div>
          </div>
        </div>
      `).join('');
    }
  } catch (e) { console.error('loadMirrors:', e); }
}

async function toggleMirror(slug, enabled) {
  await fetch('/api/mirrors/' + slug, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({enabled})
  });
}

async function setMirrorScale(slug, scale_factor) {
  await fetch('/api/mirrors/' + slug, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({scale_factor: parseFloat(scale_factor)})
  });
}

// Knobs
async function loadKnobs() {
  try {
    const res = await fetch('/api/knobs');
    const knobs = await res.json();
    Object.entries(knobs).forEach(([key, value]) => {
      const el = document.getElementById('knob-' + key);
      if (!el) return;
      if (el.type === 'checkbox') el.checked = value === true || value === 'true';
      if (el.type === 'range') el.value = value;
    });
    syncRangeDisplay('approval_threshold_usd', 'thresh-display', v => parseInt(v) === 0 ? 'Always ask' : '$'+parseInt(v).toLocaleString());
    syncRangeDisplay('max_position_pct', 'pos-display', v => v+'%');
    syncRangeDisplay('max_trades_per_day', 'trades-display', v => v);
    syncRangeDisplay('daily_loss_halt_pct', 'loss-display', v => parseFloat(v).toFixed(1)+'%');
    syncSeg('seg-timeout', knobs.approval_timeout_minutes);
    syncSeg('seg-freq', knobs.report_frequency);
    syncSeg('seg-day', knobs.report_weekly_day);
    syncSeg('seg-delivery', knobs.report_delivery);
    syncSeg('seg-depth', knobs.report_depth);
  } catch (e) { console.error('loadKnobs:', e); }
}

function syncRangeDisplay(knobKey, displayId, formatter) {
  const input = document.getElementById('knob-' + knobKey);
  const display = document.getElementById(displayId);
  if (input && display) display.textContent = formatter(input.value);
}

function syncSeg(segId, activeValue) {
  const seg = document.getElementById(segId);
  if (!seg || activeValue == null) return;
  const strVal = String(activeValue).toLowerCase();
  seg.querySelectorAll('.seg-btn').forEach(btn => {
    const btnVal = (btn.dataset.value || btn.textContent).toLowerCase();
    btn.classList.toggle('active', btnVal === strVal || btn.textContent.toLowerCase().startsWith(strVal.slice(0, 3)));
  });
}

async function saveKnob(key, value) {
  await fetch('/api/knobs', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({key, value})
  });
}

function setSeg(knobKey, value, btn) {
  const seg = btn.closest('.seg-control');
  seg.querySelectorAll('.seg-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  saveKnob(knobKey, value);
}

// Reports — renders list on the reports page (#reports-list)
async function loadReports() {
  const container = document.getElementById('reports-list');
  if (!container) return;
  try {
    const res = await fetch('/api/reports');
    const reports = await res.json();
    if (!reports.length) {
      container.innerHTML = '<div class="card" style="padding:24px;text-align:center;color:var(--text-3)">No reports yet. Reports are generated automatically based on your <a href="/settings" style="color:var(--blue)">report settings</a>.</div>';
      return;
    }
    container.innerHTML = reports.map(r => `
      <div class="report-card card" onclick="toggleReport(this)">
        <div class="report-top">
          <div>
            <span class="report-title-text">${r.title || 'Report'}</span>
            <span class="badge ${r.report_type === 'weekly' ? 'badge-blue' : 'badge-purple'}" style="margin-left:8px">${r.report_type === 'weekly' ? 'Weekly' : 'Daily'}</span>
          </div>
          <div style="display:flex;gap:8px;align-items:center">
            ${r.pnl_pct != null ? `<span class="badge ${r.pnl_pct >= 0 ? 'badge-green' : 'badge-red'}">${r.pnl_pct >= 0 ? '+' : ''}${r.pnl_pct.toFixed(1)}%</span>` : ''}
            <span style="font-size:12px;color:var(--text-3)">${formatDate(r.created_at)}</span>
            <span class="report-chevron" style="font-size:12px;color:var(--text-3)">▼</span>
          </div>
        </div>
        <div class="report-body" style="display:none">${r.summary || ''}</div>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = '<div class="card" style="padding:24px;color:var(--red)">Failed to load reports.</div>';
  }
}

function toggleReport(card) {
  const body = card.querySelector('.report-body');
  const chevron = card.querySelector('.report-chevron');
  const open = body.style.display === 'none';
  body.style.display = open ? 'block' : 'none';
  if (chevron) chevron.textContent = open ? '▲' : '▼';
}

async function refreshSignals() { await loadAlerts(); }

// Helpers
function badgeClass(type) {
  return { market_wave: 'badge-red', mirror_trade: 'badge-amber', approval_request: 'badge-blue', wallet_low: 'badge-amber' }[type] || 'badge-blue';
}

function alertLabel(type) {
  return { market_wave: 'Market wave', mirror_trade: 'Mirror alert', approval_request: 'Awaiting approval', wallet_low: 'Wallet low' }[type] || type;
}

function timeAgo(iso) {
  if (!iso) return '—';
  const diff = (Date.now() - new Date(iso)) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff/60) + ' min ago';
  if (diff < 86400) return Math.floor(diff/3600) + ' hr ago';
  return Math.floor(diff/86400) + ' d ago';
}

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric'});
}

function initials(name) {
  return name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
}
