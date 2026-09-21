import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    // Caddy раздаёт эту папку как статику (см. docker-compose.yml)
    outDir: "dist",
    sourcemap: false,
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    // в dev API берётся с бэкенда напрямую; в проде — тот же домен через Caddy
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
