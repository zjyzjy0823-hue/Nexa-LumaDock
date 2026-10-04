<script setup lang="ts">
import { confirmAction } from '../composables/useConfirm'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { Check, ChevronDown, Cloud, Copy, ExternalLink, Github, Grid2X2, HardDrive, House, List, MoreHorizontal, Pencil, Plus, Search, X } from 'lucide-vue-next'
import ActionButton from '../components/ui/ActionButton.vue'
import ExternalLinkButton from '../components/ui/ExternalLink.vue'
import SectionContainer from '../components/ui/SectionContainer.vue'
import { useAuthStore } from '../stores/auth'
import { useWebsitesStore } from '../stores/websites'
import type { Website } from '../types/website'

const emit = defineEmits<{ action: [message: string] }>()
const auth = useAuthStore()
const store = useWebsitesStore()
const query = ref('')
const selectedCategory = ref('all')
const onlyFavorites = ref(false)
const sort = ref<'order' | 'name' | 'createdAt' | 'updatedAt'>('order')
const sortOpen = ref(false)
const sortOptions = [
  { value: 'order', label: '自定义排序' },
  { value: 'name', label: '名称排序' },
  { value: 'createdAt', label: '创建时间' },
  { value: 'updatedAt', label: '最近更新' },
] as const
const viewMode = ref<'grid' | 'list'>('grid')
const openMenuId = ref<string | null>(null)
const dialogMode = ref<'add' | 'edit' | null>(null)
const editingId = ref<string | null>(null)
const formError = ref('')
const saving = ref(false)
const categoryDialog = ref(false)
const categoryName = ref('')
const editingCategoryId = ref<string | null>(null)
const categoryError = ref('')
const form = reactive({ name: '', url: '', icon: '', description: '', categoryId: '', favorite: false, order: 0 })
const autoIconValue = ref('')
const iconPreviewFailed = ref(false)
const iconPreviewUrl = computed(() => /^https?:\/\//i.test(form.icon.trim()) ? form.icon.trim() : '')
let faviconTimer: ReturnType<typeof setTimeout> | undefined
let faviconSequence = 0
function imageAvailable(url: string) {
  return new Promise<boolean>(resolve => {
    const image = new Image()
    const timer = window.setTimeout(() => { image.onload = null; image.onerror = null; resolve(false) }, 3500)
    image.onload = () => { window.clearTimeout(timer); resolve(true) }
    image.onerror = () => { window.clearTimeout(timer); resolve(false) }
    image.src = url
  })
}
async function detectFavicon() {
  const candidate = form.url.trim()
  const sequence = ++faviconSequence
  if (!dialogMode.value || (form.icon.trim() && form.icon !== autoIconValue.value)) return
  let origin: string
  try {
    const parsed = new URL(/^https?:\/\//i.test(candidate) ? candidate : `https://${candidate}`)
    if (!parsed.hostname || (!/^https?:\/\//i.test(candidate) && !parsed.hostname.includes('.') && parsed.hostname !== 'localhost')) return
    origin = parsed.origin
  } catch { return }
  for (const path of ['/favicon.ico', '/apple-touch-icon.png']) {
    const icon = `${origin}${path}`
    if (await imageAvailable(icon) && sequence === faviconSequence && form.url.trim() === candidate) {
      form.icon = icon
      autoIconValue.value = icon
      iconPreviewFailed.value = false
      return
    }
  }
}
watch(() => form.url, () => {
  if (faviconTimer) clearTimeout(faviconTimer)
  faviconSequence++
  if (autoIconValue.value && form.icon === autoIconValue.value) {
    form.icon = ''
    autoIconValue.value = ''
  }
  faviconTimer = setTimeout(() => { void detectFavicon() }, 500)
})
watch(() => form.icon, () => { iconPreviewFailed.value = false })
const websiteCategories = computed(() => [{ id: 'all', name: '全部', order: -1 }, ...store.categories])
const visibleGroups = computed(() => {
  const items = store.websites.map(item => ({ ...item, href: item.url, subtitle: item.description || item.url, logo: item.icon || 'generic' }))
  const favorite = items.filter(item => item.favorite)
  const other = items.filter(item => !item.favorite)
  return [
    { id: 'favorites', title: '收藏网站', items: favorite },
    { id: 'websites', title: onlyFavorites.value ? '收藏网站' : '我的网站', items: onlyFavorites.value ? [] : other },
  ].filter(group => group.items.length)
})

function refresh() {
  if (!auth.token) return
  store.load(auth.token, { categoryId: selectedCategory.value === 'all' ? undefined : selectedCategory.value,
    search: query.value.trim(), favorite: onlyFavorites.value ? true : undefined, sort: sort.value })
}
function openWebsite(item: Website) {
  openMenuId.value = null
  if (auth.token) void store.visit(auth.token, item.id).catch(() => {})
}
let searchTimer: ReturnType<typeof setTimeout> | undefined
watch([selectedCategory, onlyFavorites, sort], refresh)
watch(query, () => { if (searchTimer) clearTimeout(searchTimer); searchTimer = setTimeout(refresh, 250) })

function openDialog(item?: Website) {
  if (!auth.token) { emit('action', '请先登录。'); return }
  openMenuId.value = null; editingId.value = item?.id ?? null; dialogMode.value = item ? 'edit' : 'add'; formError.value = ''
  Object.assign(form, { name: item?.name ?? '', url: item?.url ?? '', icon: item?.icon ?? '', description: item?.description ?? '',
    categoryId: item?.categoryId ?? '', favorite: item?.favorite ?? false, order: item?.order ?? (Math.max(-1, ...store.websites.map(site => site.order)) + 1) })
  autoIconValue.value = ''
  iconPreviewFailed.value = false
}
defineExpose({ openCreate: () => openDialog() })
function clearOrCreate() {
  if (query.value || selectedCategory.value !== 'all' || onlyFavorites.value) {
    query.value = ''; selectedCategory.value = 'all'; onlyFavorites.value = false
  } else openDialog()
}
function closeDialog() { if (!saving.value) { dialogMode.value = null; formError.value = '' } }
async function saveWebsite() {
  const name = form.name.trim(), candidate = form.url.trim()
  if (!name || !candidate) { formError.value = '请填写网站名称和网址。'; return }
  let url: string
  try { if (/^[a-z][a-z0-9+.-]*:/i.test(candidate) && !/^https?:\/\//i.test(candidate)) throw new Error()
    const parsed = new URL(/^https?:\/\//i.test(candidate) ? candidate : `https://${candidate}`)
    if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname || /\s/.test(candidate)) throw new Error()
    url = parsed.toString()
  } catch { formError.value = '请输入有效的 HTTP 或 HTTPS 网址。'; return }
  if (!auth.token) return
  saving.value = true; formError.value = ''
  try {
    const data = { name, url, icon: form.icon.trim() || null, description: form.description.trim() || null,
      categoryId: form.categoryId || null, favorite: form.favorite, order: form.order }
    if (editingId.value) await store.update(auth.token, editingId.value, data)
    else await store.create(auth.token, data)
    emit('action', editingId.value ? `已更新「${name}」。` : `已添加「${name}」。`)
    dialogMode.value = null; selectedCategory.value = 'all'; query.value = ''; refresh()
  } catch (error) { formError.value = error instanceof Error ? error.message : '保存失败' }
  finally { saving.value = false }
}
async function removeWebsite(item: Website) {
  openMenuId.value = null
  if (!auth.token || !(await confirmAction(`删除「${item.name}」？`))) return
  try { await store.remove(auth.token, item.id); emit('action', `已删除「${item.name}」。`) }
  catch (error) { emit('action', error instanceof Error ? error.message : '删除失败') }
}
async function toggleFavorite(item: Website) {
  openMenuId.value = null
  if (!auth.token) return
  try { await store.update(auth.token, item.id, { favorite: !item.favorite }); refresh(); emit('action', item.favorite ? '已取消收藏。' : '已收藏。') }
  catch (error) { emit('action', error instanceof Error ? error.message : '操作失败') }
}
async function moveWebsite(item: Website, direction: -1 | 1) {
  if (!auth.token || selectedCategory.value !== 'all' || query.value || onlyFavorites.value || sort.value !== 'order') return
  const sorted = [...store.websites].sort((a, b) => a.order - b.order || a.id.localeCompare(b.id))
  const group = sorted.filter(entry => entry.favorite === item.favorite)
  const index = group.findIndex(entry => entry.id === item.id)
  const neighbor = group[index + direction]
  if (!neighbor) return
  try {
    const itemPosition = sorted.findIndex(entry => entry.id === item.id)
    const neighborPosition = sorted.findIndex(entry => entry.id === neighbor.id)
    sorted[itemPosition] = neighbor
    sorted[neighborPosition] = item
    for (let position = 0; position < sorted.length; position++) {
      if (sorted[position].order !== position) await store.update(auth.token, sorted[position].id, { order: position })
    }
    sort.value = 'order'; refresh(); emit('action', '网站顺序已更新。')
  } catch (error) { emit('action', error instanceof Error ? error.message : '排序失败'); refresh() }
}
async function saveCategory() {
  if (!auth.token || !categoryName.value.trim()) { categoryError.value = '请输入分类名称。'; return }
  try {
    if (editingCategoryId.value) await store.renameCategory(auth.token, editingCategoryId.value, categoryName.value.trim())
    else await store.createCategory(auth.token, categoryName.value.trim())
    editingCategoryId.value = null; categoryName.value = ''; categoryError.value = ''; emit('action', '分类已保存。')
  }
  catch (error) { categoryError.value = error instanceof Error ? error.message : '保存失败' }
}
function renameCategory(id: string, oldName: string) {
  editingCategoryId.value = id; categoryName.value = oldName; categoryError.value = ''
}
async function removeCategory(id: string, name: string) {
  if (!auth.token || !(await confirmAction(`删除分类「${name}」？其中的网站会保留。`))) return
  try { await store.removeCategory(auth.token, id); if (selectedCategory.value === id) selectedCategory.value = 'all'; emit('action', '分类已删除。') }
  catch (error) { categoryError.value = error instanceof Error ? error.message : '删除失败' }
}
async function copyLink(item: Website) {
  openMenuId.value = null
  try { await navigator.clipboard.writeText(item.url); emit('action', `已复制「${item.name}」的网址。`) }
  catch { emit('action', '复制失败，请检查浏览器权限。') }
}
function onDocumentPointerDown(event: PointerEvent) {
  if (!(event.target as Element).closest('[data-website-menu]')) openMenuId.value = null
  if (!(event.target as Element).closest('[data-website-sort]')) sortOpen.value = false
}
function onDocumentKeydown(event: KeyboardEvent) { if (event.key === 'Escape') { openMenuId.value = null; sortOpen.value = false; closeDialog(); categoryDialog.value = false } }
onMounted(async () => {
  document.addEventListener('pointerdown', onDocumentPointerDown); document.addEventListener('keydown', onDocumentKeydown)
  refresh()
})
onUnmounted(() => { document.removeEventListener('pointerdown', onDocumentPointerDown); document.removeEventListener('keydown', onDocumentKeydown); if (searchTimer) clearTimeout(searchTimer); if (faviconTimer) clearTimeout(faviconTimer); faviconSequence++ })
</script>

<template>
  <div class="websites-page">
    <h1 class="visually-hidden">网站</h1>

    <div class="website-toolbar">
      <div class="website-toolbar__top">
        <label class="website-search">
          <Search :size="19" :stroke-width="1.9" aria-hidden="true" />
          <input v-model="query" type="search" placeholder="搜索网站、应用或服务..." aria-label="搜索网站" />
          <span v-if="query" class="website-search__clear" role="button" tabindex="0" aria-label="清除搜索" @click="query = ''" @keydown.enter="query = ''"><X :size="15" /></span>
        </label>
        <div class="website-toolbar__right">
          <div class="view-switch" aria-label="视图切换">
            <button type="button" :class="{ 'view-switch__button--active': viewMode === 'grid' }" :aria-pressed="viewMode === 'grid'" aria-label="网格视图" title="网格视图" @click="viewMode = 'grid'"><Grid2X2 :size="17" :stroke-width="1.9" /></button>
            <button type="button" :class="{ 'view-switch__button--active': viewMode === 'list' }" :aria-pressed="viewMode === 'list'" aria-label="列表视图" title="列表视图" @click="viewMode = 'list'"><List :size="18" :stroke-width="1.9" /></button>
          </div>
          <ActionButton variant="primary" size="sm" @click="openDialog()"><Plus :size="15" :stroke-width="2" />添加网站</ActionButton>
        </div>
      </div>
      <div class="website-toolbar__bottom">
      <div class="category-filter" aria-label="网站分类">
        <button
          v-for="category in websiteCategories"
          :key="category.id"
          class="category-filter__pill"
          :class="{ 'category-filter__pill--active': selectedCategory === category.id }"
          type="button"
          :aria-pressed="selectedCategory === category.id"
          @click="selectedCategory = category.id"
        >{{ category.name }}</button>
        <button class="category-filter__pill" :class="{ 'category-filter__pill--active': onlyFavorites }" type="button" @click="onlyFavorites = !onlyFavorites">★ 收藏</button>
        <button class="category-filter__pill" type="button" @click="categoryDialog = true">+ 管理分类</button>
      </div>
      <div class="website-sort" data-website-sort>
        <button class="website-sort__trigger" type="button" aria-label="排序" aria-haspopup="listbox" :aria-expanded="sortOpen" @click="sortOpen = !sortOpen">
          {{ sortOptions.find(option => option.value === sort)?.label }} <ChevronDown :size="13" />
        </button>
        <div v-if="sortOpen" class="website-sort__menu" role="listbox" aria-label="排序方式">
          <button v-for="option in sortOptions" :key="option.value" type="button" role="option" :aria-selected="sort === option.value" :class="{ 'website-sort__option--selected': sort === option.value }" @click="sort = option.value; sortOpen = false">{{ option.label }}<Check v-if="sort === option.value" :size="13" /></button>
        </div>
      </div>
      </div>
    </div>

    <div v-if="store.loading" class="website-empty" role="status"><h2>正在加载网站…</h2></div>
    <div v-else-if="store.error" class="website-empty" role="alert"><h2>加载失败</h2><p>{{ store.error }}</p><button type="button" @click="refresh">重试</button></div>
    <div v-else-if="visibleGroups.length" class="website-sections">
      <SectionContainer v-for="group in visibleGroups" :key="group.id" :title="group.title" :class="{ 'website-section--menu-open': group.items.some(item => item.id === openMenuId) }">
        <div class="website-grid" :class="{ 'website-grid--list': viewMode === 'list' }">
          <article v-for="item in group.items" :key="item.id" class="website-card" :class="{ 'website-card--menu-open': openMenuId === item.id }">
            <ExternalLinkButton class="website-card__main" :href="item.href" :aria-label="`打开 ${item.name}`" @activate="openWebsite(item)" @action="emit('action', $event)">
              <span class="website-logo" :class="`website-logo--${item.logo}`" aria-hidden="true">
                <svg v-if="item.logo === 'chatgpt'" viewBox="0 0 24 24"><path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.182a5.985 5.985 0 0 0-3.998 2.9 6.046 6.046 0 0 0 .743 7.097 5.98 5.98 0 0 0 .511 4.91 6.051 6.051 0 0 0 6.515 2.9A5.984 5.984 0 0 0 13.26 24a6.056 6.056 0 0 0 5.772-4.206 5.989 5.989 0 0 0 3.998-2.9 6.056 6.056 0 0 0-.748-7.073ZM13.26 22.43a4.476 4.476 0 0 1-2.877-1.041l.142-.08 4.778-2.758a.795.795 0 0 0 .393-.681v-6.737l2.02 1.169a.07.07 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.494 4.493Zm-9.66-4.125a4.471 4.471 0 0 1-.535-3.014l.142.085 4.783 2.758a.771.771 0 0 0 .78 0l5.843-3.368v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.499 4.499 0 0 1-6.14-1.646ZM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.677l5.814 3.354-2.02 1.169a.076.076 0 0 1-.071 0l-4.83-2.787A4.504 4.504 0 0 1 2.34 7.872Zm16.597 3.855-5.834-3.387L15.12 7.2a.076.076 0 0 1 .07 0l4.831 2.791a4.494 4.494 0 0 1-.676 8.104v-5.677a.79.79 0 0 0-.407-.667Zm2.01-3.023-.141-.085-4.774-2.782a.775.775 0 0 0-.786 0L9.41 9.229V6.897a.067.067 0 0 1 .028-.061l4.831-2.787a4.5 4.5 0 0 1 6.68 4.66Zm-12.64 4.135-2.02-1.164a.08.08 0 0 1-.038-.057V6.074a4.5 4.5 0 0 1 7.376-3.453l-.142.08-4.778 2.758a.794.794 0 0 0-.393.681Zm1.098-2.365 2.602-1.5 2.607 1.5v3l-2.598 1.499-2.607-1.5Z" fill="currentColor" /></svg>
                <Github v-else-if="item.logo === 'github'" :size="27" :stroke-width="2.1" fill="currentColor" />
                <svg v-else-if="item.logo === 'gmail'" viewBox="0 0 48 38" fill="none"><path d="M5 34V7l19 14L43 7v27" stroke="#EA4335" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" /><path d="M5 10v24" stroke="#4285F4" stroke-width="6" stroke-linecap="round" /><path d="M43 10v24" stroke="#34A853" stroke-width="6" stroke-linecap="round" /><path d="m5 7 19 14" stroke="#C5221F" stroke-width="6" stroke-linecap="round" /><path d="M43 7 24 21" stroke="#FBBC04" stroke-width="6" stroke-linecap="round" /></svg>
                <span v-else-if="item.logo === 'notion'" class="brand-notion">N</span>
                <svg v-else-if="item.logo === 'youtube'" viewBox="0 0 40 30"><rect x="1" y="2" width="38" height="26" rx="7" fill="currentColor" /><path d="m17 9 11 6-11 6Z" fill="#fff" /></svg>
                <svg v-else-if="item.logo === 'figma'" viewBox="0 0 32 48"><path d="M16 16H8a8 8 0 0 1 0-16h8Z" fill="#F24E1E" /><path d="M16 0h8a8 8 0 0 1 0 16h-8Z" fill="#FF7262" /><path d="M16 16h8a8 8 0 1 1 0 16h-8Z" fill="#1ABCFE" /><path d="M16 16H8a8 8 0 0 0 0 16h8Z" fill="#A259FF" /><path d="M16 32H8a8 8 0 1 0 8 8Z" fill="#0ACF83" /></svg>
                <span v-else-if="item.logo === 'linear'" class="brand-linear"><i /><i /><i /></span>
                <span v-else-if="item.logo === 'vercel'" class="brand-vercel" />
                <Cloud v-else-if="item.logo === 'cloudflare'" :size="28" :stroke-width="2" fill="currentColor" />
                <Pencil v-else-if="item.logo === 'excalidraw'" :size="27" :stroke-width="2.2" />
                <HardDrive v-else-if="item.logo === 'nas'" :size="27" :stroke-width="1.9" />
                <House v-else-if="item.logo === 'home'" :size="28" :stroke-width="2" />
                <span v-else-if="item.logo === 'immich'" class="brand-immich"><i /><i /><i /><i /></span>
                <span v-else-if="item.logo === 'jellyfin'" class="brand-jellyfin" />
                <img v-else-if="item.icon && /^https?:\/\//.test(item.icon)" :src="item.icon" alt="" class="website-icon-image" />
                <span v-else class="brand-generic">{{ item.name.slice(0, 1).toUpperCase() }}</span>
              </span>
              <span class="website-card__copy"><strong>{{ item.name }}</strong><small>{{ item.subtitle }}</small></span>
            </ExternalLinkButton>
            <div class="website-card__menu" data-website-menu>
              <button class="website-card__more" type="button" :aria-label="`${item.name} 更多操作`" :aria-expanded="openMenuId === item.id" @click="openMenuId = openMenuId === item.id ? null : item.id"><MoreHorizontal :size="19" :stroke-width="2" /></button>
              <div v-if="openMenuId === item.id" class="website-menu">
                <ExternalLinkButton :href="item.href" @activate="openWebsite(item)" @action="emit('action', $event)"><ExternalLink :size="15" />打开网站</ExternalLinkButton>
                <button type="button" @click="copyLink(item)"><Copy :size="15" />复制链接</button>
                <button type="button" @click="openDialog(item)"><Pencil :size="15" />编辑网站</button>
                <button type="button" @click="toggleFavorite(item)">{{ item.favorite ? '☆ 取消收藏' : '★ 收藏网站' }}</button>
                <button type="button" :disabled="selectedCategory !== 'all' || !!query || onlyFavorites || sort !== 'order'" @click="moveWebsite(item, -1)">上移</button>
                <button type="button" :disabled="selectedCategory !== 'all' || !!query || onlyFavorites || sort !== 'order'" @click="moveWebsite(item, 1)">下移</button>
                <button type="button" @click="removeWebsite(item)">删除网站</button>
              </div>
            </div>
          </article>
        </div>
      </SectionContainer>
    </div>

    <div v-else class="website-empty">
      <span class="website-empty__icon"><Search :size="25" :stroke-width="1.7" /></span>
      <h2>{{ query || selectedCategory !== 'all' || onlyFavorites ? '没有找到相关网站' : '还没有网站' }}</h2>
      <p>{{ query || selectedCategory !== 'all' || onlyFavorites ? '试试其他关键词或切换分类。' : '添加一个网站，开始建立你的快捷入口。' }}</p>
      <button type="button" @click="clearOrCreate">{{ query || selectedCategory !== 'all' || onlyFavorites ? '清除筛选' : '添加网站' }}</button>
    </div>

    <div v-if="dialogMode" class="website-dialog-backdrop" @click.self="closeDialog">
      <div class="website-dialog" role="dialog" aria-modal="true" :aria-label="dialogMode === 'add' ? '添加网站' : '编辑网站'">
        <div class="website-dialog__header"><div><span>PERSONAL SPACE</span><h2>{{ dialogMode === 'add' ? '添加网站' : '编辑网站' }}</h2><p>保存一个属于你的快捷入口。</p></div><button type="button" aria-label="关闭" @click="closeDialog"><X :size="19" /></button></div>
        <form @submit.prevent="saveWebsite">
          <label>网站名称<input v-model="form.name" maxlength="120" placeholder="例如：我的工作台" required /></label>
          <label>网址<input v-model="form.url" type="text" inputmode="url" placeholder="https://example.com" required /></label>
          <div class="website-icon-field">
            <label>图标（自动获取，也可手动修改）<input v-model="form.icon" maxlength="500" placeholder="输入网址后自动获取 favicon" /></label>
            <span class="website-icon-preview" aria-label="图标预览">
              <img v-if="iconPreviewUrl && !iconPreviewFailed" :src="iconPreviewUrl" alt="" @error="iconPreviewFailed = true" />
              <span v-else>{{ form.name.trim().slice(0, 1).toUpperCase() || '✦' }}</span>
            </span>
          </div>
          <label>简介<textarea v-model="form.description" maxlength="500" placeholder="用一句话描述这个网站" /></label>
          <div class="website-dialog__row">
            <label>分类<select v-model="form.categoryId"><option value="">未分类</option><option v-for="category in store.categories" :key="category.id" :value="category.id">{{ category.name }}</option></select></label>
            <label class="website-check"><input v-model="form.favorite" type="checkbox" /> 收藏</label>
          </div>
          <p v-if="formError" class="website-dialog__error" role="alert">{{ formError }}</p>
          <div class="website-dialog__actions"><button type="button" class="website-dialog__cancel" :disabled="saving" @click="closeDialog">取消</button><button type="submit" class="website-dialog__submit" :disabled="saving"><Check :size="16" />{{ saving ? '保存中…' : dialogMode === 'add' ? '添加网站' : '保存修改' }}</button></div>
        </form>
      </div>
    </div>
    <div v-if="categoryDialog" class="website-dialog-backdrop" @click.self="categoryDialog = false"><div class="website-dialog" role="dialog" aria-modal="true" aria-label="管理分类">
      <div class="website-dialog__header"><h2>管理分类</h2><button type="button" aria-label="关闭" @click="categoryDialog = false"><X :size="19" /></button></div>
      <form class="website-category-form" @submit.prevent="saveCategory"><input v-model="categoryName" maxlength="80" aria-label="分类名称" :placeholder="editingCategoryId ? '分类名称' : '新分类名称'" /><button type="submit">{{ editingCategoryId ? '保存分类' : '添加' }}</button><button v-if="editingCategoryId" type="button" @click="editingCategoryId = null; categoryName = ''">取消编辑</button></form>
      <p v-if="categoryError" class="website-dialog__error" role="alert">{{ categoryError }}</p>
      <div v-for="category in store.categories" :key="category.id" class="website-category-row"><span>{{ category.name }}</span><button type="button" @click="renameCategory(category.id, category.name)">重命名</button><button type="button" @click="removeCategory(category.id, category.name)">删除</button></div>
    </div></div>
  </div>
</template>

<style scoped>
.websites-page { min-width: 0; padding: 0 20px 36px; }
.visually-hidden { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
.website-toolbar { position: relative; z-index: 40; margin: 4px 0 14px; padding: 10px 13px 9px; border: 1px solid rgba(255,255,255,.48); border-radius: 18px; background: linear-gradient(140deg,rgba(217,229,255,.27),rgba(202,216,246,.19) 55%,rgba(247,220,237,.24)); box-shadow: var(--shadow-card); backdrop-filter: blur(var(--glass-blur)) saturate(125%); -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(125%); }
.website-toolbar__top, .website-toolbar__right, .category-filter, .view-switch { display: flex; align-items: center; }
.website-toolbar__top { gap: 16px; justify-content: space-between; }
.website-search { display: flex; align-items: center; gap: 9px; width: min(100%, 355px); height: 37px; padding: 0 12px; color: #52698f; border: 1px solid rgba(156,177,216,.28); border-radius: 11px; background: rgba(255,255,255,.78); box-shadow: inset 0 1px 1px rgba(255,255,255,.85), 0 3px 10px rgba(42,60,111,.04); transition: border-color .18s, background .18s; }
.website-search:focus-within { border-color: rgba(103,132,213,.55); background: rgba(255,255,255,.78); }
.website-search input { width: 100%; min-width: 0; padding: 0; color: #263653; border: 0; outline: none; background: transparent; font-size: 13px; }
.website-search input::placeholder { color: #6c7e9a; }
.website-search input::-webkit-search-cancel-button { display: none; }
.website-search__clear { display: grid; flex: none; width: 22px; height: 22px; place-items: center; border-radius: 7px; cursor: pointer; }
.website-search__clear:hover { color: #3e5fc1; background: rgba(117,149,222,.14); }
.website-toolbar__right { flex: none; gap: 9px; }
.view-switch { gap: 2px; padding: 3px; border: 1px solid rgba(155,175,213,.25); border-radius: 12px; background: rgba(231,238,253,.53); }
.view-switch button { display: grid; width: 34px; height: 31px; place-items: center; color: #7586a2; border: 0; border-radius: 9px; background: transparent; transition: background .18s, color .18s, box-shadow .18s; }
.view-switch button:hover { color: #4164ba; }
.view-switch .view-switch__button--active { color: #506fc4; background: rgba(255,255,255,.86); box-shadow: 0 2px 8px rgba(44,64,118,.1), inset 0 1px rgba(255,255,255,.9); }
.website-toolbar__bottom { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
.category-filter { flex: 1; min-width: 0; gap: 7px; overflow-x: auto; scrollbar-width: none; }
.category-filter::-webkit-scrollbar { display: none; }
.category-filter__pill { flex: none; min-height: 27px; padding: 4px 11px; color: rgba(255,255,255,.9); border: 1px solid rgba(255,255,255,.26); border-radius: 99px; background: rgba(255,255,255,.16); font-size: 11px; font-weight: 580; white-space: nowrap; text-shadow:0 1px 5px rgba(25,38,76,.3); transition: background .18s, color .18s, box-shadow .18s; }
.category-filter__pill:hover { color: #fff; background: rgba(255,255,255,.28); }
.category-filter__pill--active, .category-filter__pill--active:hover { color: #fff; border-color: rgba(77,106,190,.3); background: linear-gradient(120deg, #6c87d3, #7883cf); box-shadow: 0 5px 12px rgba(74,96,178,.22), inset 0 1px rgba(255,255,255,.22); }
.website-sections { display: grid; gap: 14px; }
.website-sections :deep(.section-container) { padding: 17px 19px 19px; overflow: visible; }
.website-sections :deep(.website-section--menu-open) { z-index: 5; }
.website-sections :deep(.section-container__heading) { margin-bottom: 13px; }
.website-grid { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 12px; }
.website-grid--list { grid-template-columns: 1fr; gap: 9px; }
.website-card { position: relative; display: flex; align-items: center; min-width: 0; min-height: 91px; border: var(--glass-tile-border); border-radius: 15px; background: var(--glass-tile-background); box-shadow: var(--glass-tile-shadow); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); transition: transform .2s, background .2s, box-shadow .2s; }
.website-card::after { position: absolute; inset: auto 15px 0; height: 1px; background: linear-gradient(90deg,transparent,rgba(255,255,255,.7),transparent); content: ''; pointer-events: none; }
.website-card:hover, .website-card--menu-open { z-index: 2; transform: translateY(-2px) scale(1.02); background: var(--glass-tile-hover-background); box-shadow: var(--glass-tile-hover-shadow); }
.website-card__main { display: flex; align-items: center; gap: 13px; min-width: 0; min-height: 89px; flex: 1; padding: 14px 0 14px 14px; color: inherit; text-decoration: none; }
.website-logo { display: grid; flex: none; width: 48px; height: 48px; place-items: center; overflow: hidden; color: #fff; border: 1px solid rgba(255,255,255,.52); border-radius: 14px; box-shadow: inset 0 1px 0 rgba(255,255,255,.35), 0 4px 12px rgba(32,52,104,.13); }
.website-logo svg { display: block; width: 29px; height: 29px; }
.website-logo--chatgpt { background: linear-gradient(145deg,#1b8a80,#0f5b63); }
.website-logo--github { background: linear-gradient(145deg,#3d485d,#141d30); }
.website-logo--gmail { background: linear-gradient(145deg,#fff,#f1f5ff); }
.website-logo--gmail svg { width: 30px; height: 25px; }
.website-logo--notion { color: #111927; background: linear-gradient(145deg,#fff,#e8ebf3); }
.brand-notion { display: grid; width: 27px; height: 27px; place-items: center; border: 2.3px solid currentColor; border-radius: 2px; box-shadow: 2px -2px 0 currentColor; font-family: Georgia,serif; font-size: 22px; font-weight: 800; line-height: 1; }
.website-logo--youtube { color: #ee3847; background: linear-gradient(145deg,#fff,#fff3f3); }
.website-logo--youtube svg { width: 32px; }
.website-logo--figma { background: linear-gradient(145deg,#fff,#f1f3fa); }
.website-logo--figma svg { width: 23px; height: 34px; }
.website-logo--linear { background: linear-gradient(145deg,#5350aa,#28245f); }
.brand-linear { position: relative; display: block; width: 29px; height: 29px; overflow: hidden; border-radius: 50%; background: #e1e1ff; }
.brand-linear i { position: absolute; display: block; height: 5px; background: #6962bd; transform: rotate(45deg); }
.brand-linear i:nth-child(1) { width: 28px; top: 4px; left: -14px; }.brand-linear i:nth-child(2) { width: 34px; top: 11px; left: -10px; }.brand-linear i:nth-child(3) { width: 34px; top: 19px; left: -3px; }
.website-logo--vercel { background: linear-gradient(145deg,#343a49,#111624); }
.brand-vercel { width: 0; height: 0; border-right: 15px solid transparent; border-bottom: 26px solid #fff; border-left: 15px solid transparent; transform: rotate(180deg); }
.website-logo--cloudflare { color: #f18a17; background: linear-gradient(145deg,#fff6e7,#fff); }
.website-logo--excalidraw { background: linear-gradient(145deg,#9e7ce8,#6955be); }
.website-logo--nas { background: linear-gradient(145deg,#63b1fd,#3479dc); }
.website-logo--home { background: linear-gradient(145deg,#61c9f2,#258dc5); }
.website-logo--immich { background: linear-gradient(145deg,#303c6e,#171d42); }
.brand-immich { position: relative; width: 32px; height: 32px; }.brand-immich i { position: absolute; width: 14px; height: 14px; border-radius: 8px 8px 2px 8px; transform-origin: 16px 16px; }.brand-immich i:nth-child(1) { top: 1px; left: 9px; background: #f4c958; transform: rotate(0deg); }.brand-immich i:nth-child(2) { top: 9px; left: 17px; background: #f18684; transform: rotate(90deg); }.brand-immich i:nth-child(3) { top: 17px; left: 9px; background: #a78de9; transform: rotate(180deg); }.brand-immich i:nth-child(4) { top: 9px; left: 1px; background: #7ac6e3; transform: rotate(270deg); }
.website-logo--jellyfin { background: linear-gradient(145deg,#2b284d,#171432); }
.brand-jellyfin { position: relative; width: 29px; height: 27px; background: linear-gradient(135deg,#aa60cf,#616bd9); clip-path: polygon(50% 0,100% 100%,0 100%); }.brand-jellyfin::after { position: absolute; inset: 11px 9px 4px; background: #252044; clip-path: polygon(50% 0,100% 100%,0 100%); content: ''; }
.website-logo--generic { background: linear-gradient(145deg,#8ca8e8,#6e78c8); }.brand-generic { font-size: 21px; font-weight: 700; }
.website-card__copy { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.website-card__copy strong { overflow: hidden; color: #273652; font-size: 13px; font-weight: 700; letter-spacing: -.01em; text-overflow: ellipsis; white-space: nowrap; }
.website-card__copy small { overflow: hidden; color: #52627d; font-size: 11px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.website-card__menu { position: relative; z-index: 3; align-self: flex-start; margin: 12px 9px 0 3px; }
.website-card__more { display: grid; width: 27px; height: 27px; place-items: center; color: #8695ab; border: 0; border-radius: 8px; background: transparent; }
.website-card__more:hover, .website-card__more[aria-expanded="true"] { color: #4867b7; background: rgba(111,141,213,.13); }
.website-menu { position: absolute; z-index: 10; top: 32px; right: 0; width: 143px; padding: 5px; border: 1px solid rgba(177,191,221,.48); border-radius: 12px; background:var(--glass-popover-background); box-shadow: 0 13px 30px rgba(32,46,91,.21);   backdrop-filter:var(--glass-overlay-filter); -webkit-backdrop-filter:var(--glass-overlay-filter); }
.website-menu a, .website-menu button { display: flex; align-items: center; gap: 9px; width: 100%; padding: 8px; color: #435674; border: 0; border-radius: 8px; background: none; font-size: 11px; font-weight: 580; text-align: left; text-decoration: none; white-space: nowrap; }
.website-menu a:hover, .website-menu button:hover { color: #3e61bd; background: #edf2fc; }
.website-menu button:disabled { opacity: .4; cursor: not-allowed; }
.website-grid--list .website-card, .website-grid--list .website-card__main { min-height: 74px; }
.website-grid--list .website-card__main { padding-block: 10px; }
.website-grid--list .website-logo { width: 43px; height: 43px; border-radius: 12px; }
.website-empty { display: flex; min-height: 290px; flex-direction: column; align-items: center; justify-content: center; padding: 28px; color: #fff; border: 1px solid rgba(255,255,255,.48); border-radius: 22px; background: linear-gradient(140deg,rgba(217,229,255,.27),rgba(202,216,246,.19) 55%,rgba(247,220,237,.24)); box-shadow: var(--shadow-card); backdrop-filter: blur(var(--glass-blur)) saturate(125%); -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(125%); text-align: center; text-shadow:0 1px 8px rgba(25,38,76,.26); }
.website-empty__icon { display: grid; width: 56px; height: 56px; place-items: center; color: #6682cb; border: 1px solid rgba(255,255,255,.76); border-radius: 17px; background: rgba(255,255,255,.54); }.website-empty h2 { margin: 17px 0 4px; font-size: 17px; }.website-empty p { margin: 0; color: rgba(255,255,255,.8); font-size: 12px; }.website-empty button { margin-top: 17px; padding: 8px 15px; color: #5070bf; border: 1px solid rgba(100,130,206,.24); border-radius: 9px; background: rgba(255,255,255,.7); font-size: 12px; font-weight: 650; }
.website-dialog-backdrop { position: fixed; z-index: 100; inset: 0; display: grid; place-items: center; padding: 18px; background: rgba(22,34,71,.42); backdrop-filter: blur(10px); }
.website-dialog { width: min(100%, 460px); padding: 23px; color: #263653; border: 1px solid rgba(255,255,255,.78); border-radius: 22px; background:var(--glass-dialog-background); box-shadow: 0 25px 75px rgba(14,27,72,.3), inset 0 1px 0 white;  backdrop-filter:var(--glass-overlay-filter); -webkit-backdrop-filter:var(--glass-overlay-filter); max-height:calc(100dvh - 40px); overflow-y:auto; }
.website-dialog__header { display: flex; justify-content: space-between; gap: 10px; margin-bottom: 20px; }.website-dialog__header span { color: #7e91bc; font-size: 9px; font-weight: 800; letter-spacing: .15em; }.website-dialog__header h2 { margin: 5px 0 4px; font-size: 23px; font-weight: 720; letter-spacing: -.025em; }.website-dialog__header p { margin: 0; color: #8493aa; font-size: 12px; }.website-dialog__header button { display: grid; width: 30px; height: 30px; flex: none; place-items: center; color: #6b7b97; border: 0; border-radius: 9px; background: rgba(218,227,246,.65); }
.website-dialog form { display: grid; gap: 13px; }.website-dialog label { display: grid; gap: 6px; min-width: 0; color: #4a5d7a; font-size: 11px; font-weight: 700; }.website-dialog input, .website-dialog select { width: 100%; min-width: 0; height: 40px; padding: 0 12px; color: #293b59; border: 1px solid rgba(151,171,212,.42); border-radius: 10px; outline: none; background: rgba(255,255,255,.78); font-size: 12px; }.website-dialog input:focus, .website-dialog select:focus { border-color: #849de4; box-shadow: 0 0 0 3px rgba(119,150,226,.13); }.website-dialog input::placeholder { color: #acb6c7; }.website-dialog__row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }.website-dialog__error { margin: 0; color: #c34655; font-size: 11px; }.website-dialog__actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 9px; }.website-dialog__actions button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 37px; padding: 0 15px; border-radius: 10px; font-size: 12px; font-weight: 680; }.website-dialog__cancel { color: #6d7e99; border: 1px solid rgba(160,177,211,.4); background: rgba(255,255,255,.6); }.website-dialog__submit { color: #fff; border: 1px solid rgba(92,119,200,.58); background: linear-gradient(120deg,#6988d9,#6e78cb); box-shadow: 0 6px 15px rgba(72,98,183,.22); }
.website-sort { position: relative; z-index: 30; flex: none; }
.website-sort__trigger { display: inline-flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 116px; height: 28px; padding: 0 9px; color: #4c67a5; border: 1px solid rgba(255,255,255,.62); border-radius: 9px; background: rgba(245,248,255,.84); box-shadow: inset 0 1px white, 0 3px 10px rgba(23,40,90,.12); font: inherit; font-size: 11px; cursor: pointer; }
.website-sort__trigger:hover, .website-sort__trigger[aria-expanded="true"] { background: rgba(255,255,255,.96); }
.website-sort__menu { position: absolute; top: calc(100% + 7px); right: 0; width: 148px; padding: 5px; border: 1px solid rgba(255,255,255,.72); border-radius: 12px; background:var(--glass-popover-background); box-shadow: 0 15px 34px rgba(16,33,82,.28),inset 0 1px white;   backdrop-filter:var(--glass-overlay-filter); -webkit-backdrop-filter:var(--glass-overlay-filter); }
.website-sort__menu button { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 8px 9px; color: #3b4f75; border: 0; border-radius: 8px; background: transparent; font: inherit; font-size: 11px; text-align: left; cursor: pointer; }
.website-sort__menu button:hover, .website-sort__menu .website-sort__option--selected { color: #3d5fb3; background: rgba(120,151,224,.18); }
.website-sort__trigger:focus-visible, .website-sort__menu button:focus-visible { outline: 2px solid #7798ea; outline-offset: 2px; }
.website-icon-field { display: grid; grid-template-columns: 1fr 44px; align-items: end; gap: 10px; }
.website-icon-preview { display: grid; width: 44px; height: 40px; place-items: center; overflow: hidden; color: #5c78c6; border: 1px solid rgba(151,171,212,.42); border-radius: 10px; background: rgba(255,255,255,.78); font-size: 18px; font-weight: 700; }
.website-icon-preview img { width: 27px; height: 27px; object-fit: contain; }
.website-icon-image { width: 30px; height: 30px; object-fit: contain; }
.website-category-form input, .website-dialog textarea { width: 100%; min-width: 0; padding: 10px 12px; color: #293b59; border: 1px solid rgba(151,171,212,.42); border-radius: 10px; background: rgba(255,255,255,.86); font: inherit; }
.website-category-form button { margin: 0; color: #fff; background: #6988d9; }
.website-dialog textarea { min-height: 68px; resize: vertical; }
.website-dialog .website-check { display: flex; align-items: center; gap: 8px; margin-top: 12px; }
.website-dialog .website-check input { width: 16px; height: 16px; }
.website-category-form { display: flex !important; gap: 8px; }
.website-category-row { display: flex; align-items: center; gap: 8px; margin-top: 10px; padding: 8px; border-radius: 10px; background: rgba(255,255,255,.6); font-size: 12px; }
.website-category-row span { flex: 1; }
.website-category-row button { padding: 5px 8px; color: #4c67a5; border: 0; background: transparent; cursor: pointer; }
.website-dialog__submit:disabled { opacity: .55; cursor: wait; }
@media (max-width: 1250px) { .website-grid { grid-template-columns: repeat(3,minmax(0,1fr)); } }
@media (max-width: 1000px) { .website-grid { grid-template-columns: repeat(2,minmax(0,1fr)); } .website-grid--list { grid-template-columns: 1fr; } }
@media (max-width: 640px) { .websites-page { padding: 0 2px 32px; }.website-toolbar { padding: 10px; margin-top: 4px; }.website-toolbar__top { flex-wrap: wrap; }.website-search { width: 100%; }.website-toolbar__right { width: 100%; justify-content: space-between; }.website-grid { grid-template-columns: 1fr; }.website-card__main { min-height: 76px; padding-block: 10px; }.website-card { min-height: 78px; } }
</style>
