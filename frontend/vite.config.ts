import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const API = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: API, changeOrigin: true },
      "/serve": { target: API, changeOrigin: true },
      "/ws": { target: API.replace("http", "ws"), ws: true, changeOrigin: true },
    },
  },
  preview: {
    port: 4173,
    proxy: {
      "/api": { target: API, changeOrigin: true },
      "/serve": { target: API, changeOrigin: true },
      "/ws": { target: API.replace("http", "ws"), ws: true, changeOrigin: true },
    },
  },
  build: {
    chunkSizeWarningLimit: 1800,
    rollupOptions: {
      output: {
        manualChunks: {
          three: ["three", "@react-three/fiber", "@react-three/drei", "@react-three/postprocessing", "postprocessing"],
          charts: ["recharts"],
          flow: ["@xyflow/react"],
          motion: ["gsap", "@gsap/react"],
        },
      },
    },
  },
});
