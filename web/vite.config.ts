import { copyFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import vue from '@vitejs/plugin-vue';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, type Plugin } from 'vitest/config';

const staticSpaRoutes = [
  'activity', 'storage', 'downloads', 'aria2', 'chat-send', 'exports', 'quick-mode',
  'tts', 'decrypt', 'utility', 'backups', 'profiles', 'profiles/vault', 'workers',
  'settings', 'development',
];

function staticReleaseFiles(): Plugin {
  return {
    name: 'tme3-static-release-files',
    writeBundle(outputOptions) {
      const directory = outputOptions.dir || fileURLToPath(new URL('./build', import.meta.url));
      const indexFile = join(directory, 'index.html');
      copyFileSync(indexFile, join(directory, '200.html'));
      for (const route of staticSpaRoutes) {
        const routeDirectory = join(directory, route);
        mkdirSync(routeDirectory, { recursive: true });
        copyFileSync(indexFile, join(routeDirectory, 'index.html'));
      }
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
    include: [join(fileURLToPath(new URL('./', import.meta.url)), 'vue/src/**/*.test.ts'), join(fileURLToPath(new URL('./', import.meta.url)), 'src/lib/*.test.ts')],
    setupFiles: [fileURLToPath(new URL('./vue/src/test-setup.ts', import.meta.url))]
  }
});
