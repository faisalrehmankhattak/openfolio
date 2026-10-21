import { defineConfig } from "vite";
import { copyFileSync, mkdirSync } from "node:fs";

const HEADAUDIO = "node_modules/@met4citizen/headaudio/dist";

// app.js: ES module with lazily loaded chunks (3D, voice), fetched only when opened.
export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2020",
    minify: true,
    chunkSizeWarningLimit: 1500,
    lib: { entry: "src/app.ts", formats: ["es"], fileName: () => "app.js" },
    rollupOptions: { output: { chunkFileNames: "chunks/[name]-[hash].js" } },
  },
  plugins: [
    {
      name: "copy-headaudio-assets",
      closeBundle() {
        mkdirSync("dist", { recursive: true });
        for (const f of ["headworklet.min.mjs", "model-en-mixed.bin"]) copyFileSync(`${HEADAUDIO}/${f}`, `dist/${f}`);
      },
    },
  ],
});
