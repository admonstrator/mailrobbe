import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The backend that `npm run dev` and `npm run preview` forward /api to, and /viewer: the PDF viewer
// is built on its own (`npm run build:viewer`) and needs the policy the backend serves it with.
const api = process.env.MAILROBBE_API ?? "http://127.0.0.1:8000";
const proxy = { "/api": api, "/viewer": api };

export default defineConfig({
  plugins: [react()],
  base: "/",
  server: { port: 5173, proxy },
  preview: { proxy },
  test: {
    environment: "jsdom",
    // Dates are shown in the browser's time zone; the tests pin one.
    env: { TZ: "Europe/Berlin" },
    setupFiles: ["src/test/setup.ts"],
  },
});
