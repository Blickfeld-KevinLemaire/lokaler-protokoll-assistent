import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import globals from 'globals';
import ts from 'typescript-eslint';

export default ts.config(
  {
    ignores: [
      'build/',
      '.svelte-kit/',
      'node_modules/',
      'screenshots/',
      'src/lib/api/schema.d.ts',
      'src-tauri/'
    ]
  },
  js.configs.recommended,
  ...ts.configs.recommended,
  ...svelte.configs.recommended,
  {
    languageOptions: { globals: { ...globals.browser, ...globals.node } }
  },
  {
    files: ['**/*.svelte', '**/*.svelte.ts'],
    languageOptions: {
      parserOptions: {
        projectService: true,
        extraFileExtensions: ['.svelte'],
        parser: ts.parser
      }
    }
  },
  {
    rules: {
      // Inhalte können vertraulich sein: nichts ungefiltert in die Konsole (siehe src/lib/protokoll.ts).
      'no-console': ['error', { allow: ['warn', 'error'] }],
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      // Interne Verweise laufen über href mit festen Pfaden; resolve() bringt hier nichts.
      'svelte/no-navigation-without-resolve': 'off'
    }
  },
  {
    files: ['bildschirmfotos/**'],
    rules: { 'no-console': 'off' }
  }
);
