<script setup lang="ts">
import type { MarkdownInline } from '../../services/markdownBlocks'
import OpusIcon from '../ui/OpusIcon.vue'

const props = defineProps<{
  tokens: MarkdownInline[]
  knownFiles?: Set<string>
}>()

const emit = defineEmits<{
  openFile: [path: string, line?: number]
}>()

const FILE_EXT_RE =
  /\.(?:ts|tsx|js|jsx|mjs|cjs|vue|py|json|css|scss|less|html|htm|svg|md|rs|go|sql|ya?ml|sh|bash|ps1|toml|txt|env|ini|cfg|png|jpe?g|gif|webp|bmp|ico|pdf|zip|tar|gz|7z|csv|xlsx?|docx?|mp3|mp4|wav)$/i

function parseFileCitation(raw: string): { path: string; line?: number } | null {
  const s = raw.trim().replace(/^@/, '')
  if (!s || s.length > 220 || /[\s*<>|"`]/.test(s) || s.includes('://') || s.includes('::')) {
    return null
  }
  const m = /^(.+?)(?:#L(\d+)(?:-L?\d+)?|:(\d+))?$/.exec(s)
  if (!m) return null
  const cleanPath = m[1]
  const normSep = cleanPath.replace(/\\/g, '/')
  const line = m[2] ? Number(m[2]) : m[3] ? Number(m[3]) : undefined
  if (!normSep.includes('/') && !FILE_EXT_RE.test(cleanPath)) return null
  if (!FILE_EXT_RE.test(cleanPath) && !cleanPath.includes('.')) return null
  return { path: cleanPath, ...(line && Number.isFinite(line) ? { line } : {}) }
}

function isPossiblyMissingFile(filePath: string): boolean {
  const known = props.knownFiles
  if (!known || known.size === 0) return false
  const norm = filePath.replace(/\\/g, '/').replace(/^\.\//, '').toLowerCase()
  if (known.has(norm)) return false
  for (const item of known) {
    if (item.endsWith(`/${norm}`) || item === norm) return false
  }
  return true
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
      :class="{ 'is-missing': isPossiblyMissingFile(parseFileCitation(tok.text)!.path) }"
      :title="
        isPossiblyMissingFile(parseFileCitation(tok.text)!.path)
          ? `当前已扫描工作区中未匹配到 ${parseFileCitation(tok.text)!.path}（点击仍可尝试读取）`
          : `点击预览工作区文件：${parseFileCitation(tok.text)!.path}`
      "
      @click="emit('openFile', parseFileCitation(tok.text)!.path, parseFileCitation(tok.text)!.line)"
    >
      <code class="md-inline-code">{{ tok.text }}</code>
    </button>
    <code v-else-if="tok.type === 'code'" class="md-inline-code">{{ tok.text }}</code>
    <span v-else-if="tok.type === 'image'" class="md-inline-img-card">
      <a :href="tok.src" target="_blank" rel="noopener noreferrer" class="md-inline-img-link" :title="`查看原图：${tok.alt}`">
        <img :src="tok.src" :alt="tok.alt" loading="lazy" class="md-inline-img" />
      </a>
      <span class="md-inline-img-bar">
        <span class="md-inline-img-caption">{{ tok.alt }}</span>
        <a
          :href="tok.src"
          :download="tok.alt || 'image'"
          target="_blank"
          rel="noopener noreferrer"
          class="md-inline-img-dl"
          title="下载图片"
        >
          <OpusIcon name="download" />
          <span>下载</span>
        </a>
      </span>
    </span>
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
.md-inline-file.is-missing .md-inline-code {
  color: var(--text-3);
  border-style: dashed;
  border-color: color-mix(in srgb, var(--warn) 45%, var(--line));
}
.md-inline-file:hover .md-inline-code {
  background: var(--accent-soft);
}
.md-inline-img-card {
  display: inline-flex;
  flex-direction: column;
  max-width: min(360px, 100%);
  margin: 6px 0;
  border: 1px solid var(--line-strong);
  border-radius: 10px;
  overflow: hidden;
  background: var(--surface-2);
  vertical-align: middle;
}
.md-inline-img-link {
  display: block;
  line-height: 0;
}
.md-inline-img {
  display: block;
  max-width: 100%;
  max-height: 240px;
  width: auto;
  height: auto;
  object-fit: contain;
}
.md-inline-img-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 5px 9px;
  border-top: 1px solid var(--line);
  background: var(--solid);
  font-size: 11.5px;
}
.md-inline-img-caption {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-2);
}
.md-inline-img-dl {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: none;
  color: var(--accent);
  font-weight: 560;
  text-decoration: none;
}
.md-inline-img-dl .i {
  width: 12px;
  height: 12px;
}
</style>
