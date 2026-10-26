import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The base path is injected at build time: `vite build --base=/projects-site/labs/revenue-atlas/`.
// Locally `npm run dev` serves at "/". Nothing in src/ may assume "/" is the site root.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false, target: "es2020" },
  server: { port: 5173, strictPort: true },
  preview: { port: 4173, strictPort: true },
});
