import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiPaths = [
  '/stats', '/scores', '/scan', '/plays', '/backtest', '/weights',
  '/health', '/auth', '/augur', '/tickers', '/universe', '/earnings',
  '/calibrate', '/backfill', '/debug', '/killer-plays', '/inverse-plays',
  '/signals', '/market', '/intel', '/watchlist', '/notify', '/alerts',
  '/admin', '/chart',
]

// Proxy target is env-overridable so the dev server can run against a remote
// API (e.g. VITE_API_TARGET=https://cyber.keltonshockey.com) without a local
// backend. Defaults to the local uvicorn instance.
const API_TARGET = process.env.VITE_API_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: '127.0.0.1',
    proxy: Object.fromEntries(
      apiPaths.map(p => [p, { target: API_TARGET, changeOrigin: true, secure: true }])
    ),
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
