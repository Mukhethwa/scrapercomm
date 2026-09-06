import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// base './' so built assets resolve when FastAPI serves the app at "/".
// The dev server proxies /api to the FastAPI server on :8000.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // shadcn generates components that import from "@/...", so the alias has to exist
    // in both the bundler and the type checker.
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  base: './',
  server: {
    // Listen on every interface, not just loopback, so a phone on the same Wi-Fi can
    // reach the dev server. The /api proxy below is made by this server rather than by
    // the browser, so it still resolves localhost:8000 correctly from a remote device.
    host: true,
    proxy: { '/api': 'http://localhost:8000' },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
