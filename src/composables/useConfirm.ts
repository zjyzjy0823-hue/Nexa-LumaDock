import { shallowRef } from 'vue'

export const confirmation = shallowRef<{ message: string; resolve: (value: boolean) => void } | null>(null)

export function confirmAction(message: string): Promise<boolean> {
  confirmation.value?.resolve(false)
  return new Promise(resolve => { confirmation.value = { message, resolve } })
}

export function resolveConfirmation(value: boolean) {
  const current = confirmation.value
  confirmation.value = null
  current?.resolve(value)
}
