import { spawnSync } from 'node:child_process'
import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const tauri = join(root, 'src-tauri')
const config = JSON.parse(await readFile(join(tauri, 'tauri.conf.json'), 'utf8'))
const android = join(tauri, 'gen/android/app/src/main')
const cli = join(root, 'node_modules/@tauri-apps/cli/tauri.js')
const init = spawnSync(process.execPath, [cli, 'android', 'init', '--ci', '--skip-targets-install'], { cwd: root, stdio: 'inherit' })
if (init.status !== 0) throw init.error ?? new Error('Tauri Android initialization failed')

const copy = async (file, destination) => {
  await mkdir(dirname(destination), { recursive: true })
  await copyFile(join(tauri, 'android', file), destination)
}

await copy('LocalCorePlugin.kt', join(android, 'java', ...config.identifier.split('.'), 'LocalCorePlugin.kt'))
await copy('AndroidNotifications.kt', join(android, 'java', ...config.identifier.split('.'), 'AndroidNotifications.kt'))
for (const resource of ['studiolo_backup_rules.xml', 'studiolo_data_extraction_rules.xml', 'studiolo_network_security.xml']) {
  await copy(resource, join(android, 'res/xml', resource))
}

const logo = await readFile(join(root, 'public/favicon.svg'), 'utf8')
const mark = logo.match(/<path\b[^>]*\sd="([MmLlHhVvCcSsQqTtAaZz\d\s.,+\-]+)"/)?.[1]
const background = logo.match(/<rect\b[^>]*\sfill="(#[0-9a-f]{6})"/i)?.[1]
if (!mark || !background) throw new Error('Studiolo logo path and background are required')

const androidNamespace = 'http://schemas.android.com/apk/res/android'
const brandColor = '@color/studiolo_brand_background'
const foreground = '@drawable/studiolo_launcher_mark'
const startupMark = '@drawable/studiolo_startup_mark'

function vector(size, markSize, backgroundPath = '') {
  const inset = (size - markSize) / 2
  const scale = markSize / 100
  return `<vector xmlns:android="${androidNamespace}"
    android:width="${size}dp" android:height="${size}dp"
    android:viewportWidth="${size}" android:viewportHeight="${size}">
${backgroundPath}    <group android:translateX="${inset}" android:translateY="${inset}"
        android:scaleX="${scale}" android:scaleY="${scale}">
        <path android:fillColor="#FFFFFF" android:pathData="${mark}" />
    </group>
</vector>`
}

function startingTheme(items) {
  return `<resources>
    <style name="Theme.Studiolo.Starting" parent="Theme.studiolo_desktop">
        <item name="android:statusBarColor">${brandColor}</item>
        <item name="android:navigationBarColor">${brandColor}</item>
        <item name="android:windowLightStatusBar">false</item>
        <item name="android:windowLightNavigationBar">false</item>
${items}
    </style>
</resources>`
}

const resources = {
  'values/studiolo_brand.xml': `<resources><color name="studiolo_brand_background">${background}</color></resources>`,
  'drawable/studiolo_launcher_mark.xml': vector(108, 48),
  'drawable/studiolo_startup_mark.xml': vector(288, 120),
  'drawable/studiolo_notification_icon.xml': vector(24, 16),
  'mipmap-anydpi/studiolo_launcher.xml': vector(128, 72,
    `    <path android:fillColor="${brandColor}" android:strokeColor="#383B44"
        android:strokeWidth="1.5"
        android:pathData="M32 4H96A28 28 0 0 1 124 32V96A28 28 0 0 1 96 124H32A28 28 0 0 1 4 96V32A28 28 0 0 1 32 4Z" />
`),
  'mipmap-anydpi-v26/studiolo_launcher.xml': `<adaptive-icon xmlns:android="${androidNamespace}">
    <background android:drawable="${brandColor}" />
    <foreground android:drawable="${foreground}" />
    <monochrome android:drawable="${foreground}" />
</adaptive-icon>`,
  'drawable/studiolo_starting_window.xml': `<layer-list xmlns:android="${androidNamespace}">
    <item android:drawable="${brandColor}" />
    <item android:drawable="${startupMark}" android:gravity="center" android:width="192dp" android:height="192dp" />
</layer-list>`,
  'values/studiolo_starting_theme.xml': startingTheme(
    '        <item name="android:windowBackground">@drawable/studiolo_starting_window</item>'),
  'values-v31/studiolo_starting_theme.xml': startingTheme(
    `        <item name="android:windowSplashScreenBackground">${brandColor}</item>
        <item name="android:windowSplashScreenAnimatedIcon">${startupMark}</item>`),
}
for (const [path, xml] of Object.entries(resources)) {
  const resource = join(android, 'res', path)
  await mkdir(dirname(resource), { recursive: true })
  await writeFile(resource, `<?xml version="1.0" encoding="utf-8"?>\n${xml}\n`)
}

const manifestPath = join(android, 'AndroidManifest.xml')
let manifest = await readFile(manifestPath, 'utf8')
if (!/<application\b[^>]*>/s.test(manifest) || !manifest.includes('android.permission.INTERNET')) {
  throw new Error('Unexpected Tauri Android manifest template')
}
if (!manifest.includes('android.permission.POST_NOTIFICATIONS')) {
  manifest = manifest.replace(/<uses-permission\b[^>]*android.permission.INTERNET[^>]*\/>/,
    '$&\n    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />')
}
const attributes = {
  icon: '@mipmap/studiolo_launcher',
  roundIcon: '@mipmap/studiolo_launcher',
  allowBackup: 'false',
  fullBackupContent: '@xml/studiolo_backup_rules',
  dataExtractionRules: '@xml/studiolo_data_extraction_rules',
  networkSecurityConfig: '@xml/studiolo_network_security',
}
function setAttributes(tag, entries) {
  for (const [name, value] of Object.entries(entries)) {
    const existing = new RegExp(`\\s+android:${name}="[^"]*"`)
    tag = tag.replace(existing, '').replace(/^<\w+/, `$&\n        android:${name}="${value}"`)
  }
  return tag
}
const mainActivityTag = /<activity\b[^>]*android:name="\.MainActivity"[^>]*>/
if (!mainActivityTag.test(manifest)) throw new Error('Unexpected Tauri main activity declaration')
const updated = manifest.replace(/<application\b[^>]*>/s, tag => setAttributes(tag, attributes))
  .replace(mainActivityTag, tag => setAttributes(tag, { theme: '@style/Theme.Studiolo.Starting' }))
await writeFile(manifestPath, updated)

const mainActivityPath = join(android, 'java', ...config.identifier.split('.'), 'MainActivity.kt')
const mainActivity = await readFile(mainActivityPath, 'utf8')
const baseTheme = 'setTheme(R.style.Theme_studiolo_desktop)'
if (!mainActivity.includes(baseTheme)) {
  const onCreate = /override fun onCreate\(savedInstanceState: Bundle\?\) \{/
  if (!onCreate.test(mainActivity)) throw new Error('Unexpected Tauri main activity template')
  await writeFile(mainActivityPath, mainActivity.replace(onCreate, `$&\n    ${baseTheme}`))
}

// Keep the app SDK aligned with the pinned SDK installed by Android CI.
const gradlePath = join(android, '../../build.gradle.kts')
let gradle = await readFile(gradlePath, 'utf8')
for (const setting of ['compileSdk', 'targetSdk']) {
  const declaration = new RegExp(`^([ \\t]*${setting}[ \\t]*=[ \\t]*)\\d+[ \\t]*$`, 'm')
  if (!declaration.test(gradle)) throw new Error(`Unexpected Tauri Android SDK declaration for ${setting}`)
  gradle = gradle.replace(declaration, (_, prefix) => `${prefix}36`)
}
await writeFile(gradlePath, gradle)
