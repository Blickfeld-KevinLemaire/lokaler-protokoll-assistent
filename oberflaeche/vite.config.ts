/// <reference types="vitest/config" />
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, loadEnv, type ProxyOptions } from 'vite';

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
  plugins: [sveltekit()],
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
