/**
 * AIOS Sync Manager v3.1.0
 *
 * Responsibilities:
 *  1. Monitor connectivity (navigator.onLine + /api/sync/heartbeat ping)
 *  2. Show / hide the offline banner
 *  3. Intercept form submissions and fetch calls when offline → queue in IndexedDB
 *  4. On reconnect, flush the offline queue → POST /api/sync/batch
 *  5. Parse sync results: show conflict notifications, send alerts
 *  6. Render the conflict resolution panel
 */

(function () {
  'use strict';

  const HEARTBEAT_URL   = '/api/sync/heartbeat';
  const SYNC_URL        = '/api/sync/batch';
  const CONFLICTS_URL   = '/api/sync/conflicts';
  const HEARTBEAT_MS    = 15_000;   // check every 15s
  const SYNC_DEBOUNCE   = 3_000;    // wait 3s after coming online before syncing

  let _isOnline         = navigator.onLine;
  let _heartbeatTimer   = null;
  let _syncTimer        = null;
  let _swReady          = false;

  // ── Boot ───────────────────────────────────────────────────────────────────
  async function init() {
    _registerServiceWorker();
    _bindConnectivityEvents();
    _startHeartbeat();
    _interceptForms();
    _interceptFetch();
    await _checkConflictsOnLoad();
    // Initial connectivity check
    await _heartbeat();
  }

  // ── Service Worker ─────────────────────────────────────────────────────────
  function _registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    navigator.serviceWorker.register('/sw.js', { scope: '/' })
      .then(reg => {
        _swReady = true;
        // Listen for messages from SW
        navigator.serviceWorker.addEventListener('message', _onSwMessage);
        // Prompt update when new SW is waiting
        reg.addEventListener('updatefound', () => {
          const nw = reg.installing;
          if (!nw) return;
          nw.addEventListener('statechange', () => {
            if (nw.state === 'installed' && navigator.serviceWorker.controller) {
              _showUpdateBanner();
            }
          });
        });
      })
      .catch(() => {});
  }

  function _onSwMessage(event) {
    const { type, path } = event.data || {};
    if (type === 'ONLINE')              { _setOnline(true); }
    if (type === 'OFFLINE_CACHE_HIT')   { _setOnline(false); _updateBanner(`Showing cached version of ${path}`); }
    if (type === 'OFFLINE_FALLBACK')    { _setOnline(false); }
    if (type === 'POST_OFFLINE')        { /* form intercept handles this already */ }
  }

  // ── Connectivity ───────────────────────────────────────────────────────────
  function _bindConnectivityEvents() {
    window.addEventListener('online',  () => _heartbeat());
    window.addEventListener('offline', () => _setOnline(false));
  }

  function _startHeartbeat() {
    _heartbeatTimer = setInterval(_heartbeat, HEARTBEAT_MS);
  }

  async function _heartbeat() {
    try {
      const resp = await fetch(HEARTBEAT_URL, {
        method: 'GET',
        cache:  'no-store',
        signal: AbortSignal.timeout(5000),
      });
      _setOnline(resp.ok);
    } catch {
      _setOnline(false);
    }
  }

  function _setOnline(online) {
    const wasOffline = !_isOnline;
    _isOnline = online;
    _renderOfflineBanner();

    if (online && wasOffline) {
      // Just came back online — sync after short debounce
      clearTimeout(_syncTimer);
      _syncTimer = setTimeout(_syncQueue, SYNC_DEBOUNCE);
    }
  }

  // ── Offline banner ─────────────────────────────────────────────────────────
  function _renderOfflineBanner() {
    const banner = document.getElementById('aios-offline-banner');
    if (!banner) return;
    if (_isOnline) {
      banner.style.display = 'none';
    } else {
      AIOSOfflineDB.getPendingCount().then(count => {
        const queueMsg = count > 0
          ? ` · <strong>${count}</strong> change${count !== 1 ? 's' : ''} queued`
          : '';
        banner.querySelector('.offline-msg').innerHTML =
          `⚡ Working offline — cached version active. Changes will sync when connection restores.${queueMsg}`;
        banner.style.display = 'flex';
      });
    }
  }

  function _updateBanner(msg) {
    const banner = document.getElementById('aios-offline-banner');
    if (banner) {
      banner.querySelector('.offline-msg').textContent = msg;
      banner.style.display = 'flex';
    }
  }

  function _showUpdateBanner() {
    const b = document.getElementById('aios-update-banner');
    if (b) b.style.display = 'flex';
  }

  // ── Form interception ──────────────────────────────────────────────────────
  function _interceptForms() {
    document.addEventListener('submit', async e => {
      const form = e.target;
      // Only intercept forms explicitly marked for offline sync
      if (!form.dataset.offlineSync) return;
      // Never intercept auth forms
      const action = form.action || '';
      if (action.includes('/login') || action.includes('/otp') || action.includes('/logout')) return;
      // If online, proceed normally
      if (_isOnline) return;

      e.preventDefault();
      const data      = new FormData(form);
      const payload   = Object.fromEntries(data.entries());
      const baseVer   = parseInt(form.dataset.baseVersion || '0', 10);
      const resType   = form.dataset.resourceType  || 'form';
      const resId     = form.dataset.resourceId    || '';
      const label     = form.dataset.label         || document.title;

      await AIOSOfflineDB.queueChange({
        resource_type: resType,
        resource_id:   resId,
        field:         resType,
        old_value:     '',
        new_value:     JSON.stringify(payload),
        base_version:  baseVer,
        url:           form.action || window.location.pathname,
        method:        (form.method || 'POST').toUpperCase(),
        payload:       payload,
        label:         label,
      });

      _renderOfflineBanner();
      _showToast('Change queued — will sync when back online', 'info');
    });
  }

  // ── Fetch interception (for XHR/fetch-based API calls) ────────────────────
  function _interceptFetch() {
    const origFetch = window.fetch.bind(window);
    window.fetch = async function (input, init = {}) {
      const url    = typeof input === 'string' ? input : input.url;
      const method = (init.method || 'GET').toUpperCase();

      // Only intercept state-changing calls to our own origin
      if (!['POST','PUT','PATCH','DELETE'].includes(method)) {
        return origFetch(input, init);
      }
      if (url.startsWith('http') && !url.startsWith(location.origin)) {
        return origFetch(input, init);
      }
      // Auth and sync endpoints always pass through
      const path = url.replace(location.origin, '');
      if (path.startsWith('/api/sync') || path.startsWith('/login') ||
          path.startsWith('/otp')      || path.startsWith('/logout')) {
        return origFetch(input, init);
      }
      // File uploads pass through (can't queue binary offline meaningfully)
      if (path.includes('/documents/upload')) {
        if (!_isOnline) {
          _showToast('File uploads require an internet connection', 'error');
          return new Response(
            JSON.stringify({ ok: false, error: 'File uploads are not available offline.' }),
            { status: 503, headers: { 'Content-Type': 'application/json' } }
          );
        }
        return origFetch(input, init);
      }

      // If offline, queue the request
      if (!_isOnline) {
        let payload = {};
        try {
          const bodyText = init.body ? (typeof init.body === 'string' ? init.body : await new Response(init.body).text()) : '';
          if (bodyText.startsWith('{')) {
            payload = JSON.parse(bodyText);
          } else {
            payload = Object.fromEntries(new URLSearchParams(bodyText));
          }
        } catch {}

        // Remove CSRF token from payload (will be re-added on sync)
        delete payload._csrf_token;

        await AIOSOfflineDB.queueChange({
          resource_type: _guessResourceType(path),
          resource_id:   _guessResourceId(path),
          field:         method,
          old_value:     '',
          new_value:     JSON.stringify(payload),
          base_version:  parseInt(payload._base_version || '0', 10),
          url:           path,
          method:        method,
          payload:       payload,
          label:         _labelFromPath(path),
        });

        _renderOfflineBanner();
        _showToast('Change queued — will sync when back online', 'info');
        return new Response(
          JSON.stringify({ ok: false, offline: true, queued: true,
                           message: 'Offline — change queued for sync.' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        );
      }

      return origFetch(input, init);
    };
  }

  // ── Queue flush (runs on reconnect) ───────────────────────────────────────
  async function _syncQueue() {
    const pending = await AIOSOfflineDB.getPendingChanges();
    if (!pending.length) {
      await AIOSOfflineDB.clearSynced();
      return;
    }

    _showToast(`Syncing ${pending.length} queued change${pending.length !== 1 ? 's' : ''}…`, 'info', 4000);

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.content || '';

    try {
      const resp = await fetch(SYNC_URL, {
        method:  'POST',
        headers: {
          'Content-Type':  'application/json',
          'X-CSRF-Token':  csrfToken,
        },
        body: JSON.stringify({ changes: pending }),
      });

      if (!resp.ok) {
        _showToast('Sync failed — will retry later', 'error');
        return;
      }

      const result = await resp.json();
      await AIOSOfflineDB.setMeta('last_sync', new Date().toISOString());

      // Mark accepted changes as synced
      for (const id of (result.accepted_ids || [])) {
        await AIOSOfflineDB.markSynced(id);
      }

      // Handle conflicts
      if (result.conflicts && result.conflicts.length > 0) {
        for (const conflict of result.conflicts) {
          await AIOSOfflineDB.markConflict(conflict.change_id, conflict);
        }
        _showConflictNotification(result.conflicts);
      }

      await AIOSOfflineDB.clearSynced();
      _renderOfflineBanner();

      const synced    = (result.accepted_ids || []).length;
      const conflicts = (result.conflicts    || []).length;

      if (conflicts === 0 && synced > 0) {
        _showToast(`${synced} change${synced !== 1 ? 's' : ''} synced successfully`, 'success');
      } else if (conflicts > 0) {
        _showToast(
          `${synced} synced · ${conflicts} conflict${conflicts !== 1 ? 's' : ''} need review`,
          'warning', 8000
        );
      }

    } catch (err) {
      _showToast('Sync error — will retry on next connection', 'error');
    }
  }

  // ── Conflict UI ────────────────────────────────────────────────────────────
  async function _checkConflictsOnLoad() {
    const conflicts = await AIOSOfflineDB.getConflicts();
    if (conflicts.length > 0) {
      _renderConflictBanner(conflicts.length);
    }
    // Also check server for unresolved conflicts
    try {
      const resp = await fetch(CONFLICTS_URL, { cache: 'no-store' });
      if (resp.ok) {
        const data = await resp.json();
        if (data.count > 0) _renderConflictBanner(data.count);
      }
    } catch {}
  }

  function _showConflictNotification(conflicts) {
    _renderConflictBanner(conflicts.length);
  }

  function _renderConflictBanner(count) {
    const banner = document.getElementById('aios-conflict-banner');
    if (!banner) return;
    banner.querySelector('.conflict-msg').innerHTML =
      `⚠ <strong>${count}</strong> sync conflict${count !== 1 ? 's' : ''} detected — `+
      `<a href="#" onclick="AIOSSyncManager.openConflictPanel();return false;" style="color:inherit;font-weight:800;">Review now</a>`;
    banner.style.display = 'flex';
  }

  function openConflictPanel() {
    let panel = document.getElementById('aios-conflict-panel');
    if (!panel) {
      panel = _buildConflictPanel();
      document.body.appendChild(panel);
    }
    panel.style.display = 'flex';
    _loadConflicts(panel);
  }

  function _buildConflictPanel() {
    const panel = document.createElement('div');
    panel.id    = 'aios-conflict-panel';
    panel.style.cssText = [
      'position:fixed;top:0;right:0;bottom:0;width:480px;z-index:10000;',
      'background:var(--bg-card);border-left:1px solid var(--border);',
      'display:flex;flex-direction:column;box-shadow:-8px 0 32px rgba(0,0,0,0.5);',
    ].join('');
    panel.innerHTML = `
      <div style="padding:16px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;">
        <div>
          <div style="font-size:14px;font-weight:800;letter-spacing:0.5px;">SYNC CONFLICTS</div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Review and resolve before continuing</div>
        </div>
        <button onclick="document.getElementById('aios-conflict-panel').style.display='none'"
                style="background:none;border:none;color:var(--text-muted);font-size:18px;cursor:pointer;">✕</button>
      </div>
      <div id="conflict-list" style="flex:1;overflow-y:auto;padding:16px;"></div>`;
    return panel;
  }

  async function _loadConflicts(panel) {
    const list = panel.querySelector('#conflict-list');
    list.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:32px;">Loading…</div>';

    let serverConflicts = [];
    try {
      const resp = await fetch(CONFLICTS_URL, { cache: 'no-store' });
      if (resp.ok) serverConflicts = (await resp.json()).conflicts || [];
    } catch {}

    const localConflicts  = await AIOSOfflineDB.getConflicts();

    if (!serverConflicts.length && !localConflicts.length) {
      list.innerHTML = '<div style="color:var(--text-muted);text-align:center;padding:32px;">No conflicts — all clear!</div>';
      document.getElementById('aios-conflict-banner').style.display = 'none';
      return;
    }

    list.innerHTML = '';
    serverConflicts.forEach(c => list.appendChild(_buildConflictCard(c, 'server')));
    localConflicts.forEach(c  => list.appendChild(_buildConflictCard(c,  'local')));
  }

  function _buildConflictCard(conflict, source) {
    const card = document.createElement('div');
    card.style.cssText = 'background:var(--bg-input);border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:12px;';
    const localUser  = conflict.local_user_email  || conflict.client_modified_by || 'You (offline)';
    const serverUser = conflict.server_user_email || 'Another user';
    const field      = conflict.field_name        || conflict.field || 'field';
    const resource   = conflict.resource_type     || 'resource';
    const resId      = (conflict.resource_id || '').substring(0, 8);
    const localVal   = conflict.local_display_value  || JSON.stringify(conflict.new_value || '').slice(0, 80);
    const serverVal  = conflict.server_display_value || JSON.stringify(conflict.server_value || '').slice(0, 80);

    card.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;">
        <div>
          <div style="font-size:13px;font-weight:700;color:var(--text-primary);">${_escHtml(resource)} · ${_escHtml(resId)}</div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:2px;">Field: <strong>${_escHtml(field)}</strong></div>
        </div>
        <span style="background:rgba(209,36,47,0.12);color:var(--red);font-size:10px;font-weight:700;padding:3px 8px;border-radius:10px;letter-spacing:1px;">CONFLICT</span>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;">
        <div style="background:rgba(63,185,80,0.06);border:1px solid rgba(63,185,80,0.2);border-radius:6px;padding:10px;">
          <div style="font-size:10px;color:var(--green);font-weight:700;letter-spacing:1px;margin-bottom:4px;">YOUR OFFLINE CHANGE</div>
          <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">By ${_escHtml(localUser)}</div>
          <div style="font-size:12px;word-break:break-all;">${_escHtml(localVal)}</div>
        </div>
        <div style="background:rgba(227,179,65,0.06);border:1px solid rgba(227,179,65,0.2);border-radius:6px;padding:10px;">
          <div style="font-size:10px;color:var(--gold);font-weight:700;letter-spacing:1px;margin-bottom:4px;">SERVER VERSION</div>
          <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">By ${_escHtml(serverUser)}</div>
          <div style="font-size:12px;word-break:break-all;">${_escHtml(serverVal)}</div>
        </div>
      </div>
      <div style="font-size:11px;color:var(--text-muted);margin-bottom:10px;">
        Contact: <a href="mailto:${_escHtml(serverUser)}" style="color:var(--gold);">${_escHtml(serverUser)}</a>
        if you need to coordinate before resolving.
      </div>
      <div style="display:flex;gap:8px;">
        <button onclick="AIOSSyncManager.resolveConflict('${conflict.id || conflict.id}','local')"
                style="flex:1;background:rgba(63,185,80,0.12);color:var(--green);border:1px solid rgba(63,185,80,0.3);border-radius:6px;padding:7px;font-size:12px;font-weight:700;cursor:pointer;">
          Use My Version
        </button>
        <button onclick="AIOSSyncManager.resolveConflict('${conflict.id || conflict.id}','server')"
                style="flex:1;background:rgba(227,179,65,0.12);color:var(--gold);border:1px solid rgba(227,179,65,0.3);border-radius:6px;padding:7px;font-size:12px;font-weight:700;cursor:pointer;">
          Use Server Version
        </button>
        <button onclick="AIOSSyncManager.dismissConflict('${conflict.id || conflict.id}',this.closest('[style]'))"
                style="background:none;border:1px solid var(--border);border-radius:6px;padding:7px 12px;font-size:12px;color:var(--text-muted);cursor:pointer;">
          Dismiss
        </button>
      </div>`;
    return card;
  }

  async function resolveConflict(conflictId, resolution) {
    const csrfToken = document.querySelector('meta[name=csrf-token]')?.content || '';
    try {
      await fetch(`/api/sync/conflicts/${conflictId}/resolve`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
        body:    JSON.stringify({ resolution }),
      });
    } catch {}
    // Also clear from IndexedDB
    const changes = await AIOSOfflineDB.getAllChanges();
    const match   = changes.find(c => c.conflict_data?.id === conflictId);
    if (match) await AIOSOfflineDB.markSynced(match.id);

    _showToast(`Conflict resolved — ${resolution === 'local' ? 'your' : 'server'} version kept`, 'success');
    const panel = document.getElementById('aios-conflict-panel');
    if (panel) _loadConflicts(panel);
  }

  async function dismissConflict(conflictId, cardEl) {
    const csrfToken = document.querySelector('meta[name=csrf-token]')?.content || '';
    try {
      await fetch(`/api/sync/conflicts/${conflictId}/dismiss`, {
        method: 'POST',
        headers: { 'X-CSRF-Token': csrfToken },
      });
    } catch {}
    if (cardEl) cardEl.remove();
  }

  // ── Toast notifications ────────────────────────────────────────────────────
  function _showToast(msg, type = 'info', duration = 4000) {
    const colors = {
      success: 'var(--green)',
      error:   'var(--red)',
      warning: 'var(--gold)',
      info:    '#58a6ff',
    };
    const t = document.createElement('div');
    t.innerHTML = msg;
    t.style.cssText = [
      'position:fixed;bottom:24px;right:24px;padding:12px 18px;border-radius:8px;',
      `font-size:13px;font-weight:600;z-index:9998;color:#fff;`,
      `background:${colors[type] || colors.info};`,
      'box-shadow:0 4px 20px rgba(0,0,0,0.4);max-width:320px;line-height:1.4;',
      'animation:aios-fadein 0.2s ease;',
    ].join('');
    document.body.appendChild(t);
    setTimeout(() => {
      t.style.animation = 'aios-fadeout 0.3s ease forwards';
      setTimeout(() => t.remove(), 300);
    }, duration);
  }

  // ── Helpers ────────────────────────────────────────────────────────────────
  function _guessResourceType(path) {
    if (path.includes('/documents')) return 'document';
    if (path.includes('/domain'))    return 'domain';
    if (path.includes('/team'))      return 'user';
    if (path.includes('/admin'))     return 'tenant';
    return 'form';
  }

  function _guessResourceId(path) {
    const parts = path.split('/').filter(Boolean);
    const uuidRe = /^[0-9a-f\-]{36}$/i;
    return parts.find(p => uuidRe.test(p)) || '';
  }

  function _labelFromPath(path) {
    const map = {
      '/documents':    'Document change',
      '/domain':       'Domain registration',
      '/team':         'Team member change',
      '/update':       'Record update',
      '/assign':       'Assignment change',
    };
    for (const [k, v] of Object.entries(map)) {
      if (path.includes(k)) return v;
    }
    return 'Change';
  }

  function _escHtml(str) {
    return String(str || '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ── Expose public API ──────────────────────────────────────────────────────
  window.AIOSSyncManager = {
    init, openConflictPanel, resolveConflict, dismissConflict,
    syncNow: _syncQueue,
    isOnline: () => _isOnline,
  };

  // Inject keyframe CSS
  const style = document.createElement('style');
  style.textContent = `
    @keyframes aios-fadein  { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:none} }
    @keyframes aios-fadeout { from{opacity:1} to{opacity:0;transform:translateY(8px)} }
  `;
  document.head.appendChild(style);

  // Auto-init
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
