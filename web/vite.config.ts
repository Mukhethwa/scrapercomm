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
    proxy: { '/api': 'http://localhost:8000' },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
