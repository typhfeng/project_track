const colors = {
  finance: '#0f7b7b',
  engineering: '#dc6b1f',
  soc_auto_design: '#356ad9',
  family: '#5f7f2a'
};

let dashboard = null;
let charts = {};
let configData = null;

function esc(s) {
  return String(s || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function showError(message) {
  const summary = document.getElementById('summaryCards');
  const tracks = document.getElementById('trackCards');
  const table = document.getElementById('repoTableBody');
  const issueList = document.getElementById('issueList');
  const meta = document.getElementById('searchMeta');
  const msg = `<article class="card"><div class="label">Error</div><div>${message}</div></article>`;
  summary.innerHTML = msg;
  tracks.innerHTML = '';
  table.innerHTML = '';
  issueList.innerHTML = `<div class="muted">${message}</div>`;
  meta.textContent = '0 results';
}

function number(value) {
  return new Intl.NumberFormat('en-US').format(value || 0);
}

function trackLabel(track) {
  if (!dashboard) return track;
  return dashboard.trend.labels_map[track] || track;
}

function stageBadge(stage) {
  const map = {
    Accelerating: 'ok',
    'In Progress': 'ok',
    Maintaining: 'warn',
    'At Risk': 'danger',
    Stalled: 'danger',
    'Not Started': 'warn'
  };
  return map[stage] || 'warn';
}

function setGeneratedAt() {
  const e = document.getElementById('generatedAt');
  if (!dashboard) {
    e.textContent = 'Generated: -';
    return;
  }
  const dt = new Date(dashboard.generated_at);
  e.textContent = `Generated: ${dt.toLocaleString()}`;
}

function renderSummaryCards() {
  if (!dashboard) return;
  const s = dashboard.summary;
  const cards = [
    ['Tracked Repos', s.total_repos],
    ['Active Repos (30d)', s.active_repos_30d],
    ['Commits (30d)', s.total_commits_30d],
    ['Commits (90d)', s.total_commits_90d],
    ['Dirty Repos', s.dirty_repos],
    ['Issue Hits', s.total_issue_hits]
  ];
  document.getElementById('summaryCards').innerHTML = cards
    .map(
      ([label, value]) =>
        `<article class="card"><div class="label">${label}</div><div class="value">${number(value)}</div></article>`
    )
    .join('');
}

function renderTrackCards() {
  if (!dashboard) return;
  const wrap = document.getElementById('trackCards');
  const entries = Object.entries(dashboard.track_summary);
  wrap.innerHTML = entries
    .map(([track, s]) => {
      return `
        <article class="card track" style="border-left-color:${colors[track] || '#0f7b7b'}">
          <div class="label">${s.label}</div>
          <div class="value">${s.avg_progress}</div>
          <div class="muted">avg progress</div>
          <div class="muted">repos: ${s.repos} · active: ${s.active_repos}</div>
          <div class="muted">30d commits: ${s.commits_30d} · issue hits: ${s.issues}</div>
        </article>
      `;
    })
    .join('');
}

function mountChart(id, config) {
  if (charts[id]) {
    charts[id].destroy();
  }
  const ctx = document.getElementById(id).getContext('2d');
  charts[id] = new Chart(ctx, config);
}

function renderCharts() {
  if (!dashboard) return;
  const labels = dashboard.trend.labels;
  const series = dashboard.trend.series;

  const throughputLabels = Object.keys(dashboard.track_summary);
  const throughputValues = throughputLabels.map((t) => dashboard.track_summary[t].commits_30d);

  mountChart('throughputChart', {
    type: 'bar',
    data: {
      labels: throughputLabels.map((t) => trackLabel(t)),
      datasets: [
        {
          label: 'Commits (30d)',
          data: throughputValues,
          backgroundColor: throughputLabels.map((t) => colors[t] || '#0f7b7b')
        }
      ]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } }
    }
  });

  mountChart('trendChart', {
    type: 'line',
    data: {
      labels,
      datasets: Object.keys(series).map((t) => ({
        label: trackLabel(t),
        data: series[t],
        borderColor: colors[t] || '#0f7b7b',
        backgroundColor: `${colors[t] || '#0f7b7b'}22`,
        tension: 0.25,
        fill: false
      }))
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      stacked: false
    }
  });

  mountChart('allocationChart', {
    type: 'doughnut',
    data: {
      labels: throughputLabels.map((t) => trackLabel(t)),
      datasets: [
        {
          data: throughputValues,
          backgroundColor: throughputLabels.map((t) => colors[t] || '#0f7b7b')
        }
      ]
    },
    options: {
      plugins: {
        legend: {
          position: 'bottom'
        }
      }
    }
  });

  const topRepos = [...dashboard.repos]
    .sort((a, b) => b.progress.score - a.progress.score)
    .slice(0, 12);

  mountChart('progressChart', {
    type: 'bar',
    data: {
      labels: topRepos.map((r) => r.name),
      datasets: [
        {
          label: 'Progress Score',
          data: topRepos.map((r) => r.progress.score),
          backgroundColor: topRepos.map((r) => colors[r.track] || '#0f7b7b')
        }
      ]
    },
    options: {
      indexAxis: 'y',
      plugins: { legend: { display: false } },
      scales: {
        x: {
          suggestedMin: 0,
          suggestedMax: 100
        }
      }
    }
  });
}

function renderRepoTable() {
  if (!dashboard) return;
  const rows = dashboard.repos.map((r) => {
    const dirty = r.status.dirty.modified + r.status.dirty.untracked;
    const last = r.status.last_commit.date ? new Date(r.status.last_commit.date).toLocaleDateString() : '-';
    const progress = r.progress.score;
    const stage = r.progress.stage;

    return `
      <tr>
        <td>
          <div><strong>${r.name}</strong></div>
          <div class="muted">${r.path}</div>
        </td>
        <td><span class="badge">${trackLabel(r.track)}</span></td>
        <td>
          <div>${r.status.branch}</div>
          <div class="muted">${r.status.status_line || '-'}</div>
        </td>
        <td>${r.commits.last_30d}</td>
        <td>${dirty}</td>
        <td>${r.issues.total}</td>
        <td>
          <div class="progress-wrap">
            <div class="progress-bar"><span style="width:${progress}%"></span></div>
            <div class="progress-text">${progress} · <span class="badge">${stage}</span></div>
          </div>
        </td>
        <td>
          <div>${last}</div>
          <div class="muted">${r.status.last_commit.hash || ''}</div>
        </td>
      </tr>
    `;
  });

  document.getElementById('repoTableBody').innerHTML = rows.join('');
}

function renderIssues(results, query) {
  const list = document.getElementById('issueList');
  const meta = document.getElementById('searchMeta');
  meta.textContent = `${results.length} results${query ? ` for "${query}"` : ''}`;

  if (!results.length) {
    list.innerHTML = '<div class="muted">No matching issues.</div>';
    return;
  }

  list.innerHTML = results
    .slice(0, 120)
    .map((item) => {
      return `
        <article class="issue-item">
          <div class="issue-meta">${trackLabel(item.track)} · ${item.repo} · ${item.type}</div>
          <div><strong>${item.title}</strong></div>
          <div>${item.content}</div>
        </article>
      `;
    })
    .join('');
}

function renderManualRepoTable() {
  const body = document.getElementById('manualRepoBody');
  const meta = document.getElementById('manualRepoMeta');
  if (!configData) {
    body.innerHTML = '';
    meta.textContent = '';
    return;
  }

  const include = configData.include_repos || [];
  const overrides = configData.track_overrides || {};
  meta.textContent = `${include.length} manually included repos`;
  body.innerHTML = include
    .map((p) => {
      const track = overrides[p] || 'auto';
      return `
        <tr>
          <td><code>${esc(p)}</code></td>
          <td>${esc(track)}</td>
          <td><button class="btn-secondary" data-remove-path="${esc(p)}">Remove</button></td>
        </tr>
      `;
    })
    .join('');

  body.querySelectorAll('button[data-remove-path]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const path = btn.getAttribute('data-remove-path');
      await removeRepo(path);
    });
  });
}

async function loadConfig() {
  const res = await fetch('/api/config');
  const payload = await res.json();
  if (!res.ok) {
    throw new Error(payload.error || 'failed to load config');
  }
  configData = payload;
  renderManualRepoTable();
}

async function addRepo(path, track) {
  const res = await fetch('/api/repos', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, track })
  });
  const payload = await res.json();
  if (!res.ok || !payload.ok) {
    throw new Error(payload.error || 'failed to add repo');
  }
}

async function removeRepo(path) {
  const res = await fetch('/api/repos', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path })
  });
  const payload = await res.json();
  if (!res.ok || !payload.ok) {
    throw new Error(payload.error || 'failed to remove repo');
  }
  await loadConfig();
  await loadDashboard(true);
}

async function loadDashboard(refresh = false) {
  const res = await fetch(`/api/dashboard${refresh ? '?refresh=1' : ''}`);
  const payload = await res.json();
  if (!res.ok) {
    showError(payload.error || `dashboard request failed (${res.status})`);
    return;
  }
  dashboard = payload;
  setGeneratedAt();
  renderSummaryCards();
  renderTrackCards();
  renderCharts();
  renderRepoTable();
  renderIssues(dashboard.search_pool.slice(0, 40), '');
}

let searchTimer = null;

function bindEvents() {
  document.getElementById('refreshBtn').addEventListener('click', async () => {
    document.getElementById('refreshBtn').disabled = true;
    try {
      await fetch('/api/refresh', { method: 'POST' });
      await loadDashboard(true);
    } finally {
      document.getElementById('refreshBtn').disabled = false;
    }
  });

  document.getElementById('searchInput').addEventListener('input', (e) => {
    const q = e.target.value.trim();
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => {
      const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
      const data = await res.json();
      if (!res.ok) {
        renderIssues([], q);
        return;
      }
      renderIssues(data.results || [], q);
    }, 260);
  });

  document.getElementById('addRepoBtn').addEventListener('click', async () => {
    const btn = document.getElementById('addRepoBtn');
    const path = document.getElementById('repoPathInput').value.trim();
    const track = document.getElementById('repoTrackSelect').value;
    if (!path) {
      showError('repo path is required');
      return;
    }
    btn.disabled = true;
    try {
      await addRepo(path, track);
      document.getElementById('repoPathInput').value = '';
      await loadConfig();
      await loadDashboard(true);
    } catch (e) {
      showError(e.message || 'failed to add repo');
    } finally {
      btn.disabled = false;
    }
  });
}

(async function bootstrap() {
  try {
    bindEvents();
    await loadConfig();
    await loadDashboard(false);
  } catch (e) {
    showError(e.message || 'bootstrap failed');
  }
})();
