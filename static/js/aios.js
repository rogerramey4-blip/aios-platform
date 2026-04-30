/* AIOS Dashboard — v1.0 */

// ── Clock ─────────────────────────────────────────────────────
function updateClock() {
  const el = document.getElementById('clock');
  if (!el) return;
  const now = new Date();
  let h = now.getHours();
  const m = String(now.getMinutes()).padStart(2, '0');
  const ampm = h >= 12 ? 'PM' : 'AM';
  h = h % 12 || 12;
  el.textContent = `${h}:${m} ${ampm}`;
}
setInterval(updateClock, 1000);

// ── Theme ─────────────────────────────────────────────────────
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  const btn = document.getElementById('theme-btn');
  if (btn) btn.textContent = t === 'light' ? '🌙 Dark' : '☀ Light';
  localStorage.setItem('aios-theme', t);
}

function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme') || 'dark';
  applyTheme(cur === 'light' ? 'dark' : 'light');
}

// ── Animate Progress Bars ─────────────────────────────────────
function animateBars() {
  const bars = document.querySelectorAll(
    '.bar-fill, .pipe-fill, .ar-fill'
  );
  bars.forEach(b => {
    const target = b.getAttribute('data-w') || b.style.width;
    b.setAttribute('data-w', target);
    b.style.width = '0';
    requestAnimationFrame(() => setTimeout(() => { b.style.width = target; }, 120));
  });
}

// ── Live Agent Feed ───────────────────────────────────────────
const FEEDS = {
  agency: [
    ['Client Health Monitor', 'Scanning 24 clients · Updated just now'],
    ['Churn Predictor',       'TechStart Inc: engagement score dropped 12pts'],
    ['Proposal Generator',    'Riviera Realty draft — 3 pages ready for review'],
    ['Client Health Monitor', 'Apex Dental: agent uptime restored, monitoring'],
    ['ROI Reporter',          'Metro HVAC report compiled · $14,200 value shown'],
    ['Email Drafter',         '3 outreach drafts queued · Avg. open rate: 34%'],
    ['Lead Intelligence',     'New inbound: "Harborview Dental" — scored 87/100'],
  ],
  medical: [
    ['Prior Auth Bot',     'Processing 4 urgent auths · Aetna response pending'],
    ['Claim Scrubber',     '6 claims reviewed · 1 modifier-25 issue flagged'],
    ['Recall Scheduler',   'SMS batch queued: 47 patients · Delivery ETA 9:00 AM'],
    ['Denial Analyzer',    'Aetna appeal letter drafted · 82% win probability'],
    ['Insurance Verifier', "Thursday's 41 appointments verified: 39 active"],
    ['Prior Auth Bot',     'James H. auth submitted to Aetna · Expected: 24hrs'],
    ['SOAP Notes Agent',   'Template ready · Waiting for Dr. Chen voice input'],
  ],
};

let feedIdx = 0;

function tickAgents() {
  const ind = document.body.dataset.industry;
  const feed = FEEDS[ind];
  if (!feed) return;

  const items = document.querySelectorAll('.agent-item');
  if (!items.length) return;

  const [agentName, msg] = feed[feedIdx % feed.length];
  feedIdx++;

  items.forEach(item => {
    const name = item.querySelector('.agent-name');
    if (name && name.textContent.trim() === agentName) {
      const detail = item.querySelector('.agent-detail');
      if (!detail) return;
      detail.style.opacity = '0';
      setTimeout(() => {
        detail.textContent = msg;
        detail.style.opacity = '1';
      }, 280);
    }
  });
}
setInterval(tickAgents, 3800);

// ── Dismissed Actions ─────────────────────────────────────────
document.addEventListener('click', e => {
  const action = e.target.closest('.action');
  if (!action) return;
  const badge = action.querySelector('.badge');
  if (badge && (badge.classList.contains('b-urgent') ||
                badge.classList.contains('b-due'))) {
    // In real app: PATCH /api/aios/actions/:id/dismiss
    action.style.transition = 'opacity .4s ease';
    action.style.opacity = '0.3';
  }
});

// ── Init ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Restore theme (prevent FOUC via inline script in <head>, but also here as fallback)
  const saved = localStorage.getItem('aios-theme') || 'dark';
  applyTheme(saved);

  updateClock();
  animateBars();
  tickAgents(); // immediate first tick
});
