import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'
import { env } from 'node:process'

const backendProxy = env.NAVIRA_BACKEND_URL || 'http://127.0.0.1:8000'
const frontendPort = Number(env.NAVIRA_FRONTEND_PORT || 5174)

export default defineConfig({
  plugins: [react()],
  cacheDir: './.vite-cache',
  server: {
    host: '127.0.0.1',
    port: frontendPort,
    strictPort: true,
    proxy: {
      '/api': backendProxy,
      '/health': backendProxy,
    },
  },
  test: { environment: 'jsdom', setupFiles: './src/test/setup.js', clearMocks: true },
})
