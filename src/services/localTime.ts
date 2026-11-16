/**
 * Local calendar keys for API timestamps.
 *
 * The API always returns UTC (`+00:00` / `Z`). Slicing that string yields the
 * UTC date, not the date the user saw when they created the entry — for
 * `Asia/Shanghai` (UTC+8) anything before 08:00 lands on the previous day, and
 * for UTC+13/+14 zones even noon does. These helpers convert first, then slice.
 */

function pad(value: number, size = 2) {
  return String(value).padStart(size, '0')
}

function parse(value: string | null | undefined): Date | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

/** `YYYY-MM-DD` in the viewer's timezone; falls back to the raw UTC text. */
export function localDateKey(value: string | null | undefined): string {
  const date = parse(value)
  if (!date) return value ? value.slice(0, 10) : ''
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** `YYYY-MM` in the viewer's timezone; falls back to the raw UTC text. */
export function localMonthKey(value: string | null | undefined): string {
  const date = parse(value)
  if (!date) return value ? value.slice(0, 7) : ''
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}`
}

/** Day of month (`01`..`31`) in the viewer's timezone. */
export function localDayKey(value: string | null | undefined): string {
  const date = parse(value)
  if (!date) return value ? value.slice(8, 10) : ''
  return pad(date.getDate())
}
