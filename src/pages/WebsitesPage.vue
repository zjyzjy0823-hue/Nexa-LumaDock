<script setup lang="ts">
import { confirmAction } from '../composables/useConfirm'
import { useCopyFeedback } from '../composables/useCopyFeedback'
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import ExternalLinkButton from '../components/ui/ExternalLink.vue'
import OpusIcon from '../components/ui/OpusIcon.vue'
import Modal from '../components/ui/Modal.vue'
import { useAuthStore } from '../stores/auth'
import { isAndroidLocal } from '../desktop/androidLocal'
import { useWebsitesStore } from '../stores/websites'
import type { Website } from '../types/website'

const props = defineProps<{ mobile?: boolean; search?: string }>()
const emit = defineEmits<{ action: [message: string] }>()
const auth = useAuthStore()
const websiteToken = computed(() => auth.token ?? (isAndroidLocal() ? '' : null))
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
const colors = ['var(--series-1, #6564ed)', '#24a483', '#ec935f', '#dd6e91', 'var(--series-5, #78a9e6)', '#8e9d64']
const listView = ref(false)
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
const failedIconIds = ref<Record<string, boolean>>({})
const iconPreviewUrl = computed(() => /^https?:\/\//i.test(form.icon.trim()) ? form.icon.trim() : '')

function hasValidIcon(item: Website): boolean {
  return Boolean(item.icon && /^https?:\/\//i.test(item.icon) && !failedIconIds.value[item.id])
}

function markIconFailed(id: string) {
  failedIconIds.value = { ...failedIconIds.value, [id]: true }
}
watch(() => store.websites, () => { failedIconIds.value = {} })
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
function refresh() {
  if (websiteToken.value === null) return
  store.load(websiteToken.value, { categoryId: selectedCategory.value === 'all' ? undefined : selectedCategory.value,
    search: query.value.trim(), favorite: onlyFavorites.value ? true : undefined, sort: sort.value })
}
function openWebsite(item: Website) {
  openMenuId.value = null
  if (websiteToken.value !== null) void store.visit(websiteToken.value, item.id).catch(() => {})
}
let searchTimer: ReturnType<typeof setTimeout> | undefined
watch([selectedCategory, onlyFavorites, sort], refresh)
if (isAndroidLocal()) watch(() => store.revision, refresh)
watch(() => props.search, value => { query.value = value ?? '' }, { immediate: true })
watch(query, () => { if (searchTimer) clearTimeout(searchTimer); searchTimer = setTimeout(refresh, 250) })

function openDialog(item?: Website) {
  if (websiteToken.value === null) { emit('action', '请先登录。'); return }
  openMenuId.value = null; editingId.value = item?.id ?? null; dialogMode.value = item ? 'edit' : 'add'; formError.value = ''
  Object.assign(form, { name: item?.name ?? '', url: item?.url ?? '', icon: item?.icon ?? '', description: item?.description ?? '',
    categoryId: item?.categoryId ?? '', favorite: item?.favorite ?? false, order: item?.order ?? (Math.max(-1, ...store.websites.map(site => site.order)) + 1) })
  autoIconValue.value = ''
  iconPreviewFailed.value = false
}
defineExpose({ openCreate: (value?: string) => {
  openDialog()
  if (value) {
    form.url = value
    form.name = value.replace(/^https?:\/\//i, '').split(/[/:]/)[0] ?? ''
  }
} })
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
  if (websiteToken.value === null) return
  saving.value = true; formError.value = ''
  try {
    const data = { name, url, icon: form.icon.trim() || null, description: form.description.trim() || null,
      categoryId: form.categoryId || null, favorite: form.favorite, order: form.order }
    if (editingId.value) await store.update(websiteToken.value, editingId.value, data)
    else await store.create(websiteToken.value, data)
    emit('action', editingId.value ? `已更新「${name}」。` : `已添加「${name}」。`)
    dialogMode.value = null; selectedCategory.value = 'all'; query.value = ''; refresh()
  } catch (error) { formError.value = error instanceof Error ? error.message : '保存失败' }
  finally { saving.value = false }
}
async function removeWebsite(item: Website) {
  openMenuId.value = null
  if (websiteToken.value === null || !(await confirmAction(`删除「${item.name}」？`))) return
  try { await store.remove(websiteToken.value, item.id); emit('action', `已删除「${item.name}」。`) }
  catch (error) { emit('action', error instanceof Error ? error.message : '删除失败') }
}
async function toggleFavorite(item: Website) {
  openMenuId.value = null
  if (websiteToken.value === null) return
  try { await store.update(websiteToken.value, item.id, { favorite: !item.favorite }); refresh(); emit('action', item.favorite ? '已取消收藏。' : '已收藏。') }
  catch (error) { emit('action', error instanceof Error ? error.message : '操作失败') }
}
async function moveWebsite(item: Website, direction: -1 | 1) {
  if (websiteToken.value === null || selectedCategory.value !== 'all' || query.value || onlyFavorites.value || sort.value !== 'order') return
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
      if (sorted[position].order !== position) await store.update(websiteToken.value, sorted[position].id, { order: position })
    }
    sort.value = 'order'; refresh(); emit('action', '网站顺序已更新。')
  } catch (error) { emit('action', error instanceof Error ? error.message : '排序失败'); refresh() }
}
async function saveCategory() {
  if (websiteToken.value === null || !categoryName.value.trim()) { categoryError.value = '请输入分类名称。'; return }
  try {
    if (editingCategoryId.value) await store.renameCategory(websiteToken.value, editingCategoryId.value, categoryName.value.trim())
    else await store.createCategory(websiteToken.value, categoryName.value.trim())
    editingCategoryId.value = null; categoryName.value = ''; categoryError.value = ''; emit('action', '分类已保存。')
  }
  catch (error) { categoryError.value = error instanceof Error ? error.message : '保存失败' }
}
function renameCategory(id: string, oldName: string) {
  editingCategoryId.value = id; categoryName.value = oldName; categoryError.value = ''
}
async function removeCategory(id: string, name: string) {
  if (websiteToken.value === null || !(await confirmAction(`删除分类「${name}」？其中的网站会保留。`))) return
  try { await store.removeCategory(websiteToken.value, id); if (selectedCategory.value === id) selectedCategory.value = 'all'; emit('action', '分类已删除。') }
  catch (error) { categoryError.value = error instanceof Error ? error.message : '删除失败' }
}
const { copy: copyWithFeedback, isCopied } = useCopyFeedback()
let menuCloseTimer: ReturnType<typeof setTimeout> | undefined

async function copyLink(item: Website) {
  const ok = await copyWithFeedback(item.url, `site-${item.id}`)
  if (ok) {
    emit('action', `已复制「${item.name}」的网址。`)
    if (menuCloseTimer) clearTimeout(menuCloseTimer)
    menuCloseTimer = setTimeout(() => {
      if (openMenuId.value === item.id) openMenuId.value = null
    }, 550)
  } else {
    openMenuId.value = null
    emit('action', '复制失败，请检查浏览器权限。')
  }
}
function onDocumentPointerDown(event: PointerEvent) {
  if (!(event.target as Element).closest('[data-website-menu]')) openMenuId.value = null
  if (!(event.target as Element).closest('[data-website-sort]')) sortOpen.value = false
}
function onDocumentKeydown(event: KeyboardEvent) { if (event.key === 'Escape') { openMenuId.value = null; sortOpen.value = false } }
onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointerDown); document.addEventListener('keydown', onDocumentKeydown)
  refresh()
})
onUnmounted(() => { document.removeEventListener('pointerdown', onDocumentPointerDown); document.removeEventListener('keydown', onDocumentKeydown); if (searchTimer) clearTimeout(searchTimer); if (faviconTimer) clearTimeout(faviconTimer); if (menuCloseTimer) clearTimeout(menuCloseTimer); faviconSequence++ })
</script>

<template>
  <div class="websites-page">
    <header v-if="!mobile" class="ph"><div><h1>网站</h1><div class="sub">{{ store.websites.length }} 个收藏 · 手机分享的链接也会出现在这里</div></div>
      <div class="actions"><button class="icon-btn" type="button" aria-label="网站选项" :aria-expanded="sortOpen" data-website-sort @click="sortOpen = !sortOpen"><OpusIcon name="more" /></button><button class="btn btn-primary" type="button" @click="openDialog()"><OpusIcon name="plus" />收藏网站</button></div>
    </header>
    <div v-if="!mobile" style="display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap">
      <button v-for="item in websiteCategories" :key="item.id" class="chip" type="button" :aria-pressed="selectedCategory === item.id" @click="selectedCategory = item.id">{{ item.name }}</button>
    </div>
    <div v-if="sortOpen" data-website-sort class="toolbar card mat enter" style="margin-bottom:14px;border-radius:var(--r-lg)">
      <div class="search"><OpusIcon name="search" /><input v-model="query" class="input" type="search" placeholder="搜索网站" aria-label="搜索网站"></div>
      <select v-model="sort" class="input" style="width:auto;height:30px" aria-label="排序"><option v-for="item in sortOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select>
      <button class="btn btn-ghost btn-sm" type="button" :aria-pressed="onlyFavorites" @click="onlyFavorites = !onlyFavorites">仅收藏</button>
      <button class="btn btn-ghost btn-sm" type="button" @click="listView = !listView">{{ listView ? '网格' : '列表' }}</button>
      <button class="btn btn-ghost btn-sm" type="button" @click="categoryDialog = true">管理分类</button>
    </div>
    <div v-if="store.loading" class="cleared" role="status">正在加载网站…</div>
    <div v-else-if="store.error" class="notice danger" role="alert">{{ store.error }} <button class="btn btn-ghost btn-sm" type="button" @click="refresh">重试</button></div>
    <div v-else-if="store.websites.length" :class="mobile || listView ? 'mlist mat-solid' : 'web-grid'">
      <article v-for="(item, i) in store.websites" :key="item.id" class="opus-site-item" :class="{ 'opus-site-item--open': openMenuId === item.id, 'opus-site-item--list': mobile || listView }">
        <ExternalLinkButton :href="item.url" :class="mobile || listView ? 'mrow' : 'web-card mat'" :aria-label="'打开 ' + item.name" @activate="openWebsite(item)" @action="emit('action', $event)">
          <span
            v-if="mobile || listView"
            class="fav"
            :class="{ 'fav--img': hasValidIcon(item) }"
            :style="{ width: '36px', height: '36px', borderRadius: '11px', background: hasValidIcon(item) ? undefined : colors[i % colors.length] }"
          ><img v-if="hasValidIcon(item)" class="opus-favicon" :src="item.icon ?? undefined" alt="" @error="markIconFailed(item.id)"><template v-else>{{ item.name[0] }}</template></span>
          <span v-if="mobile || listView" class="grow"><div class="title">{{ item.name }}</div><div class="sub">{{ item.url }}</div></span>
          <template v-else>
            <div class="top"><span
              class="fav"
              :class="{ 'fav--img': hasValidIcon(item) }"
              :style="{ width: '36px', height: '36px', borderRadius: '10px', background: hasValidIcon(item) ? undefined : colors[i % colors.length] }"
            ><img v-if="hasValidIcon(item)" class="opus-favicon" :src="item.icon ?? undefined" alt="" @error="markIconFailed(item.id)"><template v-else>{{ item.name[0] }}</template></span><div style="min-width:0"><div style="font-weight:600">{{ item.name }}</div><div class="faint" style="font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ item.url }}</div></div></div>
            <div class="foot"><span class="chip">{{ store.categories.find(category => category.id === item.categoryId)?.name ?? '未分类' }}</span><span>{{ item.lastVisitedAt ? '最近访问 ' + new Date(item.lastVisitedAt).toLocaleDateString('zh-CN') : '尚未访问' }}</span><span v-if="item.favorite" class="faint" style="margin-left:auto">★ 已收藏</span></div>
          </template>
        </ExternalLinkButton>
        <div class="opus-site-menu" data-website-menu>
          <button class="icon-btn" type="button" :aria-label="item.name + ' 更多操作'" :aria-expanded="openMenuId === item.id" @click="openMenuId = openMenuId === item.id ? null : item.id"><OpusIcon name="more" /></button>
          <div v-if="openMenuId === item.id" class="website-menu mat-solid enter">
            <button class="row" :class="{ 'is-copied': isCopied(`site-${item.id}`) }" type="button" @click="copyLink(item)"><OpusIcon :name="isCopied(`site-${item.id}`) ? 'check' : 'copy'" />{{ isCopied(`site-${item.id}`) ? '已复制' : '复制链接' }}</button>
            <button class="row" type="button" @click="openDialog(item)">编辑网站</button>
            <button class="row" type="button" @click="toggleFavorite(item)">{{ item.favorite ? '取消收藏' : '收藏网站' }}</button>
            <button class="row" type="button" :disabled="selectedCategory !== 'all' || !!query || onlyFavorites || sort !== 'order'" @click="moveWebsite(item, -1)">上移</button>
            <button class="row" type="button" :disabled="selectedCategory !== 'all' || !!query || onlyFavorites || sort !== 'order'" @click="moveWebsite(item, 1)">下移</button>
            <button class="row" style="color:var(--danger)" type="button" @click="removeWebsite(item)">删除网站</button>
          </div>
        </div>
      </article>
    </div>
    <div v-else class="cleared"><OpusIcon name="globe" />{{ query || selectedCategory !== 'all' ? '没有找到相关网站' : '还没有网站' }}<button v-if="!mobile" class="btn btn-sm btn-ghost" type="button" @click="clearOrCreate">{{ query || selectedCategory !== 'all' || onlyFavorites ? '清除筛选' : '收藏网站' }}</button></div>

    <Modal :open="!!dialogMode" :title="dialogMode === 'add' ? '添加网站' : '编辑网站'" @close="closeDialog">
      <form id="website-form" @submit.prevent="saveWebsite">
        <div class="field"><label for="site-name">网站名称</label><input id="site-name" v-model="form.name" class="input" maxlength="120" placeholder="例如：我的工作台" required data-initial-focus /></div>
        <div class="field"><label for="site-url">网址</label><input id="site-url" v-model="form.url" class="input" type="text" inputmode="url" placeholder="https://example.com" required /></div>
        <div class="website-icon-field">
          <div class="field"><label for="site-icon">图标（自动获取，也可手动修改）</label><input id="site-icon" v-model="form.icon" class="input" maxlength="500" placeholder="输入网址后自动获取 favicon" /></div>
          <span class="website-icon-preview" aria-label="图标预览">
            <img v-if="iconPreviewUrl && !iconPreviewFailed" :src="iconPreviewUrl" alt="" @error="iconPreviewFailed = true" />
            <span v-else>{{ form.name.trim().slice(0, 1).toUpperCase() || '✦' }}</span>
          </span>
        </div>
        <div class="field"><label for="site-desc">简介</label><textarea id="site-desc" v-model="form.description" class="input" maxlength="500" placeholder="用一句话描述这个网站" /></div>
        <div class="field-grid" style="align-items:end">
          <div class="field"><label for="site-cat">分类</label><select id="site-cat" v-model="form.categoryId" class="input"><option value="">未分类</option><option v-for="category in store.categories" :key="category.id" :value="category.id">{{ category.name }}</option></select></div>
          <label class="dlg-check" style="height:36px"><input v-model="form.favorite" type="checkbox" /> 设为收藏</label>
        </div>
        <p v-if="formError" class="dlg-error" role="alert">{{ formError }}</p>
      </form>
      <template #footer>
        <button type="button" class="btn btn-ghost" :disabled="saving" @click="closeDialog">取消</button>
        <button type="submit" form="website-form" class="btn btn-primary" :disabled="saving"><OpusIcon name="check" />{{ saving ? '保存中…' : dialogMode === 'add' ? '添加网站' : '保存修改' }}</button>
      </template>
    </Modal>

    <Modal :open="categoryDialog" title="管理分类" @close="categoryDialog = false">
      <form class="website-category-form" @submit.prevent="saveCategory">
        <input v-model="categoryName" class="input" maxlength="80" aria-label="分类名称" :placeholder="editingCategoryId ? '分类名称' : '新分类名称'" data-initial-focus />
        <button class="btn btn-primary" type="submit">{{ editingCategoryId ? '保存' : '添加' }}</button>
        <button v-if="editingCategoryId" class="btn btn-ghost" type="button" @click="editingCategoryId = null; categoryName = ''">取消</button>
      </form>
      <p v-if="categoryError" class="dlg-error" role="alert">{{ categoryError }}</p>
      <div class="list" style="margin-top:8px">
        <div v-for="category in store.categories" :key="category.id" class="row"><span class="grow">{{ category.name }}</span><button class="btn btn-sm btn-subtle" type="button" @click="renameCategory(category.id, category.name)">重命名</button><button class="btn btn-sm btn-danger" type="button" @click="removeCategory(category.id, category.name)">删除</button></div>
        <div v-if="!store.categories.length" class="faint" style="padding:12px 0;font-size:12.5px">暂无自定义分类</div>
      </div>
    </Modal>
  </div>
</template>

<style scoped>
.opus-site-item { position: relative; min-width: 0; }
.opus-site-item + .opus-site-item { border-top: 0; }
.opus-site-item--list + .opus-site-item--list { border-top: 1px solid var(--line); }
.opus-site-item > a { width: 100%; }
.opus-site-item > .web-card { display: block; }
.opus-site-item--open { z-index: 3; }
.opus-site-menu { position: absolute; top: 8px; right: 8px; opacity: 0; transition: opacity var(--dur-1); }
.opus-site-item:hover .opus-site-menu,
.opus-site-item:focus-within .opus-site-menu,
.opus-site-item--open .opus-site-menu,
.opus-site-item--list .opus-site-menu { opacity: 1; }
.opus-site-item--list .opus-site-menu { top: 50%; translate: 0 -50%; right: 10px; }
.opus-site-item .top, .opus-site-item .mrow { padding-right: 36px; }
.website-menu { position: absolute; z-index: 10; top: 100%; right: 0; min-width: 132px; padding: 4px; border-radius: var(--r-md); border: 1px solid var(--line-strong); background: color-mix(in srgb, var(--solid) 97%, transparent); backdrop-filter: var(--material-filter); -webkit-backdrop-filter: var(--material-filter); box-shadow: var(--shadow-2); }
.website-menu .row { width: 100%; }
.website-icon-field { display: grid; grid-template-columns: 1fr 40px; align-items: end; gap: 10px; }
.fav--img { padding: 5px; background: #ffffff; border: 1px solid var(--line); overflow: hidden; }
.website-icon-preview { display: grid; width: 40px; height: 36px; place-items: center; overflow: hidden; color: var(--accent); border: 1px solid var(--line-strong); border-radius: var(--r-sm); background: #ffffff; font-size: 16px; font-weight: 700; }
.website-icon-preview img { width: 22px; height: 22px; object-fit: contain; }
.website-category-form { display: flex; gap: 8px; }
.website-category-form .input { flex: 1; }
@media (hover: none) { .opus-site-menu { opacity: 1; } }
</style>
