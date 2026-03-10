import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiPaths = [
  '/stats', '/scores', '/scan', '/plays', '/backtest', '/weights',
  '/health', '/auth', '/augur', '/tickers', '/universe', '/earnings',
  '/calibrate', '/backfill', '/debug', '/killer-plays', '/inverse-plays',
  '/signals', '/market', '/intel', '/watchlist', '/notify', '/alerts',
  '/admin', '/chart',
]

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: '127.0.0.1',
    proxy: Object.fromEntries(
      apiPaths.map(p => [p, { target: 'http://localhost:8000', changeOrigin: true }])
    ),
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
