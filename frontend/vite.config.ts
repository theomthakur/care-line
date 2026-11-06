/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { lstatSync, readFileSync } from "node:fs";
import type { ProxyOptions } from "vite";

// The console never holds an agent key. Operator routes are reached through this
// same-origin proxy to the local backend (see contracts/api.md, "Transport, access").
const backend = process.env.CARELINE_BACKEND ?? "http://127.0.0.1:8000";
const target = new URL(backend);
if (target.username || target.password || target.search || target.hash) {
  throw new Error("Console backend URLs must not contain credentials, query or fragment");
}
if (target.protocol !== "https:" && !(target.protocol === "http:" && ["127.0.0.1", "[::1]"].includes(target.hostname))) {
  throw new Error("Remote console backends require HTTPS");
}
// Development only. Mounted service credentials stay in this local proxy and
// never enter browser JavaScript, localStorage, or VITE_* build variables.
const securedProxy: ProxyOptions = {
  target: backend,
  configure(proxy) {
    proxy.on("proxyReq", (request, incoming) => {
      for (const header of ["authorization", "x-agent-key", "x-call-key"]) request.removeHeader(header);
      const file = incoming.url?.startsWith("/admin/")
        ? process.env.MEMBERGUIDE_ADMIN_KEY_FILE
        : process.env.MEMBERGUIDE_OPERATOR_KEY_FILE;
      if (file) {
        const info = lstatSync(file);
        if (!info.isFile() || (info.mode & 0o077) !== 0) throw new Error("Console credential files must be owner-only regular files");
        request.setHeader("Authorization", "Bearer " + readFileSync(file, "utf8").trim());
      }
    });
  },
};

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/calls": securedProxy,
      "/tasks": securedProxy,
      "/providers": securedProxy,
      "/admin": securedProxy,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
