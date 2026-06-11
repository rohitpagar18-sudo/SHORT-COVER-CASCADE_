import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: Vite on 5173 proxies /api -> FastAPI on 8000.
// Prod: vite build -> dist/; FastAPI serves the dist on the same port.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
