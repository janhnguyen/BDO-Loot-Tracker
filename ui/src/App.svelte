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
  };

  let sidebarOpen = false;
  let sidebarPanel = 'changelog';
  let changelog = 'Loading…';


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
  }

  async function openSidebar(panel = 'changelog') {
    sidebarPanel = panel;
    sidebarOpen = true;
    if (panel === 'changelog' && changelog === 'Loading…') {
      const res = await fetch('/api/changelog');
      const data = await res.json();
      changelog = data.text || '(no changelog found)';
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
        class:active={sidebarPanel === 'settings'}
        on:click={() => openSidebar('settings')}
      >
        Settings
      </button>
    </nav>

    <div class="sidebar-content">
      {#if sidebarPanel === 'changelog'}
        <pre class="changelog-text">{changelog}</pre>
      {:else if sidebarPanel === 'settings'}

        <div class="settings-group">
          <h3>Calibration</h3>
          <button class="settings-btn" on:click={() => api('calibrate')}>Calibrate</button>
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
              checked={state.show_ocr}
              on:change={(e) => api('toggle_ocr', 'POST', { value: e.currentTarget.checked })}
            />
            <span>Show OCR log (Only used for debugging purposes)</span>
          </label>
        </div>

      {/if}
    </div>
  </aside>

  <main>
    <header>
      <div class="status {state.running ? 'running' : 'stopped'}">
        ● {state.running ? 'TRACKING' : 'STOPPED'}
      </div>
      <div class="header-right">
        <button class="icon-btn menu-btn" on:click={() => openSidebar('changelog')} title="Menu">☰</button>
        <div class="meta">Zone: {state.zone} · Time: {state.timer}</div>
      </div>
    </header>

    <section class="controls">
      <button class="start" on:click={() => api('start')}>▶ Start</button>
      <button class="stop" on:click={() => api('stop')}>■ Stop</button>
    </section>

    <section class="panes">
      <article>
        <h2>LIVE LOG</h2>
        <pre style="font-size: {state.items_font_size ?? 12}px">{state.logs.join('\n')}</pre>
      </article>

      <article>
        <h2>SESSION TOTALS</h2>
        <pre style="font-size: {state.items_font_size ?? 12}px">{state.totals.map((t) => `${t.name} ×${t.qty}`).join('\n')}</pre>
      </article>
    </section>
  </main>

</div>
