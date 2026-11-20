<script setup lang="ts">
import { computed, onUnmounted, reactive, ref } from 'vue'
import { parseCodeBlockLang } from '../../services/chatHelpers'
import { parseMermaidDiagram, type DiagramRenderModel } from '../../services/diagramBuilder'
import { parseMarkdownBlocks } from '../../services/markdownBlocks'
import { highlightCode, type HighlightSpan } from '../../services/syntaxHighlight'
import OpusIcon from '../ui/OpusIcon.vue'
import MarkdownInlineText from './MarkdownInlineText.vue'

const props = defineProps<{
  text: string
  streaming?: boolean
  knownFiles?: Set<string>
}>()

const emit = defineEmits<{
  openFile: [path: string, line?: number]
}>()

const CODE_COLLAPSE_THRESHOLD = 35

const blocks = computed(() => parseMarkdownBlocks(props.text))
const copiedBlockIdx = ref<number | null>(null)
const blockViewMode = reactive<Record<number, 'preview' | 'code'>>({})
const expandedCodeBlocks = reactive<Record<number, boolean>>({})
const wrappedCodeBlocks = reactive<Record<number, boolean>>({})
let copyResetTimer: ReturnType<typeof setTimeout> | null = null

const codeLinesByBlock = computed<Record<number, HighlightSpan[][]>>(() => {
  const out: Record<number, HighlightSpan[][]> = {}
  blocks.value.forEach((blk, idx) => {
    if (blk.type === 'code') {
      const parsed = parseCodeBlockLang(blk.lang)
      out[idx] = highlightCode(blk.code, parsed.lang)
    }
  })
  return out
})

function toggleCodeWrap(idx: number) {
  wrappedCodeBlocks[idx] = !wrappedCodeBlocks[idx]
}

function isLongCodeBlock(idx: number): boolean {
  return (codeLinesByBlock.value[idx]?.length ?? 0) > CODE_COLLAPSE_THRESHOLD
}

function isCodeCollapsed(idx: number): boolean {
  return !props.streaming && isLongCodeBlock(idx) && !expandedCodeBlocks[idx]
}

function toggleCodeExpand(idx: number) {
  expandedCodeBlocks[idx] = !expandedCodeBlocks[idx]
}

function visibleCodeLines(idx: number): HighlightSpan[][] {
  const lines = codeLinesByBlock.value[idx] ?? []
  if (isCodeCollapsed(idx)) {
    return lines.slice(0, CODE_COLLAPSE_THRESHOLD)
  }
  return lines
}

function getDiagram(code: string, lang?: string): DiagramRenderModel | null {
  if ((lang || '').trim().toLowerCase() !== 'mermaid') return null
  return parseMermaidDiagram(code)
}

function isSandboxableWebCode(lang?: string): boolean {
  const l = (lang || '').trim().toLowerCase()
  return l === 'html' || l === 'htm' || l === 'svg'
}

function getEffectiveView(idx: number, lang?: string, code?: string): 'preview' | 'code' {
  if (blockViewMode[idx]) return blockViewMode[idx]
  if (lang?.toLowerCase() === 'mermaid' && getDiagram(code || '', lang)) return 'preview'
  return 'code'
}

function setBlockView(idx: number, mode: 'preview' | 'code') {
  blockViewMode[idx] = mode
}

function wrapSandboxDoc(code: string, lang?: string): string {
  const l = (lang || '').trim().toLowerCase()
  const body = l === 'svg' ? `<div style="display:grid;place-items:center;min-height:100vh">${code}</div>` : code
  return `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;padding:12px;font-family:system-ui,-apple-system,sans-serif;background:#fff;color:#0f172a;}</style></head><body>${body}</body></html>`
}

function forwardOpenFile(path: string, line?: number) {
  emit('openFile', path, line)
}

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
        <MarkdownInlineText :tokens="block.inlines" :known-files="knownFiles" @open-file="forwardOpenFile" />
      </component>

      <div v-else-if="block.type === 'code'" class="md-code-wrap">
        <div class="md-code-head">
          <div class="md-code-meta">
            <span class="md-code-lang">{{ parseCodeBlockLang(block.lang).lang || 'code' }}</span>
            <button
              v-if="parseCodeBlockLang(block.lang).filePath"
              type="button"
              class="md-code-file-btn"
              :title="`在右侧打开 ${parseCodeBlockLang(block.lang).filePath}`"
              @click="forwardOpenFile(parseCodeBlockLang(block.lang).filePath!)"
            >
              <OpusIcon name="file" />
              <span>{{ parseCodeBlockLang(block.lang).filePath }}</span>
            </button>
          </div>
          <div class="md-code-tools">
            <div v-if="getDiagram(block.code, block.lang)" class="md-seg">
              <button
                type="button"
                class="md-seg-btn"
                :class="{ 'is-active': getEffectiveView(bIdx, block.lang, block.code) === 'preview' }"
                @click="setBlockView(bIdx, 'preview')"
              >
                图表
              </button>
              <button
                type="button"
                class="md-seg-btn"
                :class="{ 'is-active': getEffectiveView(bIdx, block.lang, block.code) === 'code' }"
                @click="setBlockView(bIdx, 'code')"
              >
                源码
              </button>
            </div>
            <div v-else-if="isSandboxableWebCode(block.lang)" class="md-seg">
              <button
                type="button"
                class="md-seg-btn"
                :class="{ 'is-active': getEffectiveView(bIdx, block.lang, block.code) === 'code' }"
                @click="setBlockView(bIdx, 'code')"
              >
                源码
              </button>
              <button
                type="button"
                class="md-seg-btn"
                :class="{ 'is-active': getEffectiveView(bIdx, block.lang, block.code) === 'preview' }"
                @click="setBlockView(bIdx, 'preview')"
              >
                沙箱预览
              </button>
            </div>
            <button
              v-if="getEffectiveView(bIdx, block.lang, block.code) === 'code'"
              type="button"
              class="md-code-copy"
              :class="{ 'is-wrapped': wrappedCodeBlocks[bIdx] }"
              :title="wrappedCodeBlocks[bIdx] ? '取消自动换行' : '开启代码自动换行'"
              @click="toggleCodeWrap(bIdx)"
            >
              <span>{{ wrappedCodeBlocks[bIdx] ? '不换行' : '折行' }}</span>
            </button>
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
        </div>

        <!-- 声明式 Mermaid 矢量流程图/时序图 -->
        <div
          v-if="getDiagram(block.code, block.lang) && getEffectiveView(bIdx, block.lang, block.code) === 'preview'"
          class="md-diagram-box"
        >
          <svg
            :viewBox="`0 0 ${getDiagram(block.code, block.lang)!.width} ${getDiagram(block.code, block.lang)!.height}`"
            class="md-diagram-svg"
            role="img"
            aria-label="Mermaid 图表可视化"
          >
            <defs>
              <marker :id="`md-arrow-${bIdx}`" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 1 L 10 5 L 0 9 z" fill="currentColor" />
              </marker>
            </defs>
            <template v-if="getDiagram(block.code, block.lang)!.kind === 'flowchart'">
              <g v-for="(edge, eIdx) in getDiagram(block.code, block.lang)!.edges" :key="`e-${eIdx}`" class="md-dia-edge">
                <path
                  :d="edge.d"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.5"
                  :stroke-dasharray="edge.dashed ? '4 3' : undefined"
                  :marker-end="`url(#md-arrow-${bIdx})`"
                />
                <text v-if="edge.label" :x="edge.labelX" :y="edge.labelY" text-anchor="middle" class="md-dia-elbl">
                  {{ edge.label }}
                </text>
              </g>
              <g v-for="node in getDiagram(block.code, block.lang)!.nodes" :key="node.id" class="md-dia-node">
                <rect
                  :x="node.x"
                  :y="node.y"
                  :width="node.width"
                  :height="node.height"
                  :rx="node.shape === 'round' ? 18 : 6"
                  class="md-dia-box"
                />
                <text :x="node.x + node.width / 2" :y="node.y + node.height / 2 + 4" text-anchor="middle" class="md-dia-nlbl">
                  {{ node.label }}
                </text>
              </g>
            </template>
            <template v-else>
              <g v-for="ll in getDiagram(block.code, block.lang)!.lifelines" :key="ll.id">
                <rect :x="ll.x - 48" y="16" width="96" height="32" rx="6" class="md-dia-box" />
                <text :x="ll.x" y="36" text-anchor="middle" class="md-dia-nlbl">{{ ll.label }}</text>
                <line :x1="ll.x" :y1="ll.topY" :x2="ll.x" :y2="ll.bottomY" stroke="currentColor" stroke-dasharray="4 4" opacity="0.45" />
              </g>
              <g v-for="(msg, mIdx) in getDiagram(block.code, block.lang)!.messages" :key="`m-${mIdx}`" class="md-dia-edge">
                <line
                  :x1="msg.fromX"
                  :y1="msg.y"
                  :x2="msg.toX"
                  :y2="msg.y"
                  stroke="currentColor"
                  stroke-width="1.5"
                  :stroke-dasharray="msg.dashed ? '4 3' : undefined"
                  :marker-end="`url(#md-arrow-${bIdx})`"
                />
                <text :x="(msg.fromX + msg.toX) / 2" :y="msg.y - 6" text-anchor="middle" class="md-dia-elbl">
                  {{ msg.label }}
                </text>
              </g>
            </template>
          </svg>
        </div>

        <!-- 隔离沙箱 iframe 预览（禁止 allow-same-origin） -->
        <iframe
          v-else-if="isSandboxableWebCode(block.lang) && getEffectiveView(bIdx, block.lang, block.code) === 'preview'"
          class="md-sandbox-frame"
          sandbox="allow-scripts"
          :srcdoc="wrapSandboxDoc(block.code, block.lang)"
          title="HTML/SVG 安全沙箱预览"
        />

        <!-- 语法高亮代码展示（无 v-html，超 35 行自动折叠） -->
        <template v-else>
          <pre class="md-code-pre" :class="{ 'is-collapsed': isCodeCollapsed(bIdx), 'is-wrapped': wrappedCodeBlocks[bIdx] }"><code><span v-for="(lineSpans, lIdx) in visibleCodeLines(bIdx)" :key="lIdx" class="md-code-line"><template v-if="lineSpans.length"><span v-for="(sp, sIdx) in lineSpans" :key="sIdx" :class="`tok-${sp.kind}`">{{ sp.text }}</span></template><template v-else>&#10;</template>{{ lIdx < visibleCodeLines(bIdx).length - 1 ? '\n' : '' }}</span></code></pre>
          <div v-if="isLongCodeBlock(bIdx)" class="md-code-fold-bar">
            <button
              type="button"
              class="md-code-fold-btn"
              @click="toggleCodeExpand(bIdx)"
            >
              <OpusIcon :name="expandedCodeBlocks[bIdx] ? 'chevD' : 'chevR'" />
              <span>
                {{
                  expandedCodeBlocks[bIdx]
                    ? `收起代码（共 ${codeLinesByBlock[bIdx]?.length ?? 0} 行）`
                    : `展开全部 ${codeLinesByBlock[bIdx]?.length ?? 0} 行（已折叠 ${(codeLinesByBlock[bIdx]?.length ?? 0) - CODE_COLLAPSE_THRESHOLD} 行）`
                }}
              </span>
            </button>
          </div>
        </template>
      </div>

      <blockquote v-else-if="block.type === 'blockquote'" class="md-quote">
        <p v-for="(line, lIdx) in block.lines" :key="`ql-${lIdx}`">
          <MarkdownInlineText :tokens="line" :known-files="knownFiles" @open-file="forwardOpenFile" />
        </p>
      </blockquote>

      <component :is="block.ordered ? 'ol' : 'ul'" v-else-if="block.type === 'list'" class="md-list">
        <li v-for="(item, lIdx) in block.items" :key="`li-${lIdx}`">
          <MarkdownInlineText :tokens="item" :known-files="knownFiles" @open-file="forwardOpenFile" />
        </li>
      </component>

      <div v-else-if="block.type === 'table'" class="md-table-scroll">
        <table class="md-table">
          <thead>
            <tr>
              <th v-for="(cell, cIdx) in block.headers" :key="`th-${cIdx}`">
                <MarkdownInlineText :tokens="cell" :known-files="knownFiles" @open-file="forwardOpenFile" />
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, rIdx) in block.rows" :key="`tr-${rIdx}`">
              <td v-for="(cell, cIdx) in row" :key="`td-${rIdx}-${cIdx}`">
                <MarkdownInlineText :tokens="cell" :known-files="knownFiles" @open-file="forwardOpenFile" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <hr v-else-if="block.type === 'hr'" class="md-hr" />

      <p v-else class="md-para">
        <template v-for="(line, lIdx) in block.lines" :key="`pl-${lIdx}`">
          <br v-if="lIdx > 0" />
          <MarkdownInlineText :tokens="line" :known-files="knownFiles" @open-file="forwardOpenFile" />
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
.md-code-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.md-code-file-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 6px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--solid);
  color: var(--accent);
  font-family: var(--mono);
  font-size: 11px;
  cursor: pointer;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.md-code-file-btn .i { width: 11px; height: 11px; flex: none; }
.md-code-file-btn:hover { background: var(--accent-soft); }
.md-code-pre.is-wrapped {
  white-space: pre-wrap;
  word-break: break-word;
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
.md-code-copy.is-wrapped {
  color: var(--accent);
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
.md-code-tools {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.md-seg {
  display: inline-flex;
  padding: 1px;
  border-radius: 6px;
  background: var(--surface-2);
  border: 1px solid var(--line);
}
.md-seg-btn {
  padding: 1px 6px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--text-3);
  font-size: 10.5px;
  cursor: pointer;
}
.md-seg-btn.is-active {
  background: var(--solid);
  color: var(--text);
  font-weight: 500;
}
.md-diagram-box {
  padding: 10px;
  overflow-x: auto;
  background: var(--solid);
}
.md-diagram-svg {
  display: block;
  width: 100%;
  max-height: 320px;
  color: var(--text-2);
}
.md-dia-box {
  fill: var(--surface-2);
  stroke: var(--accent-line);
  stroke-width: 1.5;
}
.md-dia-nlbl {
  fill: var(--text);
  font-size: 11.5px;
  font-weight: 500;
}
.md-dia-elbl {
  fill: var(--text-3);
  font-size: 10px;
}
.md-sandbox-frame {
  display: block;
  width: 100%;
  height: 240px;
  border: 0;
  background: #fff;
}
.md-code-fold-bar {
  display: flex;
  justify-content: center;
  border-top: 1px solid var(--line);
  background: var(--surface-1);
}
.md-code-fold-btn {
  width: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 5px 10px;
  border: 0;
  background: transparent;
  color: var(--accent);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
}
.md-code-fold-btn:hover { background: var(--surface-2); }
.md-code-fold-btn .i { width: 12px; height: 12px; }
.tok-keyword { color: var(--tok-keyword, #9333ea); font-weight: 500; }
.tok-string { color: var(--tok-string, #15803d); }
.tok-number { color: var(--tok-number, #b45309); }
.tok-comment { color: var(--tok-comment, #64748b); font-style: italic; }
.tok-type { color: var(--tok-type, #0369a1); }
.tok-operator { color: var(--tok-operator, #475569); }
.tok-punct { color: var(--tok-punct, #64748b); }
.tok-tag { color: var(--tok-tag, #be123c); }
.tok-attr { color: var(--tok-attr, #0f766e); }
.tok-property { color: var(--tok-property, #1d4ed8); }
.tok-diffAdd { color: var(--tok-diffAdd, var(--ok)); }
.tok-diffDel { color: var(--tok-diffDel, var(--warn)); }
.tok-diffMeta { color: var(--tok-diffMeta, var(--accent)); font-weight: 600; }
</style>
