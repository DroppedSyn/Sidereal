import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Dev: `sidereal serve` on 8470, Vite on 5173 proxying /api. Writes from the dev server need
// SIDEREAL_WEB__ALLOWED_ORIGINS='["http://localhost:5173"]' (see AGENTS.md Decisions).
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:8470' },
  },
  build: {
    outDir: 'dist',
    // CSP is script-src 'self': no inline scripts, no polyfill snippet.
    modulePreload: { polyfill: false },
    assetsInlineLimit: 0,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
  },
});
