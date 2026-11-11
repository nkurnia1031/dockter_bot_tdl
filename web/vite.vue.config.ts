import { fileURLToPath } from 'node:url';
import { copyFileSync } from 'node:fs';
import { join } from 'node:path';
import { defineConfig, type Plugin } from 'vite';
import vue from '@vitejs/plugin-vue';

function staticSpaFallback(): Plugin {
  return {
    name: 'tme3-static-spa-fallback',
    writeBundle(outputOptions) {
      const directory = outputOptions.dir || fileURLToPath(new URL('./build-vue', import.meta.url));
      copyFileSync(join(directory, 'index.html'), join(directory, '200.html'));
    }
  };
}

export default defineConfig({
  root: fileURLToPath(new URL('./vue/', import.meta.url)),
  base: '/',
  plugins: [vue(), staticSpaFallback()],
  build: {
    outDir: '../build-vue',
    emptyOutDir: true
  }
});
