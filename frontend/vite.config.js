/**
 * =============================================================================
 * CONFIGURAZIONE VITE — BUILD TOOL PER IL FRONTEND REACT
 * =============================================================================
 * 
 * Configurazione per lo sviluppo e la build dell'applicazione React.
 * 
 * PLUGINS:
 * - @vitejs/plugin-react: supporto React con Fast Refresh
 * 
 * SERVER DI SVILUPPO:
 * - Porta: 3000
 * - Host: 0.0.0.0 (accessibile da tutte le interfacce)
 * - Proxy: reindirizza /api a http://api:8000 (backend FastAPI in Docker)
 * 
 * BUILD:
 * - Output: cartella dist/
 * - Sourcemap: disabilitati per produzione
 */

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: '0.0.0.0',
    proxy: {
      '/api': 'http://api:8000'
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: false
  }
})