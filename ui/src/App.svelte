<script>
  import { onMount } from 'svelte';

  let state = {
    running: false,
    zone: 'Unknown',
    timer: '00:00:00',
    logs: [],
    totals: [],
    show_ocr: false,
    sessions: ['No sessions'],
    selected_session: 'No sessions',
    show_live_log: true,
    light_mode: false,
    family_name: "",
  };

  let sidebarOpen = false;
  let sidebarPanel = 'changelog';
  let changelog = 'Loading…';
  let dbStats = null;
  let dbLoading = false;
  let ocrTick = 0;

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
      leftPct = Math.min(80, Math.max(20, ((e.clientX - rect.left) / rect.width) * 100));
    }
    if (draggingV && panesEl) {
      const rect = panesEl.getBoundingClientRect();
      const fromBottom = rect.bottom - e.clientY;
      ocrHeightPx = Math.min(rect.height * 0.6, Math.max(80, fromBottom));
    }
  }

  function stopDrag() { draggingH = false; draggingV = false; }

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

  function handleOverlayKey(e) {
    if (e.key === 'Escape') closeSidebar();
  }

  onMount(() => {
    refresh();
    const interval = setInterval(refresh, 1000);
    return () => clearInterval(interval);
  });
</script>

<div class="ui-root">

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
        Database
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
            <div class="db-card db-card-wide">
              <div class="db-card-value">{fmtSilver(dbStats.summary.best_avg_hour)}<span class="db-card-unit">/hr</span></div>
              <div class="db-card-label">Best Rate · {dbStats.summary.best_zone ?? '—'}</div>
            </div>
          </div>

          <!-- Session History -->
          <div class="db-section-label">Session History</div>
          <div class="db-sessions">
            {#each dbStats.sessions as s}
              <div class="db-session">
                <div class="db-session-head">
                  <span class="db-session-id">#{s.id}</span>
                  <span class="db-session-zone">{s.zone}</span>
                  <span class="db-badge" class:db-badge-live={!s.ended_at}>{s.ended_at ? 'done' : 'live'}</span>
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
          <h3>Family Name</h3>
          <input
            class="name-box"
            type="text"
            value={state.family_name}
            placeholder="Enter Family Name"
            on:change={(e) => api('set_family_name', 'POST', { value: e.currentTarget.value })}
          />
        </div>

        <div class="settings-group">
          <h3>Calibration</h3>
          <button class="settings-btn" on:click={() => api('calibrate')}>Calibrate</button>
        </div>

        <div class="settings-group">
          <h3>Database</h3>
          <button class="settings-btn" on:click={() => api('')}>Clear Database</button>
          <button class="settings-btn" on:click={() => api('')}>Upload Sessions</button>
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
          <h3>Live Log</h3>
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
          <label class="toggle-row">
            <input
              type="checkbox"
              checked={state.show_live_log}
              on:change={(e) => api('toggle_live_log', 'POST', { value: e.currentTarget.checked })}
            >
            <span>Show Live Log</span>
          </label>
        </div>

        <div class="settings-group">
          <h3>Personalization</h3>
          <label class="toggle-row">
            <input
              type="checkbox"
              checked={state.light_mode}
              on:change={(e) => api('toggle_light_mode', 'POST', { value: e.currentTarget.checked })}
            >
            <span>Light Mode</span>
          </label>
        </div>

        <div class="settings-group">
          <button class="settings-btn" on:click={() => api('')}>Reset Settings</button>
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
          <article style="width: {leftPct}%; min-width: 0;">
            <h2>LIVE LOG</h2>
            <pre style="font-size: {state.items_font_size ?? 12}px">{(state.show_ocr ? state.logs : state.logs.filter(l => !l.includes('[OCR]'))).join('\n')}</pre>
          </article>

          <!-- svelte-ignore a11y-no-static-element-interactions -->
          <div class="drag-handle-h" on:mousedown={startDragH}></div>

        {/if}

        <article style="flex: 1; min-width: 0;">
          <h2>SESSION TOTALS</h2>
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
