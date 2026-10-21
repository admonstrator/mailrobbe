import { readFileSync } from "node:fs";

import { defineConfig, type Plugin } from "vite";

// The PDF viewer (D121), built apart from the app: one classic script, dist/viewer/pdf.js, and
// its page, dist/viewer/pdf.html. `npm run build` runs this after the app's build, which empties
// dist; `npm run build:viewer -- --watch` rebuilds it alone while working on it.

const VIEWER_PAGE = "src/viewer/pdf.html";

/** The page as it is; the server writes a nonce per response into its script tag. */
function viewerPage(): Plugin {
  return {
    name: "mailrobbe-viewer-page",
    buildStart() {
      this.addWatchFile(VIEWER_PAGE);
    },
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "pdf.html",
        source: readFileSync(VIEWER_PAGE, "utf8"),
      });
    },
  };
}

// pdf.js decodes JBIG2, CCITT fax (common in scans) and JPEG 2000 images with wasm, else with
// JavaScript decoders it imports from wasmUrl at run time. The viewer's policy allows neither
// compiling wasm nor loading modules, so these decoders are bundled and handed over in place of
// that import. The build fails when pdf.js changes the line, rather than leave scans blank.
const DECODER_IMPORT =
  /import\(\s*\/\*webpackIgnore: true\*\/\s*\/\*@vite-ignore\*\/\s*`\$\{WasmImage\.#wasmUrl\}\$\{this\._noWasmFilename\}`\)/g;
const BUNDLED_DECODERS = `({
  "jbig2_nowasm_fallback.js": () => import("pdfjs-dist/wasm/jbig2_nowasm_fallback.js"),
  "openjpeg_nowasm_fallback.js": () => import("pdfjs-dist/wasm/openjpeg_nowasm_fallback.js"),
})[this._noWasmFilename]()`;

function bundledImageDecoders(): Plugin {
  return {
    name: "mailrobbe-pdfjs-image-decoders",
    transform(code, id) {
      if (!id.replaceAll("\\", "/").endsWith("/pdfjs-dist/legacy/build/pdf.worker.mjs"))
        return null;
      const found = code.match(DECODER_IMPORT)?.length ?? 0;
      if (found !== 1) this.error(`expected one import of pdf.js's image decoders, found ${found}`);
      return { code: code.replace(DECODER_IMPORT, BUNDLED_DECODERS), map: null };
    },
  };
}

export default defineConfig({
  plugins: [viewerPage(), bundledImageDecoders()],
  publicDir: false,
  build: {
    outDir: "dist/viewer",
    emptyOutDir: true,
    minify: true,
    // import.meta has no place in a classic script; pdf.js reads it only on Node, and the
    // decoders above only to find wasm files they do not load here.
    rolldownOptions: { transform: { define: { "import.meta": "{}" } } },
    lib: {
      entry: "src/viewer/main.ts",
      formats: ["iife"],
      name: "mailrobbeViewer",
      fileName: () => "pdf.js",
    },
  },
});
