import test from 'node:test'
import assert from 'node:assert/strict'
import { shouldBlockBrowserShortcut } from '../src/desktop/desktopInteractions.ts'

const key = (value, modifiers = {}) => ({ key: value, ctrlKey: false, altKey: false, metaKey: false, isComposing: false, ...modifiers })
test('browser refresh, print, save, address and source shortcuts are blocked', () => {
  assert.equal(shouldBlockBrowserShortcut(key('F5')), true)
  for (const value of ['r', 'R', 'p', 's', 'l', 'u']) {
    assert.equal(shouldBlockBrowserShortcut(key(value, { ctrlKey: true })), true, value)
  }
  // Shift does not affect the decision: Ctrl+Shift+R uses the same browser filter.
})
test('clipboard, editing, Nexa search and ordinary keys remain available', () => {
  for (const value of ['c', 'v', 'x', 'a', 'z', 'y', 'k', 'Tab', 'Escape', 'ArrowLeft']) {
    assert.equal(shouldBlockBrowserShortcut(key(value, { ctrlKey: true })), false, value)
  }
  for (const value of ['r', 'p', 's', 'l', 'u']) assert.equal(shouldBlockBrowserShortcut(key(value)), false)
})
test('system/Alt shortcuts and IME composition are not intercepted', () => {
  for (const modifiers of [{ altKey: true }, { metaKey: true }, { isComposing: true }]) {
    assert.equal(shouldBlockBrowserShortcut(key('r', { ctrlKey: true, ...modifiers })), false)
    assert.equal(shouldBlockBrowserShortcut(key('F5', modifiers)), false)
  }
})
test('macOS Command browser shortcuts are blocked, including Shift+R', () => {
  for (const value of ['r', 'R', 'p', 's', 'l', 'u']) {
    assert.equal(shouldBlockBrowserShortcut(key(value, { metaKey: true }), 'macos'), true, value)
    assert.equal(shouldBlockBrowserShortcut(key(value, { metaKey: true, shiftKey: true }), 'macos'), true, value)
    assert.equal(shouldBlockBrowserShortcut(key(value, { ctrlKey: true }), 'macos'), false, value)
  }
})
test('macOS clipboard, undo, redo, search, Quit and IME remain native', () => {
  for (const value of ['c', 'v', 'x', 'a', 'z', 'k', 'q']) {
    for (const shiftKey of [false, true]) {
      assert.equal(shouldBlockBrowserShortcut(key(value, { metaKey: true, shiftKey }), 'macos'), false, value)
    }
  }
  for (const modifiers of [{ altKey: true }, { isComposing: true }, { ctrlKey: true }]) {
    assert.equal(shouldBlockBrowserShortcut(key('r', { metaKey: true, ...modifiers }), 'macos'), false)
  }
})
