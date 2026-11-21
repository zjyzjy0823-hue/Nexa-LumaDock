<script setup lang="ts">
import { computed, onUnmounted, ref, useId, watch } from 'vue'
import { normalizeWebsiteUrl, type WebsiteDraft } from '../../services/websiteForm'
import type { WebsiteCategory } from '../../types/website'
import OpusIcon from '../ui/OpusIcon.vue'

const props = withDefaults(defineProps<{
  categories: WebsiteCategory[]
  active?: boolean
  showPaste?: boolean
}>(), { active: true })
const draft = defineModel<WebsiteDraft>({ required: true })
const emit = defineEmits<{ error: [message: string] }>()
const id = useId()
const autoIcon = ref('')
const iconFailed = ref(false)
const previewUrl = computed(() => /^https?:\/\//i.test(draft.value.icon.trim()) ? draft.value.icon.trim() : '')
let faviconTimer: ReturnType<typeof setTimeout> | undefined
let faviconSequence = 0

function imageAvailable(url: string) {
  return new Promise<boolean>(resolve => {
    const image = new Image()
    const timeout = setTimeout(() => finish(false), 3500)
    function finish(found: boolean) {
      clearTimeout(timeout)
      image.onload = image.onerror = null
      resolve(found)
    }
    image.referrerPolicy = 'no-referrer'
    image.onload = () => finish(true)
    image.onerror = () => finish(false)
    image.src = url
  })
}

async function detectIcon(candidate: string, sequence: number) {
  if (!props.active || (draft.value.icon.trim() && draft.value.icon !== autoIcon.value)) return
  let url: URL
  try { url = normalizeWebsiteUrl(candidate) } catch { return }
  if (!/^https?:\/\//i.test(candidate) && !url.hostname.includes('.') && url.hostname !== 'localhost') return
  for (const path of ['/favicon.ico', '/apple-touch-icon.png']) {
    const icon = `${url.origin}${path}`
    const found = await imageAvailable(icon)
    if (sequence !== faviconSequence || draft.value.url.trim() !== candidate || !props.active
      || (draft.value.icon.trim() && draft.value.icon !== autoIcon.value)) return
    if (found) {
      autoIcon.value = icon
      draft.value.icon = icon
      return
    }
  }
}

watch([() => draft.value.url, () => props.active], ([url, active], [previousUrl]) => {
  clearTimeout(faviconTimer)
  const sequence = ++faviconSequence
  if (url !== previousUrl) {
    if (autoIcon.value && draft.value.icon === autoIcon.value) draft.value.icon = ''
    autoIcon.value = ''
  }
  if (active && url.trim()) faviconTimer = setTimeout(() => { void detectIcon(url.trim(), sequence) }, 500)
}, { immediate: true })
watch(() => draft.value.icon, () => { iconFailed.value = false })
onUnmounted(() => { clearTimeout(faviconTimer); faviconSequence++ })

async function pasteUrl() {
  try { draft.value.url = await navigator.clipboard.readText() }
  catch { emit('error', '请直接粘贴网址。') }
}
</script>

<template>
  <div class="website-fields">
    <div class="field">
      <label :for="`${id}-name`">网站名称</label>
      <input :id="`${id}-name`" v-model="draft.name" class="input" maxlength="120" placeholder="例如：我的工作台" required data-initial-focus />
    </div>
    <div class="field">
      <label :for="`${id}-url`">网址</label>
      <div class="website-url-field">
        <input :id="`${id}-url`" v-model="draft.url" class="input" inputmode="url" maxlength="2048" placeholder="https://example.com" required />
        <button v-if="showPaste" class="btn btn-ghost" type="button" @click="pasteUrl"><OpusIcon name="copy" />粘贴</button>
      </div>
    </div>
    <div class="website-icon-field">
      <div class="field">
        <label :for="`${id}-icon`">图标（自动获取，也可手动修改）</label>
        <input :id="`${id}-icon`" v-model="draft.icon" class="input" maxlength="500" placeholder="输入网址后自动获取 favicon" />
      </div>
      <span class="website-icon-preview" aria-label="图标预览">
        <img v-if="previewUrl && !iconFailed" :src="previewUrl" referrerpolicy="no-referrer" alt="" @error="iconFailed = true" />
        <span v-else>{{ draft.name.trim().slice(0, 1).toUpperCase() || '✦' }}</span>
      </span>
    </div>
    <div class="field">
      <label :for="`${id}-description`">简介</label>
      <textarea :id="`${id}-description`" v-model="draft.description" class="input" maxlength="500" rows="2" placeholder="用一句话描述这个网站" />
    </div>
    <div class="field-grid website-options">
      <div class="field">
        <label :for="`${id}-category`">分类</label>
        <select :id="`${id}-category`" v-model="draft.categoryId" class="input">
          <option value="">未分类</option>
          <option v-for="category in categories" :key="category.id" :value="category.id">{{ category.name }}</option>
        </select>
      </div>
      <label class="dlg-check"><input v-model="draft.favorite" type="checkbox" />设为收藏</label>
    </div>
  </div>
</template>

<style scoped>
.website-url-field, .website-icon-field { display: flex; align-items: end; gap: 8px; }
.website-url-field .input, .website-icon-field .field { flex: 1; min-width: 0; }
.website-url-field .btn { flex: none; min-height: 36px; }
.website-icon-field { margin-bottom: 12px; }
.website-icon-field .field, .website-options .field { margin-bottom: 0; }
.website-icon-preview {
  display: grid; place-items: center; flex: none; width: 40px; height: 36px;
  overflow: hidden; border: 1px solid var(--line-strong); border-radius: var(--r-sm);
  background: var(--surface-2); color: var(--accent); font-size: 16px; font-weight: 700;
}
.website-icon-preview img { width: 22px; height: 22px; object-fit: contain; }
.website-options { align-items: end; }
.website-options .dlg-check { min-height: 36px; }
</style>
