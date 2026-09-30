// Run against npm run dev in a fresh Web context without Tauri mocks:
// npx --yes --package @playwright/cli playwright-cli -s=shellweb run-code --filename tests/desktop-interactions.browser.js
async page => {
  await page.goto('http://127.0.0.1:5173/')
  return page.evaluate(async () => {
    const { isEditableTarget, shouldSuppressDrag, installDesktopInteractions } = await import('/src/desktop/desktopInteractions.ts')
    const fixture = document.createElement('section')
    fixture.innerHTML = '<input><textarea></textarea><div contenteditable="true"><span>edit</span><div contenteditable="false"><span>read</span></div><span contenteditable="inherit">inherited edit</span></div><div contenteditable="plaintext-only">plain</div><div contenteditable="FALSE">read</div><button>button</button><a><img></a><svg><path></path></svg><div data-allow-drag><img></div>'
    document.body.append(fixture)
    const checks = []
    const check = (name, actual, expected) => {
      if (actual !== expected) throw Error(`${name}: expected ${expected}, got ${actual}`)
      checks.push(name)
    }
    let dispose
    try {
      for (const selector of ['input', 'textarea', '[contenteditable="true"] > span', '[contenteditable="plaintext-only"]']) {
        check(`editable ${selector}`, isEditableTarget(fixture.querySelector(selector)), true)
      }
      check('nested contenteditable=false', isEditableTarget(fixture.querySelector('[contenteditable="false"] span')), false)
      check('contenteditable false is case insensitive', isEditableTarget(fixture.querySelector('[contenteditable="FALSE"]')), false)
      check('invalid editable value inherits parent', isEditableTarget(fixture.querySelector('[contenteditable="inherit"]')), true)
      check('button is not editable', isEditableTarget(fixture.querySelector('button')), false)
      check('null is not editable', isEditableTarget(null), false)
      for (const selector of ['a', 'a img', 'svg path']) check(`ghost drag ${selector}`, shouldSuppressDrag(fixture.querySelector(selector)), true)
      check('explicit drag opt-in', shouldSuppressDrag(fixture.querySelector('[data-allow-drag] img')), false)
      check('editing drag', shouldSuppressDrag(fixture.querySelector('textarea')), false)
      check('ordinary text drag', shouldSuppressDrag(fixture.querySelector('button')), false)
      dispose = installDesktopInteractions()
      for (const selector of ['input', 'textarea', 'a', 'button']) {
        const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
        fixture.querySelector(selector).dispatchEvent(event)
        check(`native menu suppressed ${selector}`, event.defaultPrevented, true)
      }
      for (const [key, ctrlKey, shiftKey, blocked] of [['F5', false, false, true], ['r', true, false, true], ['R', true, true, true], ['p', true, false, true], ['s', true, false, true], ['c', true, false, false], ['v', true, false, false], ['a', true, false, false], ['x', true, false, false], ['z', true, false, false], ['y', true, false, false]]) {
        const event = new KeyboardEvent('keydown', { key, ctrlKey, shiftKey, bubbles: true, cancelable: true })
        fixture.querySelector('textarea').dispatchEvent(event)
        check(`shortcut ${ctrlKey ? 'Ctrl+' : ''}${shiftKey ? 'Shift+' : ''}${key}`, event.defaultPrevented, blocked)
      }
      for (const [selector, blocked] of [['a img', true], ['[data-allow-drag] img', false]]) {
        const event = new DragEvent('dragstart', { bubbles: true, cancelable: true })
        fixture.querySelector(selector).dispatchEvent(event)
        check(`dragstart ${selector}`, event.defaultPrevented, blocked)
      }
      const drop = new DragEvent('drop', { bubbles: true, cancelable: true })
      fixture.dispatchEvent(drop)
      check('drop remains available', drop.defaultPrevented, false)
      dispose()
      const after = new MouseEvent('contextmenu', { bubbles: true, cancelable: true })
      fixture.dispatchEvent(after)
      check('listener cleanup restores default behavior', after.defaultPrevented, false)
      return { passed: checks.length, checks }
    } finally { dispose?.(); fixture.remove() }
  })
}
