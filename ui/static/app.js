document.addEventListener('DOMContentLoaded', async () => {
  await loadAll();
  setInterval(pollAlerts, 30000);
  setInterval(loadWatchlist, 5000);    // quotes: 5 s (1 MCP call)
  setInterval(loadPortfolio, 15000);  // holdings + P&L: 15 s (3 MCP calls)
  loadCyclePulse();
  setInterval(loadCyclePulse, 30000);
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
    loadCyclePulse(),
  ]);
}

// Agent brain card — shows cycle status + Claude's recent observations
async function loadCyclePulse() {
  const chip = document.getElementById('agent-status-chip');
  const card = document.getElementById('agent-card');
  if (!chip || !card) return;

  let d;
  try {
    const res = await fetch('/api/agent/cycle_status');
    if (!res.ok) {
      card.innerHTML = '<p class="agent-meta">Could not reach agent status.</p>';
      return;
    }
    d = await res.json();
  } catch (e) {
    card.innerHTML = '<p class="agent-meta">Could not reach agent status.</p>';
    return;
  }

  // Update the status chip
  chip.className = 'agent-chip';
  const runBtn = document.getElementById('agent-run-btn');
  if (d.status === 'running') {
    chip.classList.add('running');
    chip.textContent = 'Analyzing…';
    if (runBtn && runBtn.textContent === 'Run') {
      runBtn.disabled = true;
      runBtn.textContent = 'Running';
    }
  } else if (d.status === 'error') {
    chip.classList.add('error');
    chip.textContent = 'Error';
    if (runBtn) { runBtn.disabled = false; runBtn.textContent = 'Run'; }
  } else {
    chip.textContent = d.finished_at ? timeAgo(d.finished_at) + ' ago' : 'Idle';
    if (runBtn && runBtn.textContent === 'Running') {
      runBtn.disabled = false;
      runBtn.textContent = 'Run';
    }
  }

  // Populate card body
  if (d.status === 'running') {
    card.innerHTML = '<p class="agent-meta">Claude is reading market data and checking your watchlist…</p>';
    return;
  }
  if (d.status === 'error') {
    card.innerHTML = `<p class="agent-meta" style="color:var(--red)">${d.error || 'Unknown error'}</p>`;
    return;
  }

  const thoughts = d.recent_thoughts || [];
  if (!thoughts.length) {
    card.innerHTML = '<p class="agent-meta">No cycle has run yet — starts automatically.</p>';
    return;
  }

  const meta = d.finished_at
    ? `<div class="agent-meta">Last scan ${timeAgo(d.finished_at)} ago · every 15 min · ${thoughts.length} observations</div>`
    : `<div class="agent-meta">Waiting for first cycle… · ${thoughts.length} observations</div>`;

  const items = thoughts.map((t, i) => {
    const sev = t.severity || 'info';
    const body = (t.body || '').trim();
    const hasMore = body.length > t.headline.length + 5;
    return `
    <div class="agent-thought" id="thought-${i}" onclick="toggleThought(${i})">
      <div class="agent-thought-header">
        <span class="agent-thought-dot ${sev}"></span>
        <span class="agent-thought-headline">${escHtml(t.headline)}</span>
        ${hasMore ? '<span class="agent-thought-chevron">▾</span>' : ''}
      </div>
      ${hasMore ? `<div class="agent-thought-body">${escHtml(body)}</div>` : ''}
    </div>`;
  }).join('');

  card.innerHTML = meta + items;
}

function toggleThought(i) {
  const el = document.getElementById('thought-' + i);
  if (el) el.classList.toggle('open');
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function timeAgo(isoStr) {
  const secs = Math.round((Date.now() - new Date(isoStr + (isoStr.endsWith('Z') ? '' : 'Z'))) / 1000);
  if (secs < 60)   return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m`;
  return `${Math.floor(secs / 3600)}h`;
}

let _cooldownTimer = null;

async function triggerAgentCycle() {
  const btn  = document.getElementById('agent-run-btn');
  const warn = document.getElementById('agent-rate-warn');
  if (!btn) return;

  btn.disabled = true;
  btn.textContent = 'Starting…';

  let data;
  try {
    const res = await fetch('/api/agent/run', { method: 'POST' });
    data = await res.json();

    if (res.status === 409) {
      btn.textContent = 'Already running';
      setTimeout(() => { btn.disabled = false; btn.textContent = 'Run'; }, 3000);
      return;
    }

    if (res.status === 429) {
      // Cooldown — show warning and countdown on the button
      if (warn) {
        warn.style.display = 'block';
        warn.textContent = data.message || 'Too many triggers. Please wait.';
      }
      startCooldownBtn(btn, data.retry_after || 300);
      return;
    }

    // Success
    if (data.warn && warn) {
      warn.style.display = 'block';
      warn.textContent = `Warning: ${data.triggers_remaining} manual trigger${data.triggers_remaining === 1 ? '' : 's'} left before cooldown.`;
    } else if (warn) {
      warn.style.display = 'none';
    }

    btn.textContent = 'Running';
    // Poll until cycle finishes
    const poll = setInterval(async () => {
      await loadCyclePulse();
      const chip = document.getElementById('agent-status-chip');
      if (chip && chip.textContent !== 'Analyzing…') {
        clearInterval(poll);
        btn.disabled = false;
        btn.textContent = 'Run';
      }
    }, 3000);

  } catch (_) {
    btn.disabled = false;
    btn.textContent = 'Run';
  }
}

function startCooldownBtn(btn, seconds) {
  if (_cooldownTimer) clearInterval(_cooldownTimer);
  let remaining = seconds;
  const update = () => {
    if (remaining <= 0) {
      clearInterval(_cooldownTimer);
      btn.disabled = false;
      btn.textContent = 'Run';
      const warn = document.getElementById('agent-rate-warn');
      if (warn) warn.style.display = 'none';
      return;
    }
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    btn.textContent = m > 0 ? `${m}m ${s}s` : `${s}s`;
    remaining--;
  };
  update();
  _cooldownTimer = setInterval(update, 1000);
}

// Robinhood connection status
async function loadRobinhoodStatus() {
  const connectBanner = document.getElementById('connect-banner');
  const connectedBanner = document.getElementById('connected-banner');
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
    // Update settings page connection card
    const desc = document.getElementById('rh-status-desc');
    const btn = document.getElementById('rh-connect-btn');
    if (desc && btn) {
      if (data.connected) {
        const expiry = data.expires_at ? ' · expires ' + new Date(data.expires_at).toLocaleDateString() : '';
        desc.textContent = 'Connected' + (data.account_id ? ' · account ' + data.account_id : '') + expiry;
        desc.style.color = 'var(--green, #2d7a4f)';
        btn.textContent = 'Reconnect Robinhood';
      } else {
        desc.textContent = 'Not connected — agent cannot place trades.';
        desc.style.color = 'var(--amber, #854f0b)';
        btn.textContent = 'Connect Robinhood';
      }
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

// Cached live portfolio value — used by the chart to pin the current point
let _livePortfolio = null;

// Portfolio
async function loadPortfolio() {
  try {
    const res = await fetch('/api/portfolio');
    const data = await res.json();
    _livePortfolio = data;
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

// ── Signal auto-fade state ─────────────────────────────────────────────────
// _fadingAlerts: IDs currently mid-animation (excluded from re-renders)
// _scheduledFades: {id: timeoutId} — prevent duplicate timers across polls
const _fadingAlerts = new Set();
const _scheduledFades = {};

// Returns ms until auto-fade, or null if the signal must never auto-dismiss.
// Delay is based on alert age so re-renders don't reset the clock.
function getAutoFadeDelay(a) {
  if (a.alert_type === 'approval_request') return null;
  if (a.severity === 'critical') return null;
  const ageSec = (Date.now() - new Date(a.created_at)) / 1000;
  const totalSec = a.severity === 'warning' ? 45 : 20;
  return Math.max(0, (totalSec - ageSec) * 1000);
}

function scheduleAutoFades(alerts) {
  alerts.forEach(a => {
    if (_fadingAlerts.has(a.id) || _scheduledFades[a.id]) return;
    const delay = getAutoFadeDelay(a);
    if (delay === null) return;
    _scheduledFades[a.id] = setTimeout(() => {
      delete _scheduledFades[a.id];
      const card = document.querySelector(`.signal-card[data-id="${a.id}"]`);
      if (!card) return;
      _fadingAlerts.add(a.id);
      card.classList.add('fading-out');
      setTimeout(async () => {
        await fetch(`/api/alerts/${a.id}/ack`, { method: 'POST' });
        _fadingAlerts.delete(a.id);
      }, 550);
    }, delay);
  });
}

// ── Alerts — only decision signals (buy/sell) are shown ───────────────────
async function loadAlerts() {
  try {
    const res = await fetch('/api/alerts');
    const alerts = await res.json();
    const feed = document.getElementById('signals-feed');
    if (!feed) return;

    // Only show signals that require a buy or sell decision
    const decisions = alerts.filter(a =>
      !_fadingAlerts.has(a.id) &&
      (a.alert_type === 'approval_request' || (a.alert_type === 'mirror_trade' && a.ticker))
    );

    if (!decisions.length) {
      feed.innerHTML = '<p style="color:var(--text-3);font-size:13px;padding:12px 0">No pending decisions.</p>';
      return;
    }

    const canTrade = typeof openQuickTrade === 'function';
    feed.innerHTML = decisions.map(a => {
      let action, amount, context, primaryBtn, secondaryBtn;

      if (a.alert_type === 'approval_request') {
        action = a.action || (a.message.match(/:\s*(BUY|SELL)/i) || [])[1]?.toLowerCase() || 'buy';

        // Use structured trade fields from API (no regex fragility)
        if (a.quantity != null && a.price_usd != null) {
          const qty = Number.isInteger(a.quantity)
            ? a.quantity.toString()
            : parseFloat(a.quantity.toFixed(6)).toString();
          const price = '$' + a.price_usd.toLocaleString('en-US', {
            minimumFractionDigits: 2, maximumFractionDigits: 2,
          });
          amount = `${qty} shares @ ${price}`;
          if (a.total_usd != null) {
            amount += ` · $${a.total_usd.toLocaleString('en-US', {
              minimumFractionDigits: 2, maximumFractionDigits: 2,
            })} total`;
          }
        } else {
          // Fallback: parse total from message text
          const totalMatch = a.message.match(/~?\$?([\d,]+(?:\.\d+)?)\)?$/);
          amount = totalMatch ? '$' + totalMatch[1] : '';
        }

        // Reason from first parenthetical in message
        context = (a.message.match(/\(([^)]+)\)/) || [])[1] || 'agent recommendation';

        if (a.trade_id) {
          primaryBtn = `<button class="decision-btn decision-btn-${action}"
                          onclick="approveTrade('${a.trade_id}','${a.id}')">
                          ${action === 'sell' ? 'Approve sell' : 'Approve buy'}
                        </button>`;
          secondaryBtn = `<button class="btn-sm" onclick="rejectTrade('${a.trade_id}','${a.id}')">Reject</button>`;
        } else {
          primaryBtn = '';
          secondaryBtn = `<button class="btn-sm" onclick="ackAlert('${a.id}')">Dismiss</button>`;
        }

      } else {
        // mirror_trade
        action = /\b(sell|sold)\b/i.test(a.message) ? 'sell' : 'buy';

        // Disclosed dollar amount: "amount: $1K–$15K"
        const amtMatch = a.message.match(/amount:\s*([^)]+)\)/i);
        amount = amtMatch ? amtMatch[1].trim() + ' disclosed' : '';

        // Source name before " disclosed"
        const src = (a.message.match(/^(.+?)\s+disclosed/i) || [])[1] || 'Mirror';
        context = 'Via ' + src;

        primaryBtn = canTrade
          ? `<button class="decision-btn decision-btn-${action}" onclick="openQuickTrade('${a.ticker}','${action}',null)">
               ${action === 'sell' ? 'Sell' : 'Buy'} ${a.ticker}
             </button>`
          : '';
        secondaryBtn = `<button class="btn-sm" onclick="ackAlert('${a.id}')">Skip</button>`;
      }

      return `
        <div class="signal-card decision-card" data-id="${a.id}">
          <div class="decision-header">
            <span class="decision-action action-${action}">${action.toUpperCase()}</span>
            <span class="decision-ticker">${a.ticker || ''}</span>
            <span class="signal-time" style="margin-left:auto">${timeAgo(a.created_at)}</span>
          </div>
          ${amount
            ? `<p class="decision-amount decision-amount-${action}">${amount}</p>`
            : ''}
          <p class="decision-context">${context}</p>
          <div class="signal-actions">
            ${primaryBtn}
            ${secondaryBtn}
          </div>
        </div>`;
    }).join('');

    scheduleAutoFades(decisions);
  } catch (e) { console.error('loadAlerts:', e); }
}

async function pollAlerts() { await loadAlerts(); }

async function ackAlert(id) {
  // Cancel any pending auto-fade timer
  if (_scheduledFades[id]) { clearTimeout(_scheduledFades[id]); delete _scheduledFades[id]; }
  const card = document.querySelector(`.signal-card[data-id="${id}"]`);
  if (card) {
    _fadingAlerts.add(id);
    card.classList.add('fading-out');
    setTimeout(async () => {
      await fetch(`/api/alerts/${id}/ack`, { method: 'POST' });
      _fadingAlerts.delete(id);
      const feed = document.getElementById('signals-feed');
      if (feed && !feed.querySelector('.signal-card')) {
        feed.innerHTML = '<p style="color:var(--text-3);font-size:13px;padding:12px 0">No active signals.</p>';
      }
    }, 550);
  } else {
    await fetch(`/api/alerts/${id}/ack`, { method: 'POST' });
    await loadAlerts();
  }
}

// Add a ticker to the watchlist directly from a signal card button
async function quickWatch(ticker, btnEl) {
  const orig = btnEl.textContent;
  btnEl.disabled = true;
  btnEl.textContent = '…';
  try {
    const res = await fetch('/api/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker }),
    });
    btnEl.textContent = res.status === 409 ? 'Watching' : '✓ Watching';
    btnEl.style.color = 'var(--green)';
    loadWatchlist();
  } catch (e) {
    btnEl.textContent = orig;
    btnEl.disabled = false;
  }
}

async function approveTrade(tradeId, alertId) {
  await fetch(`/api/trades/${tradeId}/approve`, { method: 'POST' });
  if (alertId) await ackAlert(alertId);
  else await loadAlerts();
  loadPortfolio();
}

async function rejectTrade(tradeId, alertId) {
  await fetch(`/api/trades/${tradeId}/reject`, { method: 'POST' });
  if (alertId) await ackAlert(alertId);
  else await loadAlerts();
}

// Previous prices — used to detect changes and trigger flash
const _prevPrices = {};

// Returns true if US equities market is currently open (Mon–Fri 9:30–16:00 ET)
function isMarketOpen() {
  const et = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' }));
  const day = et.getDay();          // 0 Sun … 6 Sat
  const mins = et.getHours() * 60 + et.getMinutes();
  return day >= 1 && day <= 5 && mins >= 9 * 60 + 30 && mins < 16 * 60;
}

// Render a tiny SVG sparkline from an array of {price} points
function _makeSpark(points, width, height) {
  if (!points || points.length < 2) return '<span style="color:var(--text-3);font-size:11px">—</span>';
  const vals = points.map(p => p.price).filter(v => v != null);
  if (vals.length < 2) return '<span style="color:var(--text-3);font-size:11px">—</span>';
  const min = Math.min(...vals), max = Math.max(...vals);
  const range = max - min || 1;
  const xStep = width / (vals.length - 1);
  const pts = vals.map((v, i) =>
    `${(i * xStep).toFixed(1)},${(height - ((v - min) / range) * height).toFixed(1)}`
  ).join(' ');
  const up = vals[vals.length - 1] >= vals[0];
  const color = up ? 'var(--green, #2d7a4f)' : 'var(--red, #a32d2d)';
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" style="display:block">` +
    `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}

// Watchlist — updates both sidebar widget (#watchlist-widget) and full table (#watchlist-tbody)
async function loadWatchlist() {
  try {
    const [wRes, hRes] = await Promise.all([
      fetch('/api/watchlist'),
      fetch('/api/watchlist/prices/history?period=1d'),
    ]);
    if (!wRes.ok) { console.error('loadWatchlist HTTP', wRes.status); return; }
    const rows = await wRes.json();
    const history = hRes.ok ? await hRes.json() : {};

    // Detect whether live prices came back and whether market is open
    const hasLivePrices = rows.some(r => r.price != null);
    const open = isMarketOpen();
    const updatedAt = new Date().toLocaleTimeString('en-US', {hour:'numeric', minute:'2-digit'});

    let statusText, statusColor;
    if (!hasLivePrices && rows.length > 0) {
      statusText = 'Connect Robinhood to see prices';
      statusColor = 'var(--amber)';
    } else if (!open) {
      statusText = 'Market closed · last close ' + updatedAt;
      statusColor = 'var(--text-3)';
    } else {
      statusText = 'Live · updated ' + updatedAt;
      statusColor = 'var(--text-3)';
    }

    // Full watchlist page status label
    const statusEl = document.getElementById('watchlist-status');
    if (statusEl) { statusEl.textContent = statusText; statusEl.style.color = statusColor; }

    const widget = document.getElementById('watchlist-widget');
    if (widget) {
      if (rows.length === 0) {
        widget.innerHTML = '<p style="color:var(--text-3);font-size:12px;padding:6px 0">Empty watchlist.</p>';
      } else {
        widget.innerHTML = rows.map(r => `
          <div class="watch-row">
            <span class="watch-ticker">${r.ticker}</span>
            <div class="watch-right">
              <span class="watch-price">${r.price != null ? '$'+r.price.toFixed(2) : '—'}</span>
              <span class="watch-chg ${(r.change_pct || 0) >= 0 ? 'positive' : 'negative'}">${r.change_pct != null ? (r.change_pct >= 0 ? '+' : '')+r.change_pct.toFixed(1)+'%' : ''}</span>
            </div>
          </div>
        `).join('') +
        `<div class="watch-status-row" style="color:${statusColor}">${statusText}</div>`;
      }
    }
    const tbody = document.getElementById('watchlist-tbody');
    if (tbody) {
      if (rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="color:var(--text-3);text-align:center;padding:20px">No tickers yet. Add one above.</td></tr>';
      } else {
        tbody.innerHTML = rows.map(r => {
          const prev = _prevPrices[r.ticker];
          const priceChanged = r.price != null && prev != null && r.price !== prev;
          const flashClass = priceChanged ? (r.price > prev ? 'flash-up' : 'flash-down') : '';
          return `
          <tr>
            <td><strong>${r.ticker}</strong></td>
            <td style="color:var(--text-2)">${r.notes || '—'}</td>
            <td style="color:var(--text-3)">${formatDate(r.added_at)}</td>
            <td class="${flashClass}">${r.price != null ? '$'+r.price.toFixed(2) : '—'}</td>
            <td class="${(r.change_pct || 0) >= 0 ? 'positive' : 'negative'}">${r.change_pct != null ? (r.change_pct >= 0 ? '+' : '')+r.change_pct.toFixed(1)+'%' : '—'}</td>
            <td>${_makeSpark(history[r.ticker], 80, 28)}</td>
            <td><button class="btn-remove" onclick="removeFromWatchlist('${r.ticker}')">Remove</button></td>
          </tr>`;
        }).join('');
        rows.forEach(r => { if (r.price != null) _prevPrices[r.ticker] = r.price; });
      }
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
      if (el.type === 'number') el.value = value;
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
