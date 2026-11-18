<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { parseMarkdownBlocks } from '../../services/markdownBlocks'
import OpusIcon from '../ui/OpusIcon.vue'
import MarkdownInlineText from './MarkdownInlineText.vue'

const props = defineProps<{
  text: string
  streaming?: boolean
}>()

const blocks = computed(() => parseMarkdownBlocks(props.text))
const copiedBlockIdx = ref<number | null>(null)
let copyResetTimer: ReturnType<typeof setTimeout> | null = null

async function copyCodeBlock(code: string, idx: number) {
  if (!navigator.clipboard?.writeText) return
  try {
    await navigator.clipboard.writeText(code)
    copiedBlockIdx.value = idx
    if (copyResetTimer) clearTimeout(copyResetTimer)
    copyResetTimer = setTimeout(() => {
      copiedBlockIdx.value = null
      copyResetTimer = null
    }, 1500)
  } catch {
    // 忽略无剪贴板权限错误
  }
}

onUnmounted(() => {
  if (copyResetTimer) clearTimeout(copyResetTimer)
})
</script>

<template>
  <div class="md-root" :class="{ 'is-streaming': streaming }">
    <template v-for="(block, bIdx) in blocks" :key="`blk-${bIdx}-${block.type}`">
      <component
        :is="`h${block.level}`"
        v-if="block.type === 'heading'"
        class="md-heading"
        :class="`md-h${block.level}`"
      >
        <MarkdownInlineText :tokens="block.inlines" />
      </component>

      <div v-else-if="block.type === 'code'" class="md-code-wrap">
        <div class="md-code-head">
          <span class="md-code-lang">{{ block.lang || 'code' }}</span>
          <button
            type="button"
            class="md-code-copy"
            :class="{ 'is-copied': copiedBlockIdx === bIdx }"
            :aria-label="copiedBlockIdx === bIdx ? '已复制代码' : '复制代码'"
            @click="copyCodeBlock(block.code, bIdx)"
          >
            <OpusIcon :name="copiedBlockIdx === bIdx ? 'check' : 'copy'" />
            <span>{{ copiedBlockIdx === bIdx ? '已复制' : '复制' }}</span>
          </button>
        </div>
        <pre class="md-code-pre"><code>{{ block.code }}</code></pre>
      </div>

      <blockquote v-else-if="block.type === 'blockquote'" class="md-quote">
        <p v-for="(line, lIdx) in block.lines" :key="`ql-${lIdx}`">
          <MarkdownInlineText :tokens="line" />
        </p>
      </blockquote>

      <component :is="block.ordered ? 'ol' : 'ul'" v-else-if="block.type === 'list'" class="md-list">
        <li v-for="(item, lIdx) in block.items" :key="`li-${lIdx}`">
          <MarkdownInlineText :tokens="item" />
        </li>
      </component>

      <div v-else-if="block.type === 'table'" class="md-table-scroll">
        <table class="md-table">
          <thead>
            <tr>
              <th v-for="(cell, cIdx) in block.headers" :key="`th-${cIdx}`">
                <MarkdownInlineText :tokens="cell" />
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, rIdx) in block.rows" :key="`tr-${rIdx}`">
              <td v-for="(cell, cIdx) in row" :key="`td-${rIdx}-${cIdx}`">
                <MarkdownInlineText :tokens="cell" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <hr v-else-if="block.type === 'hr'" class="md-hr" />

      <p v-else class="md-para">
        <template v-for="(line, lIdx) in block.lines" :key="`pl-${lIdx}`">
          <br v-if="lIdx > 0" />
          <MarkdownInlineText :tokens="line" />
        </template>
      </p>
    </template>
  </div>
</template>

<style scoped>
.md-root {
  display: grid;
  gap: 8px;
  min-width: 0;
  color: inherit;
  line-height: 1.62;
  word-break: break-word;
}
.md-para,
.md-heading,
.md-quote p {
  margin: 0;
}
.md-h1 { font-size: 16px; font-weight: 680; line-height: 1.35; }
.md-h2 { font-size: 14.5px; font-weight: 650; line-height: 1.38; }
.md-h3,
.md-h4 { font-size: 13.5px; font-weight: 620; line-height: 1.4; }
.md-list {
  margin: 0;
  padding-left: 1.35em;
  display: grid;
  gap: 3px;
}
.md-quote {
  margin: 0;
  padding: 4px 10px;
  border-left: 3px solid var(--line-strong);
  border-radius: 0 6px 6px 0;
  background: var(--surface-2);
  color: var(--text-2);
}
.md-hr {
  width: 100%;
  height: 1px;
  margin: 2px 0;
  border: 0;
  background: var(--line);
}
:deep(.md-inline-code) {
  padding: 1px 5px;
  border-radius: 5px;
  background: var(--surface-3);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: .88em;
}
:deep(.md-link) {
  color: var(--accent);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.md-code-wrap {
  min-width: 0;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface-2);
  overflow: hidden;
}
.md-code-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 5px 10px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-3);
}
.md-code-lang {
  font-size: 11px;
  font-weight: 550;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: var(--text-3);
  text-transform: lowercase;
}
.md-code-copy {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border-radius: 5px;
  font-size: 11px;
  color: var(--text-2);
  cursor: pointer;
  transition: background-color var(--dur-1), color var(--dur-1);
}
.md-code-copy:hover {
  background: var(--solid);
  color: var(--text);
}
.md-code-copy.is-copied {
  color: var(--ok);
}
.md-code-copy .i {
  width: 12px;
  height: 12px;
}
.md-code-pre {
  margin: 0;
  padding: 10px 12px;
  overflow-x: auto;
  font-size: 12px;
  line-height: 1.5;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: var(--text);
  scrollbar-width: thin;
}
.md-table-scroll {
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 8px;
}
.md-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.md-table th,
.md-table td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}
.md-table th {
  background: var(--surface-2);
  font-weight: 600;
}
.md-table tbody tr:last-child td {
  border-bottom: 0;
}
</style>
