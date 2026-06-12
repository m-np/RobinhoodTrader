document.addEventListener('DOMContentLoaded', async () => {
  await loadAll();
  setInterval(pollAlerts, 30000);
});

async function loadAll() {
  await Promise.all([
    loadWallet(),
    loadPortfolio(),
    loadAlerts(),
    loadWatchlist(),
    loadBlocklist(),
    loadMirrors(),
    loadKnobs(),
    loadLastReport(),
  ]);
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
    const pnl = document.getElementById('m-pnl');
    const ret = document.getElementById('m-return');
    const trd = document.getElementById('m-trades');
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

// Alerts
async function loadAlerts() {
  try {
    const res = await fetch('/api/alerts');
    const alerts = await res.json();
    const feed = document.getElementById('signals-feed');
    if (!feed) return;
    if (alerts.length === 0) {
      feed.innerHTML = '<p style="color:var(--text-3);font-size:13px;padding:12px 0">No active signals.</p>';
      return;
    }
    feed.innerHTML = alerts.map(a => `
      <div class="signal-card" data-severity="${a.severity}">
        <div class="signal-top">
          <div>
            ${a.ticker ? `<span class="signal-ticker">${a.ticker}</span>` : ''}
            <span class="badge ${badgeClass(a.alert_type)}">${alertLabel(a.alert_type)}</span>
          </div>
          <span class="signal-time">${timeAgo(a.created_at)}</span>
        </div>
        <p class="signal-body">${a.message}</p>
        <div class="signal-actions">
          ${a.alert_type === 'approval_request' && a.trade_id
            ? `<button class="btn-primary btn-sm" onclick="approveTrade('${a.trade_id}')">Approve</button>
               <button class="btn-danger btn-sm" onclick="rejectTrade('${a.trade_id}')">Reject</button>`
            : `<button class="btn-sm" onclick="ackAlert('${a.id}')">Dismiss</button>`
          }
        </div>
      </div>
    `).join('');
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

// Watchlist
async function loadWatchlist() {
  try {
    const res = await fetch('/api/watchlist');
    const rows = await res.json();
    const widget = document.getElementById('watchlist-widget');
    if (widget) {
      widget.innerHTML = rows.length === 0
        ? '<p style="color:var(--text-3);font-size:12px;padding:6px 0">Empty watchlist.</p>'
        : rows.map(r => `
          <div class="watch-row">
            <span class="watch-ticker">${r.ticker}</span>
            <div class="watch-right">
              <span class="watch-price">${r.price ? '$'+r.price.toFixed(2) : '—'}</span>
              <span class="watch-chg ${(r.change_pct || 0) >= 0 ? 'positive' : 'negative'}">${r.change_pct != null ? (r.change_pct >= 0 ? '+' : '')+r.change_pct.toFixed(1)+'%' : '—'}</span>
            </div>
          </div>
        `).join('');
    }
    const tbody = document.getElementById('watchlist-tbody');
    if (tbody) {
      tbody.innerHTML = rows.map(r => `
        <tr>
          <td><strong>${r.ticker}</strong></td>
          <td style="color:var(--text-2)">${r.notes || '—'}</td>
          <td style="color:var(--text-3)">${formatDate(r.added_at)}</td>
          <td>${r.price ? '$'+r.price.toFixed(2) : '—'}</td>
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

function showAddWatch() {
  const form = document.getElementById('add-watch-form');
  if (form) form.style.display = form.style.display === 'none' ? 'flex' : 'none';
}
function showAddWatchModal() { showAddWatch(); }

// Blocklist
async function loadBlocklist() {
  try {
    const res = await fetch('/api/blocklist');
    const rows = await res.json();
    const widget = document.getElementById('blocklist-widget');
    if (widget) {
      widget.innerHTML = rows.map(r => `
        <span class="pill pill-red">${r.ticker}
          <button onclick="removeBlock('${r.ticker}')" aria-label="Remove ${r.ticker}">×</button>
        </span>
      `).join('') + '<button class="add-pill" onclick="promptAddBlock()">+ add</button>';
    }
  } catch (e) { console.error('loadBlocklist:', e); }
}

async function removeBlock(ticker) {
  await fetch(`/api/blocklist/${ticker}`, { method: 'DELETE' });
  await loadBlocklist();
}

async function promptAddBlock() {
  const ticker = prompt('Ticker to never buy:');
  if (!ticker) return;
  const reason = prompt('Reason (optional):') || '';
  await fetch('/api/blocklist', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ticker: ticker.trim().toUpperCase(), reason})
  });
  await loadBlocklist();
}

// Mirrors
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
    mirrors.forEach(m => {
      const widget = document.getElementById(`mirror-last-${m.slug}`);
      if (widget && m.last_checked_at) widget.textContent = 'Last: ' + formatDate(m.last_checked_at);
    });
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

// Last report
async function loadLastReport() {
  try {
    const res = await fetch('/api/reports/last');
    if (!res.ok) return;
    const r = await res.json();
    if (!r.id) return;
    const titleEl = document.getElementById('report-title');
    const subEl = document.getElementById('report-sub');
    const bodyEl = document.getElementById('report-body');
    const pnlEl = document.getElementById('report-pnl');
    const dateEl = document.getElementById('report-date');
    if (titleEl) titleEl.textContent = r.title || '—';
    if (subEl) subEl.textContent = r.report_type ? r.report_type.charAt(0).toUpperCase() + r.report_type.slice(1) + ' report' : '—';
    if (bodyEl) bodyEl.textContent = r.summary || '—';
    if (dateEl && r.created_at) dateEl.textContent = formatDate(r.created_at);
    if (pnlEl && r.pnl_pct != null) {
      pnlEl.textContent = (r.pnl_pct >= 0 ? '+' : '') + r.pnl_pct.toFixed(1) + '%';
      pnlEl.className = 'badge ' + (r.pnl_pct >= 0 ? 'badge-green' : 'badge-red');
    }
  } catch (e) { /* no reports yet, silent */ }
}

async function requestFullReport() {
  alert('Full report generation is queued — check back in a moment.');
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
