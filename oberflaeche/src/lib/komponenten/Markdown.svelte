<script lang="ts">
  /** Markdown → bereinigtes HTML (marked + DOMPurify). */
  import DOMPurify from 'dompurify';
  import { marked } from 'marked';

  let { text }: { text: string } = $props();

  const html = $derived(
    DOMPurify.sanitize(marked.parse(text ?? '', { async: false, gfm: true, breaks: false }))
  );
</script>

<div class="md">
  <!-- eslint-disable-next-line svelte/no-at-html-tags -- mit DOMPurify bereinigt -->
  {@html html}
</div>

<style>
  .md {
    line-height: 1.6;
    color: var(--text);
    overflow-wrap: anywhere;
  }

  .md :global(h1) {
    font-size: 19px;
    margin: 0 0 12px;
  }

  .md :global(h2) {
    font-size: 16px;
    margin: 20px 0 8px;
  }

  .md :global(h3) {
    font-size: 14.5px;
    margin: 16px 0 6px;
  }

  .md :global(p) {
    margin: 0 0 10px;
  }

  .md > :global(:last-child) {
    margin-bottom: 0;
  }

  .md :global(ul),
  .md :global(ol) {
    margin: 0 0 10px;
    padding-left: 22px;
  }

  .md :global(li) {
    margin: 2px 0;
  }

  .md :global(table) {
    border-collapse: collapse;
    margin: 8px 0 14px;
    width: 100%;
  }

  .md :global(th),
  .md :global(td) {
    border: 1px solid var(--rand);
    padding: 6px 10px;
    text-align: left;
  }

  .md :global(th) {
    background: var(--karte-2);
  }

  .md :global(code) {
    padding: 1px 5px;
    border-radius: 4px;
    background: var(--karte-2);
    font-size: 13px;
  }

  .md :global(blockquote) {
    margin: 0 0 10px;
    padding-left: 12px;
    border-left: 3px solid var(--rand);
    color: var(--text-2);
  }
</style>
