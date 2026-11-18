<script setup lang="ts">
import type { MarkdownInline } from '../../services/markdownBlocks'

defineProps<{
  tokens: MarkdownInline[]
}>()

const emit = defineEmits<{
  openFile: [path: string, line?: number]
}>()

const FILE_EXT_RE = /\.(?:ts|tsx|js|jsx|mjs|cjs|vue|py|json|css|scss|less|html|htm|svg|md|rs|go|sql|ya?ml|sh|bash|ps1|toml|txt|env|ini|cfg)$/i

function parseFileCitation(raw: string): { path: string; line?: number } | null {
  const s = raw.trim().replace(/^@/, '')
  if (!s || s.length > 200 || /[\s*<>|"`]/.test(s) || s.includes('://') || s.includes('::')) {
    return null
  }
  const m = /^(.+?)(?:#L(\d+)(?:-L?\d+)?|:(\d+))?$/.exec(s)
  if (!m) return null
  const cleanPath = m[1]
  const line = m[2] ? Number(m[2]) : m[3] ? Number(m[3]) : undefined
  if (!cleanPath.includes('/') && !FILE_EXT_RE.test(cleanPath)) return null
  if (!FILE_EXT_RE.test(cleanPath) && !cleanPath.includes('.')) return null
  return { path: cleanPath, ...(line && Number.isFinite(line) ? { line } : {}) }
}
</script>

<template>
  <template v-for="(tok, idx) in tokens" :key="`${tok.type}-${idx}`">
    <strong v-if="tok.type === 'bold'">{{ tok.text }}</strong>
    <em v-else-if="tok.type === 'italic'">{{ tok.text }}</em>
    <del v-else-if="tok.type === 'strike'">{{ tok.text }}</del>
    <button
      v-else-if="tok.type === 'code' && parseFileCitation(tok.text)"
      type="button"
      class="md-inline-file"
      :title="`点击预览工作区文件：${parseFileCitation(tok.text)!.path}`"
      @click="emit('openFile', parseFileCitation(tok.text)!.path, parseFileCitation(tok.text)!.line)"
    >
      <code class="md-inline-code">{{ tok.text }}</code>
    </button>
    <code v-else-if="tok.type === 'code'" class="md-inline-code">{{ tok.text }}</code>
    <a v-else-if="tok.type === 'link'" :href="tok.href" target="_blank" rel="noopener noreferrer" class="md-link">{{ tok.text }}</a>
    <template v-else>{{ tok.text }}</template>
  </template>
</template>

<style scoped>
.md-inline-file {
  display: inline;
  padding: 0;
  margin: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  color: var(--accent);
}
.md-inline-file .md-inline-code {
  color: var(--accent);
  border: 1px solid var(--accent-line);
}
.md-inline-file:hover .md-inline-code {
  background: var(--accent-soft);
}
</style>
