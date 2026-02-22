import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { tanstackRouter } from "@tanstack/router-vite-plugin";

export default defineConfig({
  plugins: [
    tanstackRouter(), // ✅ must be BEFORE react()
    react(),
  ],
  server: {
    proxy: {
      "/opensanctions": {
        target: "https://api.opensanctions.org",
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/opensanctions/, ""),
      },
    },
  },
});
