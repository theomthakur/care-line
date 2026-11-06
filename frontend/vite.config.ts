/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The console never holds an agent key. Operator routes are reached through this
// same-origin proxy to the local backend (see contracts/api.md, "Transport, access").
const backend = process.env.CARELINE_BACKEND ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/calls": backend,
      "/tasks": backend,
      "/admin": backend,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
