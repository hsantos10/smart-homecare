import path from "path"
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: parseInt(process.env.PORT || "5173"),
    strictPort: true, // fail loudly instead of silently drifting to another port
    proxy: {
      // The caregiver app talks ONLY to the shared REST API — same contract the
      // Android app will use. In dev we proxy /api → FastAPI on :8000 (see RUNNING.md).
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
})
