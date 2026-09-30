type Shortcut = Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'altKey' | 'metaKey' | 'isComposing'>

/** Keep application/editing shortcuts while suppressing WebView browser commands. */
export function shouldBlockBrowserShortcut(event: Shortcut): boolean {
  if (event.isComposing || event.altKey || event.metaKey) return false
  const key = event.key.toLowerCase()
  return key === 'f5' || (event.ctrlKey && ['r', 'p', 's', 'l', 'u'].includes(key))
}

export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  if (target.closest('input, textarea')) return true
  return target.closest<HTMLElement>('[contenteditable]')?.isContentEditable ?? false
}

export function shouldSuppressDrag(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  if (target.closest('[data-allow-drag]') || isEditableTarget(target)) return false
  return target.closest('img, a, svg') !== null
}

/** Desktop only. Disable all native menus; keyboard clipboard/editing remains native. */
export function installDesktopInteractions(doc: Document = document): () => void {
  const contextmenu = (event: MouseEvent) => event.preventDefault()
  const keydown = (event: KeyboardEvent) => {
    if (shouldBlockBrowserShortcut(event)) event.preventDefault()
  }
  const dragstart = (event: DragEvent) => {
    if (shouldSuppressDrag(event.target)) event.preventDefault()
  }
  doc.addEventListener('contextmenu', contextmenu, true)
  doc.addEventListener('keydown', keydown, true)
  doc.addEventListener('dragstart', dragstart, true)
  return () => {
    doc.removeEventListener('contextmenu', contextmenu, true)
    doc.removeEventListener('keydown', keydown, true)
    doc.removeEventListener('dragstart', dragstart, true)
  }
}

export function scrollPageToTop(behavior: ScrollBehavior = 'instant'): void {
  if (document.documentElement.classList.contains('nexa-desktop')) {
    document.querySelector<HTMLElement>('[data-desktop-scroll]')?.scrollTo({ top: 0, behavior })
  } else {
    window.scrollTo({ top: 0, behavior })
  }
}
