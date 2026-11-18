/**
 * 零依赖轻量多语言语法高亮分词器（输出纯结构化 Token Span，绝不拼接 HTML）。
 * 支持 TypeScript/JavaScript/Vue/HTML/CSS/JSON/Python/Bash/PowerShell/SQL/Go/Rust/YAML/Diff。
 */

export type HighlightTokenKind =
  | 'plain'
  | 'keyword'
  | 'string'
  | 'number'
  | 'comment'
  | 'type'
  | 'operator'
  | 'punct'
  | 'tag'
  | 'attr'
  | 'property'
  | 'diffAdd'
  | 'diffDel'
  | 'diffMeta'

export interface HighlightSpan {
  text: string
  kind: HighlightTokenKind
}

const LANG_ALIASES: Record<string, string> = {
  ts: 'ts',
  tsx: 'ts',
  typescript: 'ts',
  js: 'js',
  jsx: 'js',
  mjs: 'js',
  cjs: 'js',
  javascript: 'js',
  vue: 'vue',
  html: 'html',
  htm: 'html',
  xml: 'html',
  svg: 'html',
  css: 'css',
  scss: 'css',
  less: 'css',
  json: 'json',
  jsonc: 'json',
  py: 'python',
  python: 'python',
  sh: 'bash',
  bash: 'bash',
  zsh: 'bash',
  shell: 'bash',
  ps1: 'powershell',
  pwsh: 'powershell',
  powershell: 'powershell',
  sql: 'sql',
  go: 'go',
  golang: 'go',
  rs: 'rust',
  rust: 'rust',
  yaml: 'yaml',
  yml: 'yaml',
  diff: 'diff',
  patch: 'diff',
}

const KEYWORDS_BY_LANG: Record<string, Set<string>> = {
  ts: new Set([
    'import', 'export', 'from', 'as', 'default', 'const', 'let', 'var', 'function', 'return',
    'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'break', 'continue', 'try', 'catch',
    'finally', 'throw', 'async', 'await', 'new', 'class', 'extends', 'implements', 'interface',
    'type', 'enum', 'namespace', 'public', 'private', 'protected', 'readonly', 'static',
    'typeof', 'keyof', 'in', 'of', 'instanceof', 'void', 'null', 'undefined', 'true', 'false', 'this',
  ]),
  js: new Set([
    'import', 'export', 'from', 'as', 'default', 'const', 'let', 'var', 'function', 'return',
    'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'break', 'continue', 'try', 'catch',
    'finally', 'throw', 'async', 'await', 'new', 'class', 'extends', 'static', 'typeof', 'in',
    'of', 'instanceof', 'void', 'null', 'undefined', 'true', 'false', 'this',
  ]),
  python: new Set([
    'import', 'from', 'as', 'def', 'return', 'if', 'elif', 'else', 'for', 'while', 'break',
    'continue', 'pass', 'try', 'except', 'finally', 'raise', 'with', 'async', 'await', 'class',
    'lambda', 'yield', 'global', 'nonlocal', 'assert', 'del', 'in', 'is', 'not', 'and', 'or',
    'None', 'True', 'False', 'self',
  ]),
  bash: new Set([
    'if', 'then', 'elif', 'else', 'fi', 'for', 'do', 'done', 'while', 'until', 'case', 'esac',
    'in', 'function', 'return', 'export', 'local', 'readonly', 'set', 'unset', 'exit', 'true', 'false',
  ]),
  powershell: new Set([
    'function', 'param', 'begin', 'process', 'end', 'if', 'elseif', 'else', 'switch', 'for',
    'foreach', 'while', 'do', 'return', 'break', 'continue', 'try', 'catch', 'finally', 'throw',
    'true', 'false', 'null',
  ]),
  sql: new Set([
    'select', 'from', 'where', 'insert', 'into', 'values', 'update', 'set', 'delete', 'create',
    'table', 'alter', 'drop', 'index', 'join', 'inner', 'left', 'right', 'outer', 'on', 'group',
    'by', 'order', 'having', 'limit', 'offset', 'as', 'and', 'or', 'not', 'in', 'is', 'null',
    'primary', 'key', 'foreign', 'references', 'distinct', 'union', 'all', 'case', 'when', 'then', 'end',
  ]),
  go: new Set([
    'package', 'import', 'func', 'return', 'var', 'const', 'type', 'struct', 'interface', 'map',
    'chan', 'go', 'select', 'case', 'default', 'switch', 'if', 'else', 'for', 'range', 'break',
    'continue', 'defer', 'fallthrough', 'nil', 'true', 'false',
  ]),
  rust: new Set([
    'use', 'mod', 'pub', 'fn', 'let', 'mut', 'const', 'static', 'struct', 'enum', 'trait', 'impl',
    'type', 'where', 'for', 'in', 'loop', 'while', 'if', 'else', 'match', 'return', 'break',
    'continue', 'async', 'await', 'move', 'ref', 'self', 'Self', 'crate', 'super', 'true', 'false',
    'Some', 'None', 'Ok', 'Err',
  ]),
  css: new Set(['@import', '@media', '@keyframes', '@layer', '@supports', '!important', 'from', 'to']),
  yaml: new Set(['true', 'false', 'null', 'yes', 'no', 'on', 'off']),
}

export function normalizeLanguage(lang?: string): string {
  const cleaned = String(lang || '').trim().toLowerCase().replace(/^\./, '')
  if (!cleaned) return 'plain'
  return LANG_ALIASES[cleaned] || cleaned
}

export function inferLanguageFromPath(path?: string): string {
  const raw = String(path || '').trim()
  if (!raw) return 'plain'
  const lastDot = raw.lastIndexOf('.')
  if (lastDot < 0) return 'plain'
  return normalizeLanguage(raw.slice(lastDot + 1))
}

function pushSpan(out: HighlightSpan[], text: string, kind: HighlightTokenKind): void {
  if (!text) return
  const prev = out[out.length - 1]
  if (prev && prev.kind === kind) {
    prev.text += text
  } else {
    out.push({ text, kind })
  }
}

/** 扫描单行内容并返回合并后的结构化 Token Span。 */
function tokenizeLine(
  line: string,
  lang: string,
  state: { blockComment: 'slash' | 'html' | null }
): HighlightSpan[] {
  const spans: HighlightSpan[] = []
  if (!line) return spans

  if (lang === 'diff') {
    if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('@@') || line.startsWith('diff ')) {
      return [{ text: line, kind: 'diffMeta' }]
    }
    if (line.startsWith('+')) return [{ text: line, kind: 'diffAdd' }]
    if (line.startsWith('-')) return [{ text: line, kind: 'diffDel' }]
    return [{ text: line, kind: 'plain' }]
  }

  const keywords = KEYWORDS_BY_LANG[lang] || KEYWORDS_BY_LANG.ts
  const hashCommentLangs = new Set(['python', 'bash', 'powershell', 'yaml'])
  const dashCommentLangs = new Set(['sql'])
  const slashCommentLangs = new Set(['ts', 'js', 'go', 'rust', 'css', 'vue', 'json'])
  const xmlTagLangs = new Set(['html', 'vue'])

  let i = 0
  const n = line.length

  while (i < n) {
    if (state.blockComment === 'slash') {
      const close = line.indexOf('*/', i)
      if (close === -1) {
        pushSpan(spans, line.slice(i), 'comment')
        return spans
      }
      pushSpan(spans, line.slice(i, close + 2), 'comment')
      state.blockComment = null
      i = close + 2
      continue
    }

    if (state.blockComment === 'html') {
      const close = line.indexOf('-->', i)
      if (close === -1) {
        pushSpan(spans, line.slice(i), 'comment')
        return spans
      }
      pushSpan(spans, line.slice(i, close + 3), 'comment')
      state.blockComment = null
      i = close + 3
      continue
    }

    const ch = line[i]
    const next2 = line.slice(i, i + 2)
    const next4 = line.slice(i, i + 4)

    // 注释检测
    if (next4 === '<!--' && xmlTagLangs.has(lang)) {
      const close = line.indexOf('-->', i + 4)
      if (close === -1) {
        pushSpan(spans, line.slice(i), 'comment')
        state.blockComment = 'html'
        return spans
      }
      pushSpan(spans, line.slice(i, close + 3), 'comment')
      i = close + 3
      continue
    }

    if (next2 === '/*' && slashCommentLangs.has(lang)) {
      const close = line.indexOf('*/', i + 2)
      if (close === -1) {
        pushSpan(spans, line.slice(i), 'comment')
        state.blockComment = 'slash'
        return spans
      }
      pushSpan(spans, line.slice(i, close + 2), 'comment')
      i = close + 2
      continue
    }

    if (next2 === '//' && slashCommentLangs.has(lang)) {
      pushSpan(spans, line.slice(i), 'comment')
      return spans
    }

    if (ch === '#' && hashCommentLangs.has(lang)) {
      pushSpan(spans, line.slice(i), 'comment')
      return spans
    }

    if (next2 === '--' && dashCommentLangs.has(lang)) {
      pushSpan(spans, line.slice(i), 'comment')
      return spans
    }

    // 字符串常量
    if (ch === '"' || ch === "'" || ch === '`') {
      let j = i + 1
      while (j < n) {
        if (line[j] === '\\' && j + 1 < n) {
          j += 2
          continue
        }
        if (line[j] === ch) {
          j++
          break
        }
        j++
      }
      const lit = line.slice(i, j)
      if ((lang === 'json' || lang === 'yaml') && ch === '"' && /^\s*:/.test(line.slice(j))) {
        pushSpan(spans, lit, 'property')
      } else {
        pushSpan(spans, lit, 'string')
      }
      i = j
      continue
    }

    // HTML/Vue 标签
    if (ch === '<' && xmlTagLangs.has(lang)) {
      const tagMatch = /^<\/?[A-Za-z][\w:-]*/.exec(line.slice(i))
      if (tagMatch) {
        pushSpan(spans, tagMatch[0], 'tag')
        i += tagMatch[0].length
        continue
      }
    }

    // 数字常量（含 0x/float）
    if (/\d/.test(ch) && (i === 0 || !/[A-Za-z_$]/.test(line[i - 1]))) {
      const numMatch = /^(?:0x[0-9a-fA-F_]+|\d[\d_]*(?:\.[\d_]+)?(?:[eE][+-]?\d+)?)/.exec(line.slice(i))
      if (numMatch) {
        pushSpan(spans, numMatch[0], 'number')
        i += numMatch[0].length
        continue
      }
    }

    // CSS 十六进制颜色 / @rule / 属性
    if (lang === 'css' && ch === '@' && /^@[A-Za-z-]+/.test(line.slice(i))) {
      const atMatch = /^@[A-Za-z-]+/.exec(line.slice(i))!
      pushSpan(spans, atMatch[0], 'keyword')
      i += atMatch[0].length
      continue
    }

    // PowerShell 变量 $foo
    if (lang === 'powershell' && ch === '$' && /^\$[A-Za-z_][\w]*/.test(line.slice(i))) {
      const varMatch = /^\$[A-Za-z_][\w]*/.exec(line.slice(i))!
      pushSpan(spans, varMatch[0], 'property')
      i += varMatch[0].length
      continue
    }

    // 标识符 / 关键字 / 类型
    if (/[A-Za-z_$]/.test(ch)) {
      const idMatch = /^[A-Za-z_$][\w$-]*/.exec(line.slice(i))
      if (idMatch) {
        const word = idMatch[0]
        const tail = line.slice(i + word.length)
        if (lang === 'sql' && keywords.has(word.toLowerCase())) {
          pushSpan(spans, word, 'keyword')
        } else if (keywords.has(word)) {
          pushSpan(spans, word, 'keyword')
        } else if (lang === 'yaml' && /^\s*:/.test(tail)) {
          pushSpan(spans, word, 'property')
        } else if ((lang === 'css' || xmlTagLangs.has(lang)) && /^\s*[:=]/.test(tail)) {
          pushSpan(spans, word, 'attr')
        } else if (/^[A-Z][A-Za-z0-9_]*$/.test(word) && word.length > 1) {
          pushSpan(spans, word, 'type')
        } else if (lang === 'ts' || lang === 'js' || lang === 'vue') {
          if (/^\s*:/.test(tail) && spans.length > 0 && spans[spans.length - 1].kind === 'plain') {
            pushSpan(spans, word, 'property')
          } else {
            pushSpan(spans, word, 'plain')
          }
        } else {
          pushSpan(spans, word, 'plain')
        }
        i += word.length
        continue
      }
    }

    if (/[+\-*/%=&|!<>?:~^]/.test(ch)) {
      pushSpan(spans, ch, 'operator')
      i++
      continue
    }

    if (/[()[\]{}.,;]/.test(ch)) {
      pushSpan(spans, ch, 'punct')
      i++
      continue
    }

    pushSpan(spans, ch, 'plain')
    i++
  }

  return spans
}

/** 高亮单行文本（不保留跨行块注释状态）。 */
export function highlightCodeLine(line: string, lang?: string): HighlightSpan[] {
  return tokenizeLine(line, normalizeLanguage(lang), { blockComment: null })
}

/** 高亮多行代码块，跨行追踪块注释与标签注释状态。 */
export function highlightCode(code: string, lang?: string): HighlightSpan[][] {
  const norm = normalizeLanguage(lang)
  const lines = String(code ?? '').replace(/\r\n/g, '\n').split('\n')
  const state: { blockComment: 'slash' | 'html' | null } = { blockComment: null }
  return lines.map((line) => tokenizeLine(line, norm, state))
}
