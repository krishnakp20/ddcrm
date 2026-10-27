import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend port can be changed with API_PORT (default 8000), for example when that port is already taken.
const api = `http://localhost:${process.env.API_PORT || 8000}`;

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": api,
    },
  },
});
