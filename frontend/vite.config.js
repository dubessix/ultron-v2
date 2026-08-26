import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const loopbackHost = '127.0.0.1'
const localHosts = ['localhost', '127.0.0.1']
const codespacesWebMode = process.env.ULTRON_CODESPACES_WEB === '1' || process.env.CODESPACES === 'true'

// Daily local operation uses the Python production static server on loopback.
// Codespaces Web Mode is explicit: Vite owns one forwarded browser port and
// proxies API/WebSocket traffic to the internal loopback FastAPI service.
const developmentServer = {
  port: 5173,
  strictPort: true,
  host: codespacesWebMode ? '0.0.0.0' : loopbackHost,
  allowedHosts: codespacesWebMode ? true : localHosts,
  proxy: {
    '/api': {
      target: 'http://127.0.0.1:8000',
      changeOrigin: true,
    },
    '/ws': {
      target: 'ws://127.0.0.1:8000',
      ws: true,
    },
  },
}

export default defineConfig({
  plugins: [react()],
  server: developmentServer,
  preview: {
    port: 5173,
    strictPort: true,
    host: loopbackHost,
    allowedHosts: localHosts,
  },
})
