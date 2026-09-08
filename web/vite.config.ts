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
    /*
     * Tunnel domains, for letting somebody else open the dev server.
     *
     * Vite rejects a request whose Host header it does not recognise, which is what stops
     * a hostile page in a browser on this machine from reaching the dev server by name.
     * Named domains rather than `true`: that keeps the protection for every host except
     * the three services actually used to share a preview.
     */
    allowedHosts: ['.trycloudflare.com', '.devtunnels.ms', '.ngrok-free.dev', '.ngrok-free.app', '.ngrok.io'],
    proxy: { '/api': 'http://localhost:8000' },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
