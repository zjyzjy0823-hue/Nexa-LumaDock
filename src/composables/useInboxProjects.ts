import { ref, watch, type Ref } from 'vue'

export interface InboxProjectDirectory {
  nodeId: string
  cwd: string
}

export function useInboxProjects(scope: Readonly<Ref<string>>) {
  const directories = ref<InboxProjectDirectory[]>([])
  const storageKey = () => scope.value ? `studiolo:fleet:inbox-projects:${scope.value}` : ''

  function read(): InboxProjectDirectory[] {
    const key = storageKey()
    if (!key) return []
    try {
      const rows: unknown = JSON.parse(localStorage.getItem(key) ?? '[]')
      return Array.isArray(rows) ? rows.filter(row => typeof row?.nodeId === 'string' && typeof row?.cwd === 'string' && row.cwd) : []
    } catch {
      return []
    }
  }

  watch(scope, () => { directories.value = read() }, { immediate: true, flush: 'sync' })

  function save(directory: InboxProjectDirectory) {
    const next = [...read(), ...directories.value].filter(entry =>
      entry.nodeId !== directory.nodeId || entry.cwd !== directory.cwd,
    )
    const unique = new Map(next.map(entry => [JSON.stringify([entry.nodeId, entry.cwd]), entry]))
    directories.value = [...unique.values(), directory]
    try {
      const key = storageKey()
      if (!key) return false
      localStorage.setItem(key, JSON.stringify(directories.value))
      return true
    } catch {
      return false
    }
  }

  return { directories, save }
}
