import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
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
