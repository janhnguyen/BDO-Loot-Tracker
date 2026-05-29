import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

const mockState = {
  running: false,
  paused: false,
  zone: 'Thornwood Forest [Dehkia]',
  timer: '00:00:00',
  timer_seconds: 0,
  logs: [
    '[12:00:01] Bloody Tree Knot ×3',
    '[12:00:04] Trace of Savagery ×1',
    '[12:00:09] Black Stone (Weapon) ×1',
  ],
  totals: [
    { name: 'Bloody Tree Knot', qty: 12 },
    { name: 'Trace of Savagery', qty: 5 },
    { name: 'Black Stone (Weapon)', qty: 2 },
  ],
  session_silver: 1480000,
  show_ocr: false,
  show_ocr_pane: false,
  show_live_log: false,
  tracking_window_size: 20,
  items_font_size: 12,
  sessions: ['#1 | 2025-01-01 12:00:00 UTC → 2025-01-01 13:00:00 UTC | closed'],
  selected_session: '#1 | 2025-01-01 12:00:00 UTC → 2025-01-01 13:00:00 UTC | closed',
  market_updating: false,
  keybind_start: 'Control+Shift+A',
  keybind_pause: 'Control+Shift+S',
  keybind_stop: 'Control+Shift+D',
  character_name: 'Adventurer',
  needs_calibration: false,
  current_version: '0.0.0-dev',
  latest_version: '',
  update_available: false,
  update_url: '',
  update_checking: false,
  update_downloading: false,
  update_download_progress: 0,
  update_cancelled: false,
};

const mockDbStats = {
  summary: {
    total_sessions: 3,
    total_items: 248,
    total_silver: 12400000,
    best_avg_hour: 4800000,
    best_zone: 'Thornwood Forest [Dehkia]',
    best_session_id: 1,
  },
  sessions: [
    {
      id: 1,
      zone: 'Thornwood Forest [Dehkia]',
      started_at: '2025-01-01 12:00:00 UTC',
      ended_at: '2025-01-01 13:00:00 UTC',
      duration: '01:00:00',
      avg_hour: 4800000,
      total_silver: 4800000,
      item_count: 8,
    },
    {
      id: 2,
      zone: 'Saunil Camp',
      started_at: '2025-01-02 10:00:00 UTC',
      ended_at: '2025-01-02 10:30:00 UTC',
      duration: '00:30:00',
      avg_hour: 3200000,
      total_silver: 1600000,
      item_count: 5,
    },
  ],
  top_items: [
    { item_name: 'Bloody Tree Knot', total_qty: 120 },
    { item_name: 'Trace of Savagery', total_qty: 85 },
    { item_name: 'Black Stone (Weapon)', total_qty: 43 },
  ],
};

function mockApiPlugin() {
  return {
    name: 'mock-api',
    configureServer(server) {
      server.middlewares.use('/api', (req, res) => {
        res.setHeader('Content-Type', 'application/json');
        const url = req.url ?? '/';
        const action = url.split('?')[0].replace(/^\//, '');

        if (req.method === 'GET') {
          if (action === 'state') return res.end(JSON.stringify(mockState));
          if (action === 'changelog') return res.end(JSON.stringify({ text: '## v0.0.0-dev\n- Mock changelog for UI development.' }));
          if (action === 'db_stats') return res.end(JSON.stringify(mockDbStats));
          if (action.startsWith('session_detail')) return res.end(JSON.stringify({
            session: mockDbStats.sessions[0],
            timeline: [
              { elapsed_seconds: 120, value: 800000, item_name: 'Bloody Tree Knot', quantity: 4 },
              { elapsed_seconds: 900, value: 1600000, item_name: 'Trace of Savagery', quantity: 2 },
              { elapsed_seconds: 2400, value: 2400000, item_name: 'Black Stone (Weapon)', quantity: 1 },
            ],
            items: [
              { item_name: 'Bloody Tree Knot', quantity: 48, value: 2400000 },
              { item_name: 'Trace of Savagery', quantity: 20, value: 1400000 },
              { item_name: 'Black Stone', quantity: 5, value: 1000000 },
            ],
          }));
          res.statusCode = 404;
          return res.end(JSON.stringify({ error: 'not found' }));
        }

        if (req.method === 'POST') {
          let body = '';
          req.on('data', chunk => { body += chunk; });
          req.on('end', () => {
            const payload = body ? JSON.parse(body) : {};
            if (action === 'start')  mockState.running = true;
            if (action === 'stop')   { mockState.running = false; mockState.paused = false; }
            if (action === 'pause')  mockState.paused = true;
            if (action === 'resume') mockState.paused = false;
            if (action === 'set_character_name' && payload.value) mockState.character_name = payload.value;
            if (action === 'set_tracking_window') mockState.tracking_window_size = payload.value;
            if (action === 'set_font_size') mockState.items_font_size = payload.value;
            if (action === 'toggle_ocr') mockState.show_ocr = payload.value;
            if (action === 'toggle_ocr_pane') mockState.show_ocr_pane = payload.value;
            if (action === 'toggle_live_log') mockState.show_live_log = payload.value;
            if (action === 'set_keybind') {
              if (payload.action === 'start') mockState.keybind_start = payload.key;
              if (payload.action === 'pause') mockState.keybind_pause = payload.key;
              if (payload.action === 'stop')  mockState.keybind_stop  = payload.key;
            }
            res.end(JSON.stringify({ ok: true }));
          });
          return;
        }

        res.statusCode = 405;
        res.end(JSON.stringify({ error: 'method not allowed' }));
      });
    },
  };
}

export default defineConfig({
  plugins: [svelte(), mockApiPlugin()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
