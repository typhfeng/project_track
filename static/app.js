const colors = {
  finance: '#0f7b7b',
  engineering: '#dc6b1f',
  soc_auto_design: '#356ad9',
  family: '#5f7f2a'
};

let dashboard = null;
let configData = null;
let charts = {};
let selectedTrack = 'finance';
let selectedRepoId = null;
let groupData = null;
let repoDetail = null;

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
  const group = document.getElementById('groupRepoList');
  const repoMeta = document.getElementById('selectedRepoMeta');

  const msg = `<article class="card"><div class="label">Error</div><div>${esc(message)}</div></article>`;
  summary.innerHTML = msg;
  tracks.innerHTML = '';
  table.innerHTML = '';
  issueList.innerHTML = `<div class="muted">${esc(message)}</div>`;
  group.innerHTML = '';
  repoMeta.textContent = `Selected repo: error`;
  meta.textContent = '0 results';
}

function number(value) {
  return new Intl.NumberFormat('en-US').format(value || 0);
}

function trackLabel(track) {
  if (!dashboard) return track;
  return dashboard.trend.labels_map[track] || track;
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
    .map(([label, value]) => `<article class="card"><div class="label">${label}</div><div class="value">${number(value)}</div></article>`)
    .join('');
}

function renderTrackCards() {
  if (!dashboard) return;
  const wrap = document.getElementById('trackCards');
  const entries = Object.entries(dashboard.track_summary);
  wrap.innerHTML = entries
    .map(([track, s]) => {
      const active = selectedTrack === track ? 'active' : '';
      return `
        <article class="card track ${active}" data-track="${track}" style="border-left-color:${colors[track] || '#0f7b7b'}">
          <div class="label">${s.label}</div>
          <div class="value">${s.avg_progress}</div>
          <div class="muted">avg progress</div>
          <div class="muted">repos: ${s.repos} | active: ${s.active_repos}</div>
          <div class="muted">30d commits: ${s.commits_30d} | issue hits: ${s.issues}</div>
        </article>
      `;
    })
    .join('');

  wrap.querySelectorAll('[data-track]').forEach((el) => {
    el.addEventListener('click', async () => {
      const track = el.getAttribute('data-track');
      await selectTrack(track);
    });
  });
}

function mountChart(id, config) {
  if (charts[id]) charts[id].destroy();
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
      datasets: [{ label: 'Commits (30d)', data: throughputValues, backgroundColor: throughputLabels.map((t) => colors[t] || '#0f7b7b') }]
    },
    options: { responsive: true, plugins: { legend: { display: false } } }
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
    options: { responsive: true, interaction: { mode: 'index', intersect: false }, stacked: false }
  });

  mountChart('allocationChart', {
    type: 'doughnut',
    data: {
      labels: throughputLabels.map((t) => trackLabel(t)),
      datasets: [{ data: throughputValues, backgroundColor: throughputLabels.map((t) => colors[t] || '#0f7b7b') }]
    },
    options: { plugins: { legend: { position: 'bottom' } } }
  });

  const topRepos = [...dashboard.repos].sort((a, b) => b.progress.score - a.progress.score).slice(0, 12);
  mountChart('progressChart', {
    type: 'bar',
    data: {
      labels: topRepos.map((r) => r.display_name || r.name),
      datasets: [{ label: 'Progress Score', data: topRepos.map((r) => r.progress.score), backgroundColor: topRepos.map((r) => colors[r.track] || '#0f7b7b') }]
    },
    options: {
      indexAxis: 'y',
      plugins: { legend: { display: false } },
      scales: { x: { suggestedMin: 0, suggestedMax: 100 } }
    }
  });
}

function renderRepoTable() {
  if (!dashboard) return;
  const rows = dashboard.repos.map((r) => {
    const dirty = r.status.dirty.modified + r.status.dirty.untracked;
    const last = r.status.last_commit.date ? new Date(r.status.last_commit.date).toLocaleDateString() : '-';
    return `
      <tr>
        <td>
          <div><strong>${esc(r.display_name || r.name)}</strong></div>
          <div class="muted">${esc(r.path)}</div>
        </td>
        <td><span class="badge">${esc(trackLabel(r.track))}</span></td>
        <td><div>${esc(r.status.branch)}</div><div class="muted">${esc(r.status.status_line || '-')}</div></td>
        <td>${r.commits.last_30d}</td>
        <td>${dirty}</td>
        <td>${r.issues.total}</td>
        <td>
          <div class="progress-wrap">
            <div class="progress-bar"><span style="width:${r.progress.score}%"></span></div>
            <div class="progress-text">${r.progress.score} | <span class="badge">${esc(r.progress.stage)}</span></div>
          </div>
        </td>
        <td><div>${last}</div><div class="muted">${esc(r.status.last_commit.hash || '')}</div></td>
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
    .map((item) => `
      <article class="issue-item">
        <div class="issue-meta">${esc(trackLabel(item.track))} | ${esc(item.repo)} | ${esc(item.type)}</div>
        <div><strong>${esc(item.title)}</strong></div>
        <div>${esc(item.content)}</div>
      </article>
    `)
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
  const root = configData.repo_manifest?.search_root || '-';
  meta.textContent = `${include.length} repos in manifest | search_root: ${root}`;
  body.innerHTML = include
    .map((p) => `
      <tr>
        <td><code>${esc(p)}</code></td>
        <td>${esc(overrides[p] || 'auto')}</td>
        <td><button class="btn-secondary" data-remove-path="${esc(p)}">Remove</button></td>
      </tr>
    `)
    .join('');

  body.querySelectorAll('button[data-remove-path]').forEach((btn) => {
    btn.addEventListener('click', async () => removeRepo(btn.getAttribute('data-remove-path')));
  });
}

function renderGroupRepos() {
  const meta = document.getElementById('selectedGroupMeta');
  const wrap = document.getElementById('groupRepoList');
  if (!groupData) {
    meta.textContent = 'Selected group: -';
    wrap.innerHTML = '<div class="muted">No group selected.</div>';
    return;
  }

  meta.textContent = `Selected group: ${groupData.label} | repos=${groupData.summary.repos || 0} | commits30d=${groupData.summary.commits_30d || 0}`;
  if (!groupData.repos?.length) {
    wrap.innerHTML = '<div class="muted">No repos in this group.</div>';
    return;
  }

  wrap.innerHTML = groupData.repos
    .map((r) => {
      const active = selectedRepoId === r.id ? 'active' : '';
      return `
        <article class="issue-item repo-item ${active}" data-repo-id="${esc(r.id)}">
          <div class="issue-meta">${esc(r.display_name || r.name)} | progress ${r.progress.score} | 30d ${r.commits.last_30d}</div>
          <div>${esc(r.path)}</div>
        </article>
      `;
    })
    .join('');

  wrap.querySelectorAll('[data-repo-id]').forEach((el) => {
    el.addEventListener('click', async () => {
      await selectRepo(el.getAttribute('data-repo-id'));
    });
  });
}

function renderRepoDetail() {
  const meta = document.getElementById('selectedRepoMeta');
  const commits = document.getElementById('repoCommits');
  const issues = document.getElementById('repoIssues');
  const todos = document.getElementById('repoTodos');
  const files = document.getElementById('repoFiles');

  if (!repoDetail?.repo) {
    meta.textContent = 'Selected repo: -';
    commits.innerHTML = '<div class="muted">No repo selected.</div>';
    issues.innerHTML = '';
    todos.innerHTML = '';
    files.innerHTML = '';
    return;
  }

  const r = repoDetail.repo;
  meta.textContent = `Selected repo: ${r.display_name || r.name} | track=${trackLabel(r.track)} | branch=${r.status.branch}`;

  commits.innerHTML = (repoDetail.recent_commits || []).slice(0, 20).map((c) => `
    <article class="issue-item">
      <div class="issue-meta">${esc(c.date)} | ${esc(c.hash)} | ${esc(c.author)}</div>
      <div>${esc(c.subject)}</div>
    </article>
  `).join('') || '<div class="muted">No commits found.</div>';

  if (repoDetail.open_issues_error) {
    issues.innerHTML = `<div class="muted">Issue API: ${esc(repoDetail.open_issues_error)}</div>`;
  } else {
    issues.innerHTML = (repoDetail.open_issues || []).map((it) => `
      <article class="issue-item">
        <div class="issue-meta">#${it.number} | ${esc(it.state)}</div>
        <div><a href="${esc(it.url)}" target="_blank" rel="noreferrer">${esc(it.title)}</a></div>
      </article>
    `).join('') || '<div class="muted">No open issues.</div>';
  }

  todos.innerHTML = (repoDetail.todos || []).map((t) => `
    <article class="issue-item">
      <div class="issue-meta">index=${t.index} line=${t.line_no}</div>
      <div class="manual-row">
        <label><input type="checkbox" data-todo-toggle="${t.index}" ${t.done ? 'checked' : ''}/> done</label>
        <button class="btn-secondary" data-todo-edit="${t.index}">Edit</button>
      </div>
      <div>${esc(t.text)}</div>
    </article>
  `).join('') || '<div class="muted">No TODO.md entries.</div>';

  files.innerHTML = (repoDetail.last_commit_files || []).map((f) => `<article class="issue-item"><div>${esc(f)}</div></article>`).join('') || '<div class="muted">No changed files in last commit.</div>';

  todos.querySelectorAll('[data-todo-toggle]').forEach((el) => {
    el.addEventListener('change', async () => {
      const idx = Number(el.getAttribute('data-todo-toggle'));
      await updateTodo(idx, { done: el.checked });
    });
  });
  todos.querySelectorAll('[data-todo-edit]').forEach((el) => {
    el.addEventListener('click', async () => {
      const idx = Number(el.getAttribute('data-todo-edit'));
      const cur = (repoDetail.todos || []).find((x) => x.index === idx);
      const text = prompt('Edit TODO text', cur?.text || '');
      if (text === null) return;
      await updateTodo(idx, { text });
    });
  });
}

async function loadConfig() {
  const res = await fetch('/api/config');
  const payload = await res.json();
  if (!res.ok) throw new Error(payload.error || 'failed to load config');
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
  if (!res.ok || !payload.ok) throw new Error(payload.error || 'failed to add repo');
}

async function removeRepo(path) {
  const res = await fetch('/api/repos', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path })
  });
  const payload = await res.json();
  if (!res.ok || !payload.ok) throw new Error(payload.error || 'failed to remove repo');
  await loadConfig();
  await loadDashboard(true);
  await selectTrack(selectedTrack);
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

async function selectTrack(track) {
  selectedTrack = track;
  renderTrackCards();
  const res = await fetch(`/api/group/${encodeURIComponent(track)}`);
  const payload = await res.json();
  if (!res.ok || !payload.ok) {
    showError(payload.error || 'failed to load group');
    return;
  }
  groupData = payload;
  selectedRepoId = payload.repos?.[0]?.id || null;
  renderGroupRepos();
  if (selectedRepoId) {
    await selectRepo(selectedRepoId);
  } else {
    repoDetail = null;
    renderRepoDetail();
  }
}

async function selectRepo(repoId) {
  selectedRepoId = repoId;
  renderGroupRepos();
  const res = await fetch(`/api/repo/${encodeURIComponent(repoId)}`);
  const payload = await res.json();
  if (!res.ok || !payload.ok) {
    showError(payload.error || 'failed to load repo details');
    return;
  }
  repoDetail = payload;
  renderRepoDetail();
}

async function syncGroup() {
  if (!selectedTrack) return;
  const res = await fetch(`/api/group/${encodeURIComponent(selectedTrack)}/sync`, { method: 'POST' });
  const payload = await res.json();
  if (!res.ok || !payload.ok) throw new Error(payload.error || 'group sync failed');
  await loadDashboard(true);
  await selectTrack(selectedTrack);
}

async function syncRepo() {
  if (!selectedRepoId) return;
  const res = await fetch(`/api/repo/${encodeURIComponent(selectedRepoId)}/sync`, { method: 'POST' });
  const payload = await res.json();
  if (!res.ok || !payload.ok) throw new Error(payload.error || 'repo sync failed');
  repoDetail = payload;
  await loadDashboard(true);
  renderRepoDetail();
  renderGroupRepos();
}

async function commitRepo() {
  if (!selectedRepoId) return;
  const msg = document.getElementById('commitMsgInput').value.trim();
  if (!msg) throw new Error('commit message required');
  const res = await fetch(`/api/repo/${encodeURIComponent(selectedRepoId)}/commit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: msg, push: true })
  });
  const payload = await res.json();
  if (!res.ok || !payload.ok) throw new Error(payload.error || 'commit failed');
  repoDetail = payload;
  document.getElementById('commitMsgInput').value = '';
  await loadDashboard(true);
  renderRepoDetail();
  renderGroupRepos();
}

async function createIssue() {
  if (!selectedRepoId) return;
  const title = document.getElementById('issueTitleInput').value.trim();
  const body = document.getElementById('issueBodyInput').value.trim();
  if (!title) throw new Error('issue title required');
  const res = await fetch(`/api/repo/${encodeURIComponent(selectedRepoId)}/issue`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, body })
  });
  const payload = await res.json();
  if (!res.ok || !payload.ok) throw new Error(payload.error || 'create issue failed');
  repoDetail = payload;
  document.getElementById('issueTitleInput').value = '';
  document.getElementById('issueBodyInput').value = '';
  renderRepoDetail();
}

async function addTodo() {
  if (!selectedRepoId) return;
  const text = document.getElementById('todoInput').value.trim();
  if (!text) throw new Error('todo text required');
  const res = await fetch(`/api/repo/${encodeURIComponent(selectedRepoId)}/todo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, commit: true, push: true })
  });
  const payload = await res.json();
  if (!res.ok || !payload.ok) throw new Error(payload.error || 'add todo failed');
  repoDetail = payload;
  document.getElementById('todoInput').value = '';
  await loadDashboard(true);
  renderRepoDetail();
  renderGroupRepos();
}

async function updateTodo(index, patch) {
  if (!selectedRepoId) return;
  const res = await fetch(`/api/repo/${encodeURIComponent(selectedRepoId)}/todo`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ index, ...patch, commit: true, push: true })
  });
  const payload = await res.json();
  if (!res.ok || !payload.ok) throw new Error(payload.error || 'update todo failed');
  repoDetail = payload;
  await loadDashboard(true);
  renderRepoDetail();
  renderGroupRepos();
}

let searchTimer = null;

function bindEvents() {
  document.getElementById('refreshBtn').addEventListener('click', async () => {
    const btn = document.getElementById('refreshBtn');
    btn.disabled = true;
    try {
      await fetch('/api/refresh', { method: 'POST' });
      await loadDashboard(true);
      await selectTrack(selectedTrack);
    } finally {
      btn.disabled = false;
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
      await selectTrack(selectedTrack);
    } catch (e) {
      showError(e.message || 'failed to add repo');
    } finally {
      btn.disabled = false;
    }
  });

  document.getElementById('syncGroupBtn').addEventListener('click', async () => {
    try {
      await syncGroup();
    } catch (e) {
      showError(e.message || 'sync group failed');
    }
  });

  document.getElementById('syncRepoBtn').addEventListener('click', async () => {
    try {
      await syncRepo();
    } catch (e) {
      showError(e.message || 'sync repo failed');
    }
  });

  document.getElementById('commitRepoBtn').addEventListener('click', async () => {
    try {
      await commitRepo();
    } catch (e) {
      showError(e.message || 'commit failed');
    }
  });

  document.getElementById('createIssueBtn').addEventListener('click', async () => {
    try {
      await createIssue();
    } catch (e) {
      showError(e.message || 'create issue failed');
    }
  });

  document.getElementById('addTodoBtn').addEventListener('click', async () => {
    try {
      await addTodo();
    } catch (e) {
      showError(e.message || 'add todo failed');
    }
  });
}

(async function bootstrap() {
  try {
    bindEvents();
    await loadConfig();
    await loadDashboard(false);
    await selectTrack(selectedTrack);
  } catch (e) {
    showError(e.message || 'bootstrap failed');
  }
})();
