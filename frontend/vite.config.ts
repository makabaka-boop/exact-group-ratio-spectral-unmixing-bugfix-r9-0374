import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During development the SPA calls /api/* on the FastAPI server.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
