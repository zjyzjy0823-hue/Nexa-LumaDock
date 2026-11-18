/**
 * 将会话记录导出为自包含、静态安全的独立 HTML 报告（对全部用户及模型文本严格 HTML 转义，不含任何脚本）。
 */

import type { ChatMessage, ChatSession } from '../types/fleet'
import { extractMessageParts } from './chatHelpers.ts'
import { parseMarkdownBlocks } from './markdownBlocks.ts'
import { highlightCode } from './syntaxHighlight.ts'

function escHtml(raw: string): string {
  return String(raw ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderCodeBlockHtml(code: string, lang?: string): string {
  const lines = highlightCode(code, lang)
  const inner = lines
    .map(spans =>
      spans.map(sp => `<span class="tok-${escHtml(sp.kind)}">${escHtml(sp.text)}</span>`).join(''),
    )
    .join('\n')
  return `<div class="code-wrap"><div class="code-lang">${escHtml(lang || 'text')}</div><pre><code>${inner}</code></pre></div>`
}

function renderSimpleMarkdownHtml(text: string): string {
  const blocks = parseMarkdownBlocks(text)
  const parts: string[] = []
  for (const b of blocks) {
    if (b.type === 'code') {
      parts.push(renderCodeBlockHtml(b.code, b.lang))
    } else if (b.type === 'heading') {
      const txt = b.inlines.map(t => escHtml(t.text)).join('')
      parts.push(`<h${b.level}>${txt}</h${b.level}>`)
    } else if (b.type === 'list') {
      const tag = b.ordered ? 'ol' : 'ul'
      const lis = b.items.map(it => `<li>${it.map(t => escHtml(t.text)).join('')}</li>`).join('')
      parts.push(`<${tag}>${lis}</${tag}>`)
    } else if (b.type === 'blockquote') {
      const lines = b.lines.map(line => `<p>${line.map(t => escHtml(t.text)).join('')}</p>`).join('')
      parts.push(`<blockquote>${lines}</blockquote>`)
    } else if (b.type === 'hr') {
      parts.push('<hr/>')
    } else if (b.type === 'table') {
      const ths = b.headers.map(c => `<th>${c.map(t => escHtml(t.text)).join('')}</th>`).join('')
      const trs = b.rows.map(r => `<tr>${r.map(c => `<td>${c.map(t => escHtml(t.text)).join('')}</td>`).join('')}</tr>`).join('')
      parts.push(`<table><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table>`)
    } else {
      const body = b.lines
        .map(line =>
          line
            .map(t => {
              if (t.type === 'code') return `<code>${escHtml(t.text)}</code>`
              if (t.type === 'bold') return `<strong>${escHtml(t.text)}</strong>`
              if (t.type === 'italic') return `<em>${escHtml(t.text)}</em>`
              if (t.type === 'link') return `<a href="${escHtml(t.href)}" target="_blank" rel="noopener noreferrer">${escHtml(t.text)}</a>`
              return escHtml(t.text)
            })
            .join(''),
        )
        .join('<br/>')
      parts.push(`<p>${body}</p>`)
    }
  }
  return parts.join('\n')
}

export function buildSessionHtmlReport(
  session: ChatSession,
  messages: ChatMessage[],
  nodeName?: string,
): string {
  const title = escHtml(session.title || session.sessionId)
  const msgHtml = messages
    .map(m => {
      if (m.role === 'system') {
        return `<div class="sys">${escHtml(m.text)}</div>`
      }
      if (m.role === 'user') {
        return `<article class="msg user"><div class="bubble">${escHtml(m.text).replace(/\n/g, '<br/>')}</div></article>`
      }
      const toolMap = new Map((m.toolCalls ?? []).map(t => [t.callId || t.id, t]))
      const bodyHtml = extractMessageParts(m)
        .map(p => {
          if (p.type === 'thought') {
            return `<details class="fold"><summary>思考过程 (${p.text.length} 字)</summary><div class="fold-body">${escHtml(p.text).replace(/\n/g, '<br/>')}</div></details>`
          }
          if (p.type === 'tool') {
            const tc = toolMap.get(p.callId)
            if (!tc) return ''
            const st = tc.status === 'error' ? 'FAILED' : tc.status === 'running' ? 'RUNNING' : 'OK'
            const out = tc.output ? `<pre class="tool-out">${escHtml(tc.output)}</pre>` : ''
            return `<details class="fold"><summary>[${st}] ${escHtml(tc.name)} ${escHtml(tc.title || '')}</summary>${out}</details>`
          }
          return renderSimpleMarkdownHtml(p.text)
        })
        .join('\n')
      return `<article class="msg agent"><div class="role">${escHtml(m.provider)}</div><div class="bubble">${bodyHtml}</div></article>`
    })
    .join('\n')

  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>${title} — Studiolo 会话归档报告</title>
<style>
  :root { color-scheme: light dark; --bg: #f8fafc; --card: #ffffff; --text: #0f172a; --muted: #64748b; --line: #e2e8f0; --accent: #2563eb; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #0f172a; --card: #1e293b; --text: #f1f5f9; --muted: #94a3b8; --line: #334155; --accent: #60a5fa; }
  }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 28px 16px; background: var(--bg); color: var(--text); font: 14px/1.6 system-ui, -apple-system, sans-serif; }
  main { max-width: 820px; margin: 0 auto; display: grid; gap: 16px; }
  header { padding: 16px 20px; border: 1px solid var(--line); border-radius: 12px; background: var(--card); }
  header h1 { margin: 0 0 8px; font-size: 18px; }
  .meta { color: var(--muted); font-size: 12px; display: flex; flex-wrap: wrap; gap: 12px; }
  .msg { display: flex; flex-direction: column; gap: 4px; }
  .msg.user { align-items: flex-end; }
  .msg.user .bubble { background: var(--accent); color: #fff; padding: 10px 14px; border-radius: 14px 14px 4px 14px; max-width: 82%; }
  .msg.agent .bubble { background: var(--card); border: 1px solid var(--line); padding: 14px 16px; border-radius: 12px; }
  .role { font-size: 11px; font-weight: 600; color: var(--muted); text-transform: uppercase; }
  .sys { text-align: center; color: var(--muted); font-size: 12px; padding: 4px; }
  .fold { margin: 6px 0; border: 1px solid var(--line); border-radius: 8px; padding: 6px 10px; }
  .fold summary { cursor: pointer; font-weight: 600; font-size: 12.5px; }
  .fold-body, .tool-out { margin-top: 6px; font-size: 12px; color: var(--muted); white-space: pre-wrap; word-break: break-word; }
  .code-wrap { margin: 8px 0; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
  .code-lang { padding: 4px 10px; font-size: 11px; color: var(--muted); border-bottom: 1px solid var(--line); }
  pre { margin: 0; padding: 10px 12px; overflow-x: auto; font: 12px/1.5 ui-monospace, Consolas, monospace; }
  table { border-collapse: collapse; width: 100%; margin: 8px 0; }
  th, td { border: 1px solid var(--line); padding: 6px 8px; text-align: left; }
  .tok-keyword { color: #a855f7; } .tok-string { color: #16a34a; } .tok-number { color: #d97706; } .tok-comment { color: #64748b; font-style: italic; }
</style>
</head>
<body>
<main>
  <header>
    <h1>${title}</h1>
    <div class="meta">
      <span>节点：${escHtml(nodeName || session.nodeId)}</span>
      <span>运行时：${escHtml(session.provider)}</span>
      <span>目录：${escHtml(session.worktreePath || session.cwd || '-')}</span>
      <span>导出时间：${escHtml(new Date().toISOString())}</span>
    </div>
  </header>
  ${msgHtml}
</main>
</body>
</html>`
}
