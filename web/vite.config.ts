import { copyFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import vue from '@vitejs/plugin-vue';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, type Plugin } from 'vitest/config';

function staticReleaseFiles(): Plugin {
  return {
    name: 'tme3-static-release-files',
    writeBundle(outputOptions) {
      const directory = outputOptions.dir || fileURLToPath(new URL('./build', import.meta.url));
      copyFileSync(join(directory, 'index.html'), join(directory, '200.html'));
      copyFileSync(fileURLToPath(new URL('./static/build-info.json', import.meta.url)), join(directory, 'build-info.json'));
    }
  };
}

export default defineConfig({
  root: fileURLToPath(new URL('./vue/', import.meta.url)),
  base: '/',
  publicDir: fileURLToPath(new URL('./public/', import.meta.url)),
  plugins: [vue(), tailwindcss(), staticReleaseFiles()],
  resolve: { conditions: ['browser'] },
  build: {
    outDir: '../build',
    emptyOutDir: true
  },
  test: {
    environment: 'jsdom',
    include: ['vue/src/**/*.test.ts', 'src/lib/*.test.ts'],
    setupFiles: ['./vue/src/test-setup.ts']
  }
});
