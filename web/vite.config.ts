import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base './' so built assets resolve when FastAPI serves the app at "/".
// The dev server proxies /api to the FastAPI server on :8000.
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    proxy: { '/api': 'http://localhost:8000' },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
