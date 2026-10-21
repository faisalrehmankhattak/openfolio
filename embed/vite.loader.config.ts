import { defineConfig } from "vite";

// embed.js: one small classic script (IIFE) so `<script async src>` works anywhere.
export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: false,
    target: "es2020",
    minify: true,
    lib: { entry: "src/loader.ts", formats: ["iife"], name: "Openfolio", fileName: () => "embed.js" },
  },
});
