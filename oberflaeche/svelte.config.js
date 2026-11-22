import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({ pages: 'build', assets: 'build', fallback: 'index.html', strict: true }),
    // Kein Inline-Skript ausser dem Start von SvelteKit; die Hülle setzt die Inhaltsrichtlinie.
    output: { bundleStrategy: 'split' }
  }
};

export default config;
