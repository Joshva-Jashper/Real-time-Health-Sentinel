/* ═══════════════════════════════════════════════
   TestSentry Dashboard — App Logic
   Premium Redesign
═══════════════════════════════════════════════ */

const API = "";  // Use relative URLs — same origin as the serving host

let currentRunId   = null;
let allTestResults = [];
let historyChart   = null;
let passRateChart  = null;
let scoreRingChart = null;

window.addEventListener("DOMContentLoaded", () => {
  loadAll();
});

async function loadAll() {
  spinRefresh(true);
  try {
    await loadRuns();
    if (currentRunId) {
      await Promise.all([
        loadOverview(),
        loadTests(),
        loadFlaky(),
        loadRisk(),
        loadAiCache(),
        loadHistory(),
      ]);
    }
  } catch (e) {
    showToast("⚠️ API unreachable — is the server running? (port 8088)", true);
  }
  spinRefresh(false);
}

function switchTab(tab, btn) {
  document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));
  document.getElementById(`tab-${tab}`).classList.add("active");
  btn.classList.add("active");

  const titles = {
    overview: "Overview", tests: "Test Results", flaky: "Flakiness Analysis",
    risk: "Risk & Ownership", ai: "AI Triage Cache", history: "Run History",
  };
  document.getElementById("page-title").textContent = titles[tab] || tab;
}

async function loadRuns() {
  const runs = await apiFetch("/api/runs?limit=20");
  const sel  = document.getElementById("run-selector");
  sel.innerHTML = "";
  if (!runs || runs.length === 0) {
    sel.innerHTML = `<option value="">No runs found</option>`;
    return;
  }
  runs.forEach((r, i) => {
    const opt = document.createElement("option");
    opt.value = r.run_id;
    const dt  = new Date(r.started).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "short" });
    opt.textContent = `${r.run_id}  (${dt})`;
    if (i === 0) opt.selected = true;
    sel.appendChild(opt);
  });
  currentRunId = sel.value;
  document.getElementById("run-badge").textContent = `Run ID: ${currentRunId.substring(0,8)}`;
}

function onRunChange() {
  currentRunId = document.getElementById("run-selector").value;
  document.getElementById("run-badge").textContent = `Run ID: ${currentRunId.substring(0,8)}`;
  spinRefresh(true);
  Promise.all([
    loadOverview(), loadTests(), loadFlaky(), loadAiCache(),
  ]).finally(() => spinRefresh(false));
}

async function loadOverview() {
  const [health, regression, aiStats] = await Promise.all([
    apiFetch(`/api/health/${currentRunId}`),
    apiFetch(`/api/regression/${currentRunId}`),
    apiFetch(`/api/ai-stats/${currentRunId}`),
  ]);

  renderHealthRing(health);
  renderDimensions(health);
  renderRegression(regression);
  renderAiStats(aiStats);
}

function renderHealthRing(h) {
  if (!h) return;
  const score = h.total_score || 0;
  
  // Animate number
  animateNumber(document.getElementById("score-num"), score, 1000);
  
  document.getElementById("score-pass-val").textContent = `${h.pass_rate}%`;
  document.getElementById("score-flaky-val").textContent = h.flaky_count;
  document.getElementById("score-dur-val").textContent = `${h.avg_duration}s`;

  const gradeBadge = document.getElementById("grade-badge");
  gradeBadge.textContent = h.grade;
  gradeBadge.className   = `grade-badge grade-${h.grade}`;

  const ctx = document.getElementById("scoreRing").getContext("2d");
  
  // Premium gradient for doughnut
  const gradient = ctx.createLinearGradient(0, 0, 0, 200);
  if (score >= 80) { gradient.addColorStop(0, "#34d399"); gradient.addColorStop(1, "#059669"); }
  else if (score >= 60) { gradient.addColorStop(0, "#fbbf24"); gradient.addColorStop(1, "#d97706"); }
  else { gradient.addColorStop(0, "#f87171"); gradient.addColorStop(1, "#dc2626"); }

  if (scoreRingChart) scoreRingChart.destroy();
  scoreRingChart = new Chart(ctx, {
    type: "doughnut",
    data: {
      datasets: [{
        data: [score, 100 - score],
        backgroundColor: [gradient, "rgba(255,255,255,0.03)"],
        borderWidth: 0,
        borderRadius: 20,
        hoverOffset: 0
      }]
    },
    options: {
      cutout: "80%",
      animation: { animateRotate: true, duration: 1500, easing: 'easeOutQuart' },
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
    }
  });
}

function renderDimensions(h) {
  if (!h) return;
  const dims = [
    { id: "dim-speed",     score: h.speed_score },
    { id: "dim-stability", score: h.stability_score },
    { id: "dim-flakiness", score: h.flakiness_score },
    { id: "dim-coverage",  score: h.coverage_score },
    { id: "dim-quality",   score: h.quality_score },
  ];
  dims.forEach(d => {
    const el = document.getElementById(d.id);
    if (!el) return;
    el.querySelector(".dim-score-val").textContent = `${d.score}/20`;
    setTimeout(() => {
      el.querySelector(".dim-bar-fill").style.width = `${(d.score / 20) * 100}%`;
    }, 100);
  });
}

function renderRegression(r) {
  if (!r) return;
  document.getElementById("reg-nf").textContent = r.NEWLY_FAILING  || 0;
  document.getElementById("reg-fx").textContent = r.FIXED          || 0;
  document.getElementById("reg-sf").textContent = r.STILL_FAILING  || 0;
  document.getElementById("reg-st").textContent = r.STABLE         || 0;
  document.getElementById("reg-nt").textContent = r.NEW_TEST       || 0;
  document.getElementById("reg-ro").textContent = r.REOPENED       || 0;
}

function renderAiStats(s) {
  if (!s) return;
  document.getElementById("ai-total").textContent = s.total_failures || 0;
  document.getElementById("ai-hits").textContent  = s.cache_hits     || 0;
  document.getElementById("ai-calls").textContent = s.api_calls      || 0;

  const total = (s.cache_hits || 0) + (s.api_calls || 0);
  const eff   = total > 0 ? Math.round((s.cache_hits / total) * 100) : 0;
  
  document.getElementById("ai-eff").textContent = `${eff}%`;
  
  setTimeout(() => {
    document.getElementById("cache-bar-fill").style.width = `${eff}%`;
  }, 100);
  document.getElementById("cache-bar-label").textContent = `${eff}% Saved`;
}

let autoRefreshTimer = null;
function toggleAutoRefresh(cb) {
  const lbl = document.querySelector(".sidebar-status");
  if (cb.checked) {
    autoRefreshTimer = setInterval(loadAll, 5000);
    showToast("⚡ Auto Live refresh enabled (5s)");
    lbl.style.display = 'flex';
  } else {
    if (autoRefreshTimer) clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
    showToast("Auto refresh paused");
    lbl.style.display = 'none';
  }
}

async function loadTests() {
  allTestResults = await apiFetch(`/api/tests/${currentRunId}`) || [];
  renderTestsTable(allTestResults);
}

function renderTestsTable(rows) {
  const tbody = document.getElementById("tests-tbody");
  if (!rows || rows.length === 0) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="6">No test results found for this run</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map((r) => `
    <tr>
      <td><span class="mono truncate" title="${esc(r.test_name)}">${esc(r.test_name)}</span></td>
      <td><span class="badge badge-${r.status.toLowerCase()}">${r.status === "PASSED" ? "✅" : "❌"} ${r.status}</span></td>
      <td><span class="badge badge-${labelClass(r.label)}">${labelIcon(r.label)} ${r.label}</span></td>
      <td><span class="mono">${r.duration?.toFixed(4)}s</span></td>
      <td><span class="truncate-lg" style="font-size:12px;color:var(--text3)" title="${esc(r.error_msg || '')}">${esc(r.error_msg || '—')}</span></td>
      <td>
        ${r.status === "FAILED" && r.error_msg ? `
          <button class="btn-primary" onclick="triggerTriage('${esc(r.test_name)}', '${esc(r.error_msg.replace(/'/g, "\\'"))}')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>
            Triage
          </button>
        ` : '—'}
      </td>
    </tr>
  `).join("");
}

async function triggerTriage(test_name, error_msg) {
  showToast("🤖 Running Local Triage...");
  try {
    const res = await fetch(`${API}/api/triage-test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ test_name, error_msg })
    });
    const data = await res.json();
    if (res.ok && data) {
      showModal(test_name, data);
      loadAiCache();
    } else {
      showToast(`⚠️ Triage failed: ${data.detail || "Error"}`, true);
    }
  } catch (e) {
    showToast("⚠️ Could not reach AI triage service", true);
  }
}

function showModal(test_name, data) {
  const html = `
    <div class="triage-block">
      <div class="triage-lbl">Test Failed</div>
      <div class="triage-val mono" style="font-size:13px">${esc(test_name)}</div>
    </div>
    <div style="display:flex; gap:16px;">
      <div class="triage-block" style="flex:1">
        <div class="triage-lbl">Category</div>
        <div class="triage-val"><span class="badge badge-${data.category?.toLowerCase()}">${categoryIcon(data.category)} ${data.category}</span></div>
      </div>
      <div class="triage-block" style="flex:1">
        <div class="triage-lbl">Confidence</div>
        <div class="triage-val">${data.confidence_pct}%</div>
      </div>
    </div>
    <div class="triage-block">
      <div class="triage-lbl">Explanation</div>
      <div class="triage-val">${esc(data.why_it_failed)}</div>
    </div>
    <div class="triage-block" style="background:rgba(16,185,129,0.1); border-color:rgba(16,185,129,0.2);">
      <div class="triage-lbl" style="color:var(--green)">Suggested Fix</div>
      <div class="triage-val fix">${esc(data.suggested_fix)}</div>
    </div>
  `;
  document.getElementById("modal-body").innerHTML = html;
  document.getElementById("triage-modal").classList.add("open");
}
function closeModal(e) {
  if (e.target.id === 'triage-modal') document.getElementById("triage-modal").classList.remove("open");
}

function filterTests() {
  const q      = document.getElementById("test-search").value.toLowerCase();
  const status = document.getElementById("status-filter").value;
  const label  = document.getElementById("label-filter").value;
  const rows   = allTestResults.filter(r => {
    if (q      && !r.test_name.toLowerCase().includes(q)) return false;
    if (status && r.status !== status)                     return false;
    if (label  && r.label  !== label)                      return false;
    return true;
  });
  renderTestsTable(rows);
}

async function loadFlaky() {
  const data = await apiFetch(`/api/flaky?run_id=${currentRunId}`) || {};
  const s    = data.summary || {};
  const tests= data.tests   || [];

  document.getElementById("fl-critical").textContent = s.critical_flaky  || 0;
  document.getElementById("fl-high").textContent     = s.high_flaky      || 0;
  document.getElementById("fl-medium").textContent   = s.medium_flaky    || 0;
  document.getElementById("fl-avg").textContent      = `${s.avg_flakiness || 0}%`;

  const tbody = document.getElementById("flaky-tbody");
  if (!tests.length) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="8">✅ No flaky tests detected!</td></tr>`;
    return;
  }
  tbody.innerHTML = tests.map((t, i) => `
    <tr>
      <td><span class="mono">${i + 1}</span></td>
      <td><span class="mono truncate" title="${esc(t.test_name)}">${esc(t.test_name)}</span></td>
      <td><strong style="color:${flakyColor(t.flakiness_pct)}">${t.flakiness_pct}%</strong></td>
      <td><span class="badge badge-${t.flakiness_rating.toLowerCase()}">${t.flakiness_rating}</span></td>
      <td><span class="mono">${t.total_runs}</span></td>
      <td><span class="mono" style="color:var(--green)">${t.passed}</span></td>
      <td><span class="mono">${t.status_changes}</span></td>
      <td><span class="trend-${t.trend?.toLowerCase()}">${trendIcon(t.trend)}</span></td>
    </tr>
  `).join("");
}

async function loadRisk() {
  const data = await apiFetch("/api/risk") || [];
  const tbody = document.getElementById("risk-tbody");
  if (!data.length) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="6">✅ No high-risk modules detected!</td></tr>`;
    return;
  }
  tbody.innerHTML = data.map(r => `
    <tr>
      <td><span class="mono truncate" title="${esc(r.filepath)}" style="max-width:280px">${esc(r.filepath)}</span></td>
      <td><span style="font-size:12px;color:var(--text2)">${esc(ownerShort(r.owner))}</span></td>
      <td><span class="mono">${r.change_count}</span></td>
      <td><span class="mono" style="color:var(--red)">${r.failure_count}</span></td>
      <td><span class="mono" style="font-weight:700">${r.risk_score}</span></td>
      <td><span class="badge badge-risk-${r.risk_level.toLowerCase()}">${r.risk_level}</span></td>
    </tr>
  `).join("");
}

async function loadAiCache() {
  const data  = await apiFetch("/api/triage-cache") || [];
  const tbody = document.getElementById("ai-tbody");
  if (!data.length) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="7">No cached triage results yet. Run pytest to populate.</td></tr>`;
    return;
  }
  tbody.innerHTML = data.map(r => `
    <tr>
      <td><span class="mono" style="font-size:11px;color:var(--text3)">${esc(r.fingerprint)}</span></td>
      <td><span class="badge badge-${r.category?.toLowerCase()}">${categoryIcon(r.category)} ${r.category}</span></td>
      <td>
        <div class="conf-bar-wrap">
          <div class="conf-bar"><div class="conf-fill" style="width:${r.confidence_pct}%"></div></div>
          <span class="conf-pct">${r.confidence_pct}%</span>
        </div>
      </td>
      <td><span class="truncate" style="max-width:220px;font-size:12px" title="${esc(r.why_it_failed)}">${esc(r.why_it_failed)}</span></td>
      <td><span class="truncate" style="max-width:220px;font-size:12px;color:var(--green)" title="${esc(r.suggested_fix)}">${esc(r.suggested_fix)}</span></td>
      <td><span class="mono" style="font-size:11px">${esc(r.affected_module || '—')}</span></td>
      <td><strong style="color:var(--accent-2)">${r.hit_count}</strong></td>
    </tr>
  `).join("");
}

async function loadHistory() {
  const data = await apiFetch("/api/history?limit=20") || [];

  const tbody = document.getElementById("history-tbody");
  tbody.innerHTML = [...data].reverse().map(r => `
    <tr>
      <td><span class="mono">${esc(r.run_id.substring(0,8))}</span></td>
      <td><span style="font-size:12px;color:var(--text3)">${new Date(r.started).toLocaleString("en-IN",{dateStyle:"short",timeStyle:"short"})}</span></td>
      <td><strong style="color:${scoreColor(r.total_score)}">${r.total_score}/100</strong></td>
      <td><span class="badge grade-badge grade-${r.grade}" style="font-size:11px;padding:2px 8px">${r.grade}</span></td>
      <td><span class="mono">${r.pass_rate}%</span></td>
      <td><span class="mono">${r.flaky_count}</span></td>
    </tr>
  `).join("");

  const labels = data.map(r => r.run_id.substring(0,6));
  const scores = data.map(r => r.total_score);
  const passes = data.map(r => r.pass_rate);

  Chart.defaults.color = '#64748b';
  Chart.defaults.font.family = "'Inter', sans-serif";

  const chartDefaults = {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false }, tooltip: { backgroundColor: '#1e2235', titleColor: '#fff', bodyColor: '#cbd5e1', padding: 12, cornerRadius: 8, displayColors: false } },
    scales: {
      x: { grid: { color: "rgba(255,255,255,0.05)", drawBorder: false }, ticks: { font: { family: "'JetBrains Mono'", size: 10 } } },
      y: { grid: { color: "rgba(255,255,255,0.05)", drawBorder: false }, min: 0, max: 100 }
    }
  };

  const ctxH = document.getElementById("historyChart").getContext("2d");
  const gradH = ctxH.createLinearGradient(0,0,0,300);
  gradH.addColorStop(0, 'rgba(108,99,255,0.4)');
  gradH.addColorStop(1, 'rgba(108,99,255,0.0)');

  if (historyChart) historyChart.destroy();
  historyChart = new Chart(ctxH, {
    type: "line",
    data: {
      labels,
      datasets: [{
        data: scores, borderColor: "#a78bfa", backgroundColor: gradH,
        fill: true, tension: 0.4, pointBackgroundColor: "#a78bfa", pointBorderColor: "#fff", pointRadius: 4, pointHoverRadius: 6, borderWidth: 3,
      }]
    },
    options: chartDefaults
  });

  const ctxP = document.getElementById("passRateChart").getContext("2d");
  if (passRateChart) passRateChart.destroy();
  passRateChart = new Chart(ctxP, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        data: passes,
        backgroundColor: passes.map(p => p >= 95 ? "rgba(16,185,129,0.8)" : p >= 70 ? "rgba(245,158,11,0.8)" : "rgba(239,68,68,0.8)"),
        borderRadius: 6, borderSkipped: false
      }]
    },
    options: chartDefaults
  });
}

// ── Helpers ──
async function apiFetch(path) {
  try {
    const res = await fetch(`${API}${path}`);
    if (!res.ok) throw new Error(res.statusText);
    return await res.json();
  } catch (e) {
    console.warn("API error", path, e);
    return null;
  }
}

function spinRefresh(on) {
  const btn = document.querySelector(".refresh-btn");
  if (on) btn.classList.add("spinning");
  else btn.classList.remove("spinning");
}

function showToast(msg, isError = false) {
  const t = document.getElementById("toast");
  t.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>${msg}`;
  t.className = `toast${isError ? " error" : ""} show`;
  setTimeout(() => t.classList.remove("show"), 4000);
}

function animateNumber(obj, end, duration) {
  let start = 0;
  let startTimestamp = null;
  const step = (timestamp) => {
    if (!startTimestamp) startTimestamp = timestamp;
    const progress = Math.min((timestamp - startTimestamp) / duration, 1);
    obj.innerHTML = Math.floor(progress * (end - start) + start);
    if (progress < 1) window.requestAnimationFrame(step);
  };
  window.requestAnimationFrame(step);
}

function esc(str) {
  if (!str) return "";
  return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function labelClass(label) {
  const map = { NEWLY_FAILING:"newly", FIXED:"fixed", STILL_FAILING:"still", STABLE:"stable", NEW_TEST:"new_test", REOPENED:"reopened" };
  return map[label] || "unknown";
}
function labelIcon(label) {
  const map = { NEWLY_FAILING:"🔴", FIXED:"✅", STILL_FAILING:"⚠️", STABLE:"✓", NEW_TEST:"🆕", REOPENED:"🔁" };
  return map[label] || "";
}
function trendIcon(trend) {
  if (trend === "IMPROVING") return "📉";
  if (trend === "WORSENING") return "📈";
  return "➡️";
}
function categoryIcon(cat) {
  const map = { REAL_BUG:"🐛", FLAKY:"🎲", ENV_ISSUE:"🌐", DATA_ISSUE:"📦" };
  return map[cat] || "❓";
}
function ownerShort(owner) {
  if (!owner || owner === "unowned") return "Unassigned";
  return owner.includes("@") ? owner.split("@")[0] : owner;
}
function flakyColor(pct) {
  if (pct >= 70) return "var(--red)";
  if (pct >= 40) return "var(--orange)";
  if (pct >= 10) return "var(--yellow)";
  return "var(--green)";
}
function scoreColor(score) {
  if (score >= 80) return "var(--green)";
  if (score >= 60) return "var(--yellow)";
  return "var(--red)";
}
