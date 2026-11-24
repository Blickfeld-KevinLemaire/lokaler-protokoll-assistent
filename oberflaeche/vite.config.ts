/// <reference types="vitest/config" />
import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { readFileSync } from 'node:fs';
import { defineConfig, loadEnv, type ProxyOptions } from 'vite';

// Fester Versionsname: SvelteKit nimmt sonst Date.now() und laedt die Einstellungen beim Bauen mehrmals. Dann
// passen der Name in index.html (Rueckfallseite) und der in den Skripten nicht zusammen, und die Seite bleibt leer.
const paket = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8')) as {
  version: string;
};

/**
 * Entwicklungsserver: Sind VERMERK_DIENST_URL und VERMERK_API_SCHLUESSEL gesetzt (Umgebung oder .env),
 * leitet Vite /api an den Dienst weiter und setzt den Schlüssel dort – auf dem Server, nie im Bündel.
 * Die Seite verhält sich dann wie im Browser (gleiche Herkunft).
 */
function dienstProxy(mode: string): Record<string, ProxyOptions> | undefined {
  const umgebung = { ...loadEnv(mode, process.cwd(), 'VERMERK_'), ...process.env };
  const ziel = umgebung.VERMERK_DIENST_URL;
  const schluessel = umgebung.VERMERK_API_SCHLUESSEL;
  if (!ziel || !schluessel) return undefined;
  return {
    '/api': {
      target: ziel,
      changeOrigin: true,
      headers: { Authorization: `Bearer ${schluessel}` }
    }
  };
}

export default defineConfig(({ mode }) => ({
  // SvelteKit 3: Die Einstellungen stehen hier statt in svelte.config.js.
  plugins: [
    sveltekit({
      preprocess: vitePreprocess(),
      adapter: adapter({ pages: 'build', assets: 'build', fallback: 'index.html', strict: true }),
      // Kein Inline-Skript ausser dem Start von SvelteKit; die Hülle setzt die Inhaltsrichtlinie.
      output: { bundleStrategy: 'split' },
      // pollInterval 0 wie bis SvelteKit 2: kein stündliches Nachfragen nach /_app/version.json.
      version: { name: paket.version, pollInterval: 0 }
    })
  ],
  // Keine VERMERK_-Variablen ins Bündel: nur das übliche Präfix VITE_ wird eingebettet.
  envPrefix: 'VITE_',
  server: { port: 5173, strictPort: true, proxy: dienstProxy(mode) },
  resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined,
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.ts'],
    restoreMocks: true
  }
}));
