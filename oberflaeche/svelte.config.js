import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { readFileSync } from 'node:fs';

// Fester Versionsname: SvelteKit nimmt sonst Date.now() und laedt die Einstellungen beim Bauen mehrmals. Dann
// passen der Name in index.html (Rueckfallseite) und der in den Skripten nicht zusammen, und die Seite bleibt leer.
const paket = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8'));

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({ pages: 'build', assets: 'build', fallback: 'index.html', strict: true }),
    // Kein Inline-Skript ausser dem Start von SvelteKit; die Hülle setzt die Inhaltsrichtlinie.
    output: { bundleStrategy: 'split' },
    version: { name: paket.version }
  }
};

export default config;
