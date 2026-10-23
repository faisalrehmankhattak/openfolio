import { defineConfig } from "vite";

// embed.js: one small classic script (IIFE) so `<script async src>` works anywhere.
export default defineConfig({
  define: { __OPENFOLIO_BUILD__: JSON.stringify(Date.now().toString(36)) },
  build: {
    outDir: "dist",
    emptyOutDir: false,
    target: "es2020",
    minify: true,
    lib: { entry: "src/loader.ts", formats: ["iife"], name: "Openfolio", fileName: () => "embed.js" },
  },
});
