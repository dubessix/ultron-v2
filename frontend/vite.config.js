import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const loopbackHost = '127.0.0.1'
const localHosts = ['localhost', '127.0.0.1']

// Development/preview remain available for manual work, but never bind to the
// LAN. Daily launcher usage serves the production dist through Python instead.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    host: loopbackHost,
    allowedHosts: localHosts,
  },
  preview: {
    port: 5173,
    strictPort: true,
    host: loopbackHost,
    allowedHosts: localHosts,
  },
})
