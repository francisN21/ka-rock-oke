import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built files are served by Flask at /app/. In dev, API and socket calls go to a
// PiKaraoke running on this machine.
const backend = process.env.PIKARAOKE_URL || "http://localhost:5555";

export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: {
    host: true,
    proxy: {
      "/api": backend,
      "/socket.io": { target: backend, ws: true },
      "/qrcode": backend,
    },
  },
});
