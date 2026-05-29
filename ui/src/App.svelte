<script>
  import { onMount, afterUpdate } from 'svelte';

  let state = {
    running: false,
    zone: 'Unknown',
    timer: '00:00:00',
    logs: [],
    totals: [],
    show_ocr: false,
    sessions: ['No sessions'],
    selected_session: 'No sessions',
  };

  let sidebarOpen = false;
  let sidebarPanel = 'changelog';
  let changelog = 'Loading…';
  let dbStats = null;
  let dbLoading = false;
  let ocrTick = 0;
  let confirmDeleteId = null;
  let confirmWipeDb = false;
  let sessionDetail = null;
  let sessionDetailLoading = false;

  // Chart constants (SVG inner area)
  const CW = 460, CH = 150;

  const CHART_COLORS = [
    '#d4a017', '#50c878', '#4a9eff', '#e05050', '#c870e0',
    '#50c8c8', '#e09050', '#a0c850', '#e05090', '#8090e0',
  ];

  let chartMode = 'silver'; // 'silver' | 'items'

  $: timelineChart = buildTimelineChart(sessionDetail?.timeline ?? []);
  $: itemsChart = buildItemsChart(sessionDetail?.timeline ?? []);
  $: maxItemValue = Math.max(...(sessionDetail?.items ?? []).map(i => i.value), 1);

  function buildTimelineChart(timeline) {
    if (!timeline.length) return null;
    const maxT = Math.max(...timeline.map(e => e.elapsed_seconds), 1);
    const totalV = timeline.reduce((s, e) => s + e.value, 0);
    if (totalV === 0) return null;

    let cum = 0;
    const pts = [];
    for (const e of timeline) {
      cum += e.value;
      pts.push([
        (e.elapsed_seconds / maxT) * CW,
        CH - (cum / totalV) * CH,
      ]);
    }

    const polyline = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
    const area = `0,${CH} ${polyline} ${CW},${CH}`;

    const yLabels = [0, 0.5, 1].map(f => ({
      y: CH - f * CH,
      text: fmtSilver(totalV * f),
    }));
    const xLabels = [0, 0.25, 0.5, 0.75, 1].map(f => ({
      x: f * CW,
      text: fmtElapsed(maxT * f),
    }));

    return { polyline, area, yLabels, xLabels };
  }

  function buildItemsChart(timeline) {
    if (!timeline.length) return null;
    const maxT = Math.max(...timeline.map(e => e.elapsed_seconds), 1);

    // Group by item name
    const byItem = {};
    for (const e of timeline) {
      (byItem[e.item_name] ??= []).push(e);
    }

    // Sort by total qty desc, cap at top 10
    let items = Object.entries(byItem).map(([name, evts]) => ({
      name,
      events: evts.slice().sort((a, b) => a.elapsed_seconds - b.elapsed_seconds),
      total: evts.reduce((s, e) => s + e.quantity, 0),
    }));
    items.sort((a, b) => b.total - a.total);
    items = items.slice(0, 10);

    // Per-item normalisation: if total > 10 000, show per-1 000
    items = items.map(item => ({ ...item, scale: item.total > 10000 ? 1000 : 1 }));

    // Shared Y max across normalised values
    const maxY = Math.max(...items.map(i => i.total / i.scale), 1);

    // Build step-function polylines (discrete loot events)
    const series = items.map((item, idx) => {
      let cum = 0;
      let prevY = CH;
      const pts = [`0,${CH}`];
      for (const e of item.events) {
        const x = (e.elapsed_seconds / maxT) * CW;
        // horizontal segment at previous level, then jump up
        pts.push(`${x.toFixed(1)},${prevY.toFixed(1)}`);
        cum += e.quantity;
        const y = CH - (cum / item.scale / maxY) * CH;
        pts.push(`${x.toFixed(1)},${y.toFixed(1)}`);
        prevY = y;
      }
      pts.push(`${CW},${prevY.toFixed(1)}`); // extend to right edge
      return {
        name: item.name,
        points: pts.join(' '),
        total: item.total,
        scale: item.scale,
        color: CHART_COLORS[idx % CHART_COLORS.length],
      };
    });

    const yLabels = [0, 0.5, 1].map(f => ({
      y: CH - f * CH,
      text: Math.round(maxY * f).toLocaleString(),
    }));
    const xLabels = [0, 0.25, 0.5, 0.75, 1].map(f => ({
      x: f * CW,
      text: fmtElapsed(maxT * f),
    }));

    return { series, yLabels, xLabels };
  }

  function fmtElapsed(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}h${m}m`;
    if (m > 0) return `${m}m${s}s`;
    return `${s}s`;
  }

  async function openSessionDetail(id) {
    chartMode = 'silver';
    sessionDetailLoading = true;
    sessionDetail = null;
    try {
      const res = await fetch(`/api/session_detail?id=${id}`);
      sessionDetail = await res.json();
    } catch (_) {
      sessionDetail = { session: null, timeline: [], items: [] };
    } finally {
      sessionDetailLoading = false;
    }
  }

  function closeSessionDetail() {
    sessionDetail = null;
    sessionDetailLoading = false;
  }

  // Resizable panes
  let leftPct = 50;       // % width of left pane
  let ocrHeightPx = 220;  // px height of OCR pane
  let draggingH = false;
  let draggingV = false;
  let panesEl;

  function startDragH(e) { draggingH = true; e.preventDefault(); }
  function startDragV(e) { draggingV = true; e.preventDefault(); }

  function onMouseMove(e) {
    if (draggingH && panesEl) {
      const rect = panesEl.getBoundingClientRect();
      const clampedX = Math.max(200, Math.min(rect.width - 200, e.clientX - rect.left));
      leftPct = (clampedX / rect.width) * 100;
    }
    if (draggingV && panesEl) {
      const rect = panesEl.getBoundingClientRect();
      const fromBottom = rect.bottom - e.clientY;
      ocrHeightPx = Math.min(rect.height * 0.6, Math.max(80, fromBottom));
    }
  }

  function stopDrag() { draggingH = false; draggingV = false; }

  // ── Keybindings ────────────────────────────────────────────────────────────
  let rebinding = null;       // action name being rebound ('start'|'pause'|'stop')
  let rebindPrevious = null;  // value to restore on cancel

  const REBIND_LABELS = { start: 'Start', pause: 'Pause / Resume', stop: 'Stop' };

  function sanitizeCharacterName(raw) {
    return raw.replace(/<[^>]*>/g, '').replace(/[\r\n\t]/g, '').trim();
  }

  let nameFlash = null;
  let nameFlashTimer = null;

  async function saveCharacterName(v) {
    if (v) {
      await api('set_character_name', 'POST', { value: v });
      const saved = state.character_name === v;
      clearTimeout(nameFlashTimer);
      nameFlash = saved ? 'success' : 'error';
      nameFlashTimer = setTimeout(() => { nameFlash = null; }, 800);
    } else {
      clearTimeout(nameFlashTimer);
      nameFlash = 'error';
      nameFlashTimer = setTimeout(() => { nameFlash = null; }, 800);
    }
  }

  function fmtKeybind(b) {
    if (!b) return '—';
    return b.replace('Control', 'Ctrl');
  }

  function parseKeybind(b) {
    if (!b) return null;
    const parts = b.split('+');
    return {
      ctrl:  parts.includes('Control'),
      shift: parts.includes('Shift'),
      alt:   parts.includes('Alt'),
      key:   parts[parts.length - 1].toUpperCase(),
    };
  }

  function startRebind(action) {
    rebindPrevious = state[`keybind_${action}`] ?? null;
    rebinding = action;
  }

  function cancelRebind() {
    rebinding = null;
    rebindPrevious = null;
  }

  function onGlobalKeydown(e) {
    if (rebinding) {
      e.preventDefault();
      if (e.key === 'Escape') {
        cancelRebind();
        return;
      }
      const mods = ['Control', 'Shift', 'Alt', 'Meta'];
      if (!mods.includes(e.key)) {
        const parts = [];
        if (e.ctrlKey)  parts.push('Control');
        if (e.shiftKey) parts.push('Shift');
        if (e.altKey)   parts.push('Alt');
        parts.push(e.key.length === 1 ? e.key.toUpperCase() : e.key);
        api('set_keybind', 'POST', { action: rebinding, key: parts.join('+') });
        rebinding = null;
        rebindPrevious = null;
      }
      return;
    }
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    const match = (binding, defaultB) => {
      const b = parseKeybind(binding ?? defaultB);
      return b && e.ctrlKey === b.ctrl && e.shiftKey === b.shift &&
             e.altKey === b.alt && e.key.toUpperCase() === b.key;
    };
    if (match(state.keybind_start, 'Control+Shift+A')) { e.preventDefault(); api('start'); }
    else if (match(state.keybind_pause, 'Control+Shift+S')) {
      e.preventDefault();
      api(state.paused ? 'resume' : 'pause');
    }
    else if (match(state.keybind_stop, 'Control+Shift+D')) { e.preventDefault(); api('stop'); }
  }

  function fmtSilver(v) {
    if (v == null || isNaN(v)) return '0';
    if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B';
    if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K';
    return Math.round(v).toLocaleString();
  }

  function fmtDate(s) {
    if (!s) return '—';
    return s.slice(0, 10);
  }

  async function api(path, method = 'POST', payload = undefined) {
    await fetch(`/api/${path}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: payload ? JSON.stringify(payload) : undefined,
    });
    await refresh();
  }

  async function refresh() {
    const res = await fetch('/api/state');
    state = await res.json();
    ocrTick++;
  }

  async function openSidebar(panel = 'changelog') {
    sidebarPanel = panel;
    sidebarOpen = true;
    if (panel === 'changelog' && changelog === 'Loading…') {
      const res = await fetch('/api/changelog');
      const data = await res.json();
      changelog = data.text || '(no changelog found)';
    }
    if (panel === 'database') {
      dbLoading = true;
      dbStats = null;
      try {
        const res = await fetch('/api/db_stats');
        dbStats = await res.json();
      } catch (_) {
        dbStats = { summary: {}, sessions: [], top_items: [] };
      } finally {
        dbLoading = false;
      }
    }
  }

  function closeSidebar() {
    sidebarOpen = false;
  }

  async function reloadDbStats() {
    dbLoading = true;
    dbStats = null;
    try {
      const res = await fetch('/api/db_stats');
      dbStats = await res.json();
    } catch (_) {
      dbStats = { summary: {}, sessions: [], top_items: [] };
    } finally {
      dbLoading = false;
    }
  }

  async function confirmDelete() {
    if (confirmDeleteId == null) return;
    await fetch('/api/delete_session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: confirmDeleteId }),
    });
    confirmDeleteId = null;
    await reloadDbStats();
  }

  async function confirmWipe() {
    await api('wipe_database');
    confirmWipeDb = false;
    dbStats = null;
    await reloadDbStats();
  }

  function handleOverlayKey(e) {
    if (e.key === 'Escape') closeSidebar();
  }

  let dismissedCalibration = false;

  let liveLogEl;
  let liveLogAtBottom = true;
  let modalEl;
  let wipeModalEl;
  let calibModalEl;

  function onLiveLogScroll() {
    if (!liveLogEl) return;
    liveLogAtBottom = liveLogEl.scrollHeight - liveLogEl.scrollTop - liveLogEl.clientHeight < 40;
  }

  afterUpdate(() => {
    if (liveLogEl && liveLogAtBottom) {
      liveLogEl.scrollTop = liveLogEl.scrollHeight;
    }
    if (confirmDeleteId != null && modalEl) {
      modalEl.focus();
    }
    if (confirmWipeDb && wipeModalEl) {
      wipeModalEl.focus();
    }
    if (state.needs_calibration && !dismissedCalibration && calibModalEl) {
      calibModalEl.focus();
    }
  });

  onMount(async () => {
    await refresh();
    document.getElementById('loading-overlay')?.remove();
    const interval = setInterval(refresh, 1000);
    return () => clearInterval(interval);
  });
</script>

<svelte:window on:keydown={onGlobalKeydown} />

<div class="ui-root">

  <!-- Session detail overlay -->
  {#if sessionDetailLoading || sessionDetail !== null}
    <div class="detail-overlay">
      <div class="detail-header">
        <button class="icon-btn detail-back-btn" on:click={closeSessionDetail}>← Back</button>
        {#if sessionDetail?.session}
          <span class="detail-title">Session #{sessionDetail.session.id} · {sessionDetail.session.zone}</span>
        {:else if sessionDetailLoading}
          <span class="detail-title">Loading…</span>
        {/if}
      </div>

      {#if sessionDetailLoading}
        <div class="detail-loading">Loading…</div>
      {:else if sessionDetail?.session}
        <div class="detail-body">

          <!-- Stats row -->
          <div class="detail-stats">
            <div class="detail-stat">
              <div class="detail-stat-label">Started</div>
              <div class="detail-stat-value">{sessionDetail.session.started_at?.slice(0, 16) ?? '—'}</div>
            </div>
            <div class="detail-stat">
              <div class="detail-stat-label">Duration</div>
              <div class="detail-stat-value mono">{sessionDetail.session.duration}</div>
            </div>
            <div class="detail-stat">
              <div class="detail-stat-label">Avg / hr</div>
              <div class="detail-stat-value gold mono">{fmtSilver(sessionDetail.session.avg_hour)}</div>
            </div>
            <div class="detail-stat">
              <div class="detail-stat-label">Total Silver</div>
              <div class="detail-stat-value gold mono">
                {fmtSilver(sessionDetail.items.reduce((s, i) => s + i.value, 0))}
              </div>
            </div>
          </div>

          <!-- Chart section -->
          {#if timelineChart}
            <div class="detail-chart-header">
              <div class="detail-section-label" style="margin: 0;">
                {chartMode === 'silver' ? 'Silver Earned Over Time' : 'Items Obtained Over Time'}
              </div>
              <div class="chart-toggle">
                <button
                  class="chart-toggle-btn"
                  class:chart-toggle-active={chartMode === 'silver'}
                  on:click={() => chartMode = 'silver'}
                >Silver</button>
                <button
                  class="chart-toggle-btn"
                  class:chart-toggle-active={chartMode === 'items'}
                  on:click={() => chartMode = 'items'}
                >Items</button>
              </div>
            </div>

            <div class="detail-chart-wrap">
              {#if chartMode === 'silver'}
                <svg class="detail-chart-svg" viewBox="0 0 {CW + 80} {CH + 50}">
                  {#each timelineChart.yLabels as lbl}
                    <line x1="60" y1={lbl.y + 10} x2={CW + 60} y2={lbl.y + 10} class="chart-grid" />
                    <text x="56" y={lbl.y + 14} text-anchor="end" class="chart-label">{lbl.text}</text>
                  {/each}
                  <g transform="translate(60, 10)">
                    <polygon points={timelineChart.area} class="chart-area" />
                    <polyline points={timelineChart.polyline} class="chart-line" />
                    <line x1="0" y1={CH} x2={CW} y2={CH} class="chart-axis" />
                    <line x1="0" y1="0" x2="0" y2={CH} class="chart-axis" />
                  </g>
                  {#each timelineChart.xLabels as lbl}
                    <text x={lbl.x + 60} y={CH + 30} text-anchor="middle" class="chart-label">{lbl.text}</text>
                  {/each}
                </svg>

              {:else if itemsChart}
                <svg class="detail-chart-svg" viewBox="0 0 {CW + 80} {CH + 50}">
                  {#each itemsChart.yLabels as lbl}
                    <line x1="60" y1={lbl.y + 10} x2={CW + 60} y2={lbl.y + 10} class="chart-grid" />
                    <text x="56" y={lbl.y + 14} text-anchor="end" class="chart-label">{lbl.text}</text>
                  {/each}
                  <g transform="translate(60, 10)">
                    {#each itemsChart.series as s}
                      <polyline
                        points={s.points}
                        fill="none"
                        stroke={s.color}
                        stroke-width="1.5"
                        stroke-linejoin="round"
                        stroke-linecap="round"
                      />
                    {/each}
                    <line x1="0" y1={CH} x2={CW} y2={CH} class="chart-axis" />
                    <line x1="0" y1="0" x2="0" y2={CH} class="chart-axis" />
                  </g>
                  {#each itemsChart.xLabels as lbl}
                    <text x={lbl.x + 60} y={CH + 30} text-anchor="middle" class="chart-label">{lbl.text}</text>
                  {/each}
                </svg>

                <!-- Legend -->
                <div class="chart-legend">
                  {#each itemsChart.series as s}
                    <div class="chart-legend-item">
                      <span class="chart-legend-dot" style="background:{s.color}"></span>
                      <span class="chart-legend-name" title={s.name}>{s.name}</span>
                      {#if s.scale === 1000}
                        <span class="chart-legend-unit">per 1K</span>
                      {/if}
                      <span class="chart-legend-total">×{s.total.toLocaleString()}</span>
                    </div>
                  {/each}
                </div>
              {/if}
            </div>
          {:else}
            <div class="detail-no-timeline">No time-series data was recorded.</div>
          {/if}

          <!-- Items breakdown -->
          <div class="detail-section-label" style="margin-top: 24px;">Items Collected</div>
          <div class="detail-items">
            {#each sessionDetail.items as item}
              <div class="detail-item-row">
                <span class="detail-item-name" title={item.item_name}>{item.item_name}</span>
                <div class="detail-item-bar-wrap">
                  <div class="detail-item-bar" style="width: {(item.value / maxItemValue * 100).toFixed(1)}%"></div>
                </div>
                <span class="detail-item-qty">×{item.quantity.toLocaleString()}</span>
                <span class="detail-item-silver">{fmtSilver(item.value)}</span>
              </div>
            {/each}
            {#if sessionDetail.items.length === 0}
              <div class="db-empty">No items recorded for this session.</div>
            {/if}
          </div>

        </div>
      {:else}
        <div class="detail-loading">Session not found.</div>
      {/if}
    </div>
  {/if}

  <!-- Keybind capture popup -->
  {#if rebinding}
    <div class="rebind-overlay" role="dialog" aria-modal="true">
      <div class="rebind-modal">
        <div class="rebind-title">Rebind — {REBIND_LABELS[rebinding]}</div>
        <div class="rebind-current">Current: <span class="rebind-current-key">{fmtKeybind(rebindPrevious)}</span></div>
        <div class="rebind-prompt">Press a key combination…</div>
        <button class="modal-btn-cancel" on:click={cancelRebind}>Cancel</button>
      </div>
    </div>
  {/if}

  <!-- Delete confirmation modal -->
  {#if confirmDeleteId != null}
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <div class="modal-overlay" on:click={() => confirmDeleteId = null} on:keydown={(e) => e.key === 'Escape' && (confirmDeleteId = null)}>
      <div
        class="modal"
        role="dialog"
        aria-modal="true"
        tabindex="-1"
        bind:this={modalEl}
        on:click|stopPropagation
        on:keydown|stopPropagation={(e) => { if (e.key === 'Enter') confirmDelete(); else if (e.key === 'Escape') confirmDeleteId = null; }}
      >
        <div class="modal-title">Delete Session #{confirmDeleteId}?</div>
        <div class="modal-body">This will permanently remove the session and all its loot data from the local database.</div>
        <div class="modal-actions">
          <button class="modal-btn-cancel" on:click={() => confirmDeleteId = null}>Cancel</button>
          <button class="modal-btn-delete" on:click={confirmDelete}>Delete</button>
        </div>
      </div>
    </div>
  {/if}

  <!-- Wipe database confirmation modal -->
  {#if confirmWipeDb}
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <div class="modal-overlay" on:click={() => confirmWipeDb = false} on:keydown={(e) => e.key === 'Escape' && (confirmWipeDb = false)}>
      <div
        class="modal"
        role="dialog"
        aria-modal="true"
        tabindex="-1"
        bind:this={wipeModalEl}
        on:click|stopPropagation
        on:keydown|stopPropagation={(e) => { if (e.key === 'Enter') confirmWipe(); else if (e.key === 'Escape') confirmWipeDb = false; }}
      >
        <div class="modal-title">Wipe Entire Database?</div>
        <div class="modal-body">This will permanently delete all sessions and loot data. This cannot be undone.</div>
        <div class="modal-actions">
          <button class="modal-btn-cancel" on:click={() => confirmWipeDb = false}>Cancel</button>
          <button class="modal-btn-delete" on:click={confirmWipe}>Wipe</button>
        </div>
      </div>
    </div>
  {/if}

  <!-- Calibration required modal -->
  {#if state.needs_calibration && !dismissedCalibration}
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <div class="modal-overlay">
      <div
        class="modal"
        role="dialog"
        aria-modal="true"
        tabindex="-1"
        bind:this={calibModalEl}
      >
        <div class="modal-title">Calibration Required</div>
        <div class="modal-body">Your capture region hasn't been set up yet. Run calibration to tell the tracker where the loot log appears on your screen. For in-depth instructions, <a class="modal-link" href="https://github.com/janhnguyen/BDO-Loot-Tracker/tree/dev#calibration" target="_blank" rel="noreferrer">visit the setup guide</a>. If you need additional help, join the <a class="modal-link" href="https://discord.gg/uZYJfGphBP" target="_blank" rel="noreferrer">Discord server</a>.</div>
        <div class="modal-actions">
          <button class="modal-btn-cancel" on:click={() => dismissedCalibration = true}>Dismiss</button>
          <button class="modal-btn-confirm" on:click={() => { dismissedCalibration = true; api('calibrate'); }}>Calibrate Now</button>
        </div>
      </div>
    </div>
  {/if}

  <!-- Sidebar overlay -->
  {#if sidebarOpen}
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <div
      class="sidebar-overlay"
      on:click={closeSidebar}
      on:keydown={handleOverlayKey}
    ></div>
  {/if}

  <!-- Sidebar -->
  <aside class="sidebar" class:open={sidebarOpen}>
    <div class="sidebar-header">
      <span class="sidebar-title">Menu</span>
      <button class="icon-btn" on:click={closeSidebar} title="Close">✕</button>
    </div>

    <nav class="sidebar-nav">
      <button
        class="nav-btn"
        class:active={sidebarPanel === 'changelog'}
        on:click={() => openSidebar('changelog')}
      >
        Changelog
      </button>
      <button
        class="nav-btn"
        class:active={sidebarPanel === 'database'}
        on:click={() => openSidebar('database')}
      >
        Sessions
      </button>
      <button
        class="nav-btn"
        class:active={sidebarPanel === 'settings'}
        on:click={() => openSidebar('settings')}
      >
        Settings
      </button>
    </nav>

    <div class="sidebar-content">
      {#if sidebarPanel === 'changelog'}
        <pre class="changelog-text">{changelog}</pre>

      {:else if sidebarPanel === 'database'}
        {#if dbLoading}
          <div class="db-loading">Loading stats…</div>
        {:else if dbStats}
          <!-- Overview cards -->
          <div class="db-section-label">Overview</div>
          <div class="db-cards">
            <div class="db-card">
              <div class="db-card-value">{dbStats.summary.total_sessions ?? 0}</div>
              <div class="db-card-label">Sessions</div>
            </div>
            <div class="db-card">
              <div class="db-card-value">{(dbStats.summary.total_items ?? 0).toLocaleString()}</div>
              <div class="db-card-label">Items Looted</div>
            </div>
            <div class="db-card db-card-wide">
              <div class="db-card-value gold">{fmtSilver(dbStats.summary.total_silver)}</div>
              <div class="db-card-label">Total Silver</div>
            </div>
            <!-- svelte-ignore a11y-no-static-element-interactions -->
            <div
              class="db-card db-card-wide"
              class:db-card-clickable={dbStats.summary.best_session_id != null}
              on:click={() => dbStats.summary.best_session_id != null && openSessionDetail(dbStats.summary.best_session_id)}
              on:keydown={(e) => e.key === 'Enter' && dbStats.summary.best_session_id != null && openSessionDetail(dbStats.summary.best_session_id)}
            >
              <div class="db-card-value">{fmtSilver(dbStats.summary.best_avg_hour)}<span class="db-card-unit">/hr</span></div>
              <div class="db-card-label">Best Rate · {dbStats.summary.best_zone ?? '—'}</div>
            </div>
          </div>

          <!-- Session History -->
          <div class="db-section-label">Session History</div>
          <div class="db-sessions">
            {#each dbStats.sessions as s}
              <div
                class="db-session db-session-clickable"
                role="button"
                tabindex="0"
                on:click={() => openSessionDetail(s.id)}
                on:keydown={(e) => { if (e.key === 'Enter') openSessionDetail(s.id); else if (e.key === 'Escape') closeSessionDetail(); }}
              >
                <div class="db-session-head">
                  <span class="db-session-id">#{s.id}</span>
                  <span class="db-session-zone">{s.zone}</span>
                  <span class="db-badge" class:db-badge-live={!s.ended_at}>{s.ended_at ? 'done' : 'live'}</span>
                  <button class="db-delete-btn" on:click|stopPropagation={() => confirmDeleteId = s.id} title="Delete session">✕</button>
                </div>
                <div class="db-session-stats">
                  <span class="db-stat">
                    <span class="db-stat-label">Duration</span>
                    <span class="db-stat-value">{s.duration}</span>
                  </span>
                  <span class="db-stat">
                    <span class="db-stat-label">Silver</span>
                    <span class="db-stat-value gold">{fmtSilver(s.total_silver)}</span>
                  </span>
                  <span class="db-stat">
                    <span class="db-stat-label">Avg/hr</span>
                    <span class="db-stat-value">{fmtSilver(s.avg_hour)}</span>
                  </span>
                </div>
                <div class="db-session-footer">{s.item_count} item types · {fmtDate(s.started_at)}</div>
              </div>
            {/each}
            {#if dbStats.sessions.length === 0}
              <div class="db-empty">No sessions recorded yet.</div>
            {/if}
          </div>

          <!-- Top Items -->
          <div class="db-section-label">Top Items (All-Time)</div>
          <div class="db-top-items">
            {#each dbStats.top_items as item, i}
              <div class="db-item-row">
                <span class="db-item-rank">#{i + 1}</span>
                <span class="db-item-name">{item.item_name}</span>
                <span class="db-item-qty">×{item.total_qty.toLocaleString()}</span>
              </div>
            {/each}
            {#if dbStats.top_items.length === 0}
              <div class="db-empty">No items tracked yet.</div>
            {/if}
          </div>
        {/if}

      {:else if sidebarPanel === 'settings'}

        <div class="settings-group">
          <h3>Personalization</h3>
          <label class="settings-label" for="character-name-input">Character Name</label>
          <input
            id="character-name-input"
            class="settings-text-input"
            class:name-flash-success={nameFlash === 'success'}
            class:name-flash-error={nameFlash === 'error'}
            type="text"
            placeholder="Enter character name"
            value={state.character_name ?? ''}
            on:keydown={(e) => {
              if (e.key === 'Enter') {
                const v = sanitizeCharacterName(e.currentTarget.value);
                saveCharacterName(v);
                e.currentTarget.blur();
              } else if (e.key === 'Escape') {
                e.currentTarget.value = state.character_name ?? '';
                e.currentTarget.blur();
              }
            }}
            on:change={(e) => {
              const v = sanitizeCharacterName(e.currentTarget.value);
              saveCharacterName(v);
            }}
          />
        </div>

        <div class="settings-group">
          <h3>Calibration</h3>
          <button class="settings-btn" on:click={() => api('calibrate')}>Calibrate</button>
        </div>

        <div class="settings-group">
          <h3>Items</h3>
          <button
            class="settings-btn"
            disabled={state.market_updating}
            on:click={() => api('update_market_prices')}
          >{state.market_updating ? 'Fetching…' : 'Update'}</button>
          <p class="settings-hint">Fetch market prices from Arsha.io.</p>
        </div>

        <div class="settings-group">
          <h3>Tracking</h3>
          <div class="slider-row">
            <span class="slider-label">Items Tracked</span>
            <span class="slider-value">{state.tracking_window_size ?? 20}</span>
          </div>
          <input
            class="slider"
            type="range"
            min="15"
            max="30"
            value={state.tracking_window_size ?? 20}
            on:change={(e) => api('set_tracking_window', 'POST', { value: Number(e.currentTarget.value) })}
          />
          <div class="slider-bounds">
            <span>15</span><span>30</span>
          </div>
        </div>

        <div class="settings-group">
          <h3>Display</h3>
          <div class="slider-row">
            <span class="slider-label">Font Size</span>
            <span class="slider-value">{state.items_font_size ?? 12}px</span>
          </div>
          <input
            class="slider"
            type="range"
            min="12"
            max="20"
            value={state.items_font_size ?? 12}
            on:change={(e) => api('set_font_size', 'POST', { value: Number(e.currentTarget.value) })}
          />
          <div class="slider-bounds">
            <span>12px</span><span>20px</span>
          </div>
        </div>

        <div class="settings-group">
          <h3>OCR</h3>
          <label class="toggle-row">
            <input
              type="checkbox"
              checked={state.show_live_log ?? false}
              on:change={(e) => api('toggle_live_log', 'POST', { value: e.currentTarget.checked })}
            />
            <span>Show Live Log</span>
          </label>
          <label class="toggle-row">
            <input
              type="checkbox"
              checked={state.show_ocr}
              on:change={(e) => api('toggle_ocr', 'POST', { value: e.currentTarget.checked })}
            />
            <span>Mix OCR into Live Log</span>
          </label>
          <label class="toggle-row">
            <input
              type="checkbox"
              checked={state.show_ocr_pane}
              on:change={(e) => api('toggle_ocr_pane', 'POST', { value: e.currentTarget.checked })}
            />
            <span>Show Live OCR image</span>
          </label>
        </div>

        <div class="settings-group">
          <h3>Keybindings</h3>
          {#each [['start', 'Start'], ['pause', 'Pause / Resume'], ['stop', 'Stop']] as [action, label]}
            <div class="keybind-row">
              <span class="keybind-label">{label}</span>
              <button class="keybind-btn" on:click={() => startRebind(action)}
              >{fmtKeybind(state[`keybind_${action}`])}</button>
            </div>
          {/each}
        </div>

        <div class="settings-group">
          <h3>Files</h3>
          <button class="settings-btn" on:click={() => api('open_log_dir')}>Error Logs</button>
          <button class="settings-btn settings-btn-danger" on:click={() => confirmWipeDb = true}>Wipe Database</button>
        </div>

        <div class="settings-group">
          <h3>Version - {state.current_version ?? '—'}</h3>
          {#if state.update_available}
            <div class="update-header">
              <p class="settings-hint update-available" style="margin: 0;">v{state.latest_version} is available.</p>
              {#if !state.update_downloading}
                <button class="update-dismiss-btn" title="Dismiss" on:click={() => api('cancel_update')}>✕</button>
              {/if}
            </div>
            {#if state.update_downloading}
              <button class="settings-btn update-btn" disabled>
                Downloading… {state.update_download_progress}%
              </button>
              <button class="settings-btn" disabled={state.update_download_progress >= 100} on:click={() => api('cancel_update')}>Cancel</button>
            {:else}
              <button class="settings-btn update-btn" on:click={() => api('install_update')}>
                Install Update
              </button>
            {/if}
          {/if}
          {#if !state.update_available}
            <button
              class="settings-btn"
              disabled={state.update_checking}
              on:click={() => api('check_for_updates')}
            >{state.update_checking ? 'Checking for Updates…' : 'Check for Updates'}</button>
          {/if}
          <button class="settings-btn" on:click={() => api('open_source_code')}>Source Code</button>
        </div>

      {/if}
    </div>
  </aside>

  <main>
    <header>
      <div class="status {state.running ? (state.paused ? 'paused' : 'running') : 'stopped'}">
        ● {state.running ? (state.paused ? 'PAUSED' : 'TRACKING') : 'STOPPED'}
      </div>
      <div class="header-right">
        <button class="icon-btn menu-btn" on:click={() => openSidebar('changelog')} title="Menu">☰</button>
        <div class="meta">Zone: {state.zone} · Time: {state.timer}</div>
      </div>
    </header>

    <section class="controls">
      <button class="start" on:click={() => api('start')}>▶ Start</button>
      {#if state.running}
        {#if state.paused}
          <button class="pause" on:click={() => api('resume')}>▶ Resume</button>
        {:else}
          <button class="pause" on:click={() => api('pause')}>⏸ Pause</button>
        {/if}
      {/if}
      <button class="stop" on:click={() => api('stop')}>■ Stop</button>
    </section>

    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <section
      class="panes"
      bind:this={panesEl}
      on:mousemove={onMouseMove}
      on:mouseup={stopDrag}
      on:mouseleave={stopDrag}
    >
      <div class="panes-top" style="flex: 1; min-height: 0; display: flex;">
        {#if state.show_live_log}
          <article style="width: {leftPct}%;">
            <h2>LIVE LOG</h2>
            <pre
              bind:this={liveLogEl}
              on:scroll={onLiveLogScroll}
              style="font-size: {state.items_font_size ?? 12}px"
            >{(state.show_ocr ? state.logs : state.logs.filter(l => !l.includes('[OCR]'))).join('\n')}</pre>
          </article>

          <!-- svelte-ignore a11y-no-static-element-interactions -->
          <div class="drag-handle-h" on:mousedown={startDragH}></div>
        {/if}

        <article style="flex: 1;">
          <h2>SESSION TOTALS <span class="session-silver">{fmtSilver(state.session_silver ?? 0)}</span></h2>
          <pre style="font-size: {state.items_font_size ?? 12}px">{state.totals.map((t) => `${t.name} ×${t.qty}`).join('\n')}</pre>
        </article>
      </div>

      {#if state.show_ocr_pane}
        <!-- svelte-ignore a11y-no-static-element-interactions -->
        <div class="drag-handle-v" on:mousedown={startDragV}></div>

        <article class="ocr-pane" style="height: {ocrHeightPx}px;">
          <h2>LIVE OCR <span class="ocr-badge">debug</span></h2>
          <div class="ocr-frames">
            <img class="ocr-frame-img" src="/api/ocr_frame?type=processed&t={ocrTick}" alt="ocr capture" />
          </div>
        </article>
      {/if}
    </section>
  </main>

</div>
