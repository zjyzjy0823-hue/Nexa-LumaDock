<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, useId, watch } from 'vue'
import { inferSpaceTextTitle } from '../../services/spaceApi'
import { useSpaceStore } from '../../stores/space'
import SpacePasswordGate from '../space/SpacePasswordGate.vue'
import OpusIcon from '../ui/OpusIcon.vue'

const props = defineProps<{ active: boolean }>()
const emit = defineEmits<{ action: [message: string]; openShare: [spaceId?: string] }>()
const space = useSpaceStore()
const spaceId = ref('')
const body = ref('')
const file = ref<File | null>(null)
const filePicker = ref<HTMLInputElement>()
const saving = ref(false)
const passwordOpen = ref(false)
const error = ref('')
const target = computed(() => space.spaces.find(item => item.id === spaceId.value))
const spacePicker = ref<HTMLElement>()
const spacePickerTrigger = ref<HTMLButtonElement>()
const spaceMenuOpen = ref(false)
const spaceMenuId = useId()
const tierLabel = { standard: '普通', protected: '机密', e2ee: '极密' } as const
const canWrite = computed(() => {
  if (!target.value || space.deviceReadOnly) return false
  if (target.value.tier === 'standard' && space.usingReplica) return true
  return Boolean(space.route && !space.offline && !space.error)
})
const hasContent = computed(() => Boolean(file.value || body.value.trim()))
const emptyMessage = computed(() => {
  if (space.loading || space.waitingForConnection) return '正在读取共享空间…'
  return space.error || (space.route ? '还没有共享空间' : '共享空间暂未连接')
})

function clearDraft() {
  body.value = ''
  file.value = null
  error.value = ''
  passwordOpen.value = false
}

watch(() => space.spaces, spaces => {
  if (!spaces.some(item => item.id === spaceId.value)) {
    spaceId.value = (spaces.find(item => item.id === space.selectedSpaceId) ?? spaces[0])?.id ?? ''
  }
}, { immediate: true })

watch(target, (next, previous) => {
  if (next?.id === previous?.id) return
  if (previous && previous.tier !== 'standard') clearDraft()
  error.value = ''
  passwordOpen.value = false
})

watch([() => props.active, () => space.route, () => space.available], ([active, route], [, previousRoute]) => {
  if (route !== previousRoute) clearDraft()
  if (active) void space.loadSpaces()
  else {
    closeSpaceMenu()
    if (target.value?.tier !== 'standard') clearDraft()
  }
}, { immediate: true })

function closeSpaceMenu(restoreFocus = false) {
  spaceMenuOpen.value = false
  if (restoreFocus) spacePickerTrigger.value?.focus()
}

function toggleSpaceMenu() {
  if (spaceMenuOpen.value) {
    closeSpaceMenu(true)
    return
  }
  spaceMenuOpen.value = true
  void nextTick(() => {
    const selected = spacePicker.value?.querySelector<HTMLButtonElement>('.share-space-option[aria-pressed="true"]')
    const firstOption = spacePicker.value?.querySelector<HTMLButtonElement>('.share-space-option')
    const focused = selected ?? firstOption
    focused?.focus()
  })
}

function onSpaceMenuEscape(event: KeyboardEvent) {
  if (!spaceMenuOpen.value) return
  event.stopPropagation()
  closeSpaceMenu(true)
}

function onSpaceMenuPointer(event: PointerEvent) {
  if (spaceMenuOpen.value && event.target instanceof Node && !spacePicker.value?.contains(event.target)) closeSpaceMenu()
}

function onSpacePickerFocusOut(event: FocusEvent) {
  if (spaceMenuOpen.value && event.relatedTarget instanceof Node && !spacePicker.value?.contains(event.relatedTarget)) closeSpaceMenu()
}

function handleVisibility() {
  if (document.hidden && target.value?.tier !== 'standard') clearDraft()
}
onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibility)
  document.addEventListener('pointerdown', onSpaceMenuPointer)
})
onUnmounted(() => {
  document.removeEventListener('visibilitychange', handleVisibility)
  document.removeEventListener('pointerdown', onSpaceMenuPointer)
})

function pickFile(event: Event) {
  const input = event.target as HTMLInputElement
  const selected = input.files?.[0]
  input.value = ''
  if (!selected) return
  if (space.capabilities && selected.size > space.capabilities.maxFileBytes) {
    error.value = '文件大小超过共享空间上限。'
    return
  }
  error.value = ''
  file.value = selected
}

async function saveShare(password?: string) {
  const destination = target.value
  if (!destination || !canWrite.value || !hasContent.value || saving.value) return
  if (destination.tier !== 'standard' && !password) {
    error.value = ''
    passwordOpen.value = true
    return
  }
  const attachment = file.value
  const text = body.value
  const route = space.route
  saving.value = true
  error.value = ''
  try {
    await space.createEntry({
      spaceId: destination.id,
      entryType: attachment ? 'file' : 'text',
      title: attachment ? attachment.name.trim().slice(0, 200) || '未命名文件' : inferSpaceTextTitle(text),
      contentText: text,
      file: attachment ?? undefined,
      password,
    })
    clearDraft()
    emit('action', space.offline ? '已保存，联网后同步' : `已保存到「${destination.name}」`)
  } catch (cause) {
    if (space.route === route && target.value?.id === destination.id) {
      error.value = cause instanceof Error ? cause.message : '保存共享内容失败'
    }
  } finally {
    saving.value = false
  }
}

function closePassword() {
  if (saving.value) return
  passwordOpen.value = false
  error.value = ''
}
</script>

<template>
  <form v-show="active" class="quick-share" aria-label="新增共享内容" @submit.prevent="saveShare()">
    <div class="share-targets">
      <div ref="spacePicker" class="share-space-picker" @focusout="onSpacePickerFocusOut" @keydown.esc="onSpaceMenuEscape">
        <button ref="spacePickerTrigger" type="button" class="share-space-trigger" :aria-expanded="spaceMenuOpen"
          :aria-controls="spaceMenuOpen ? spaceMenuId : undefined" :disabled="!space.spaces.length || saving" @click="toggleSpaceMenu">
          <span class="share-space-mark"><OpusIcon :name="target && target.tier !== 'standard' ? 'lock' : 'folder'" /></span>
          <span class="share-space-label"><span>切换空间</span><strong>{{ target?.name || '选择空间' }}</strong></span>
          <OpusIcon name="chevD" class="share-space-chevron" />
        </button>
        <div v-if="spaceMenuOpen" :id="spaceMenuId" class="share-space-menu" role="group" aria-label="可选共享空间">
          <button v-for="item in space.spaces" :key="item.id" class="share-space-option" type="button"
            :aria-pressed="item.id === spaceId" @click="spaceId = item.id; closeSpaceMenu(true)">
            <OpusIcon :name="item.tier === 'standard' ? 'folder' : 'lock'" />
            <span class="share-space-option-name">{{ item.name }}</span>
            <span class="share-space-tier">{{ tierLabel[item.tier] }}</span>
            <OpusIcon v-if="item.id === spaceId" name="check" class="share-space-check" />
          </button>
        </div>
      </div>
      <input ref="filePicker" class="sr-only" type="file" tabindex="-1" aria-label="共享文件" @change="pickFile" />
      <button class="btn btn-ghost share-file-button" type="button" :disabled="!canWrite || saving"
        @click="filePicker?.click()"><OpusIcon name="file" />文件</button>
    </div>

    <div v-if="file" class="share-attachment">
      <OpusIcon name="file" />
      <span :title="file.name">{{ file.name }}</span>
      <button type="button" class="icon-btn" aria-label="移除文件" :disabled="saving" @click="file = null; error = ''">
        <OpusIcon name="x" />
      </button>
    </div>

    <textarea v-if="target" v-model="body" class="input share-text"
      :aria-label="file ? '文件备注' : '共享文本'" :placeholder="file ? '写一点备注（可选）' : '输入要共享的文本…'"
      :disabled="!canWrite || saving" @input="error = ''" />
    <div v-else class="share-placeholder">{{ emptyMessage }}</div>

    <p v-if="error && !passwordOpen" class="share-error" role="alert">{{ error }}</p>
    <p v-else-if="space.deviceReadOnly || (target && !canWrite) || (space.offline && target)" class="share-note" role="status">
      {{ space.deviceReadOnly ? '当前设备只读' : canWrite ? '离线保存，联网后同步' : '连接后可保存到此空间' }}
    </p>
    <div class="share-actions">
      <button class="btn btn-ghost" type="button" :disabled="saving" @click="emit('openShare', target?.id)">打开空间</button>
      <button class="btn btn-primary share-save" type="submit" :disabled="!canWrite || !hasContent || saving">
        {{ saving ? '保存中…' : '保存' }}
      </button>
    </div>
  </form>
  <Teleport to="body">
    <div @keydown.esc.stop="closePassword">
      <SpacePasswordGate :open="passwordOpen" :title="file ? '输入密码加密上传' : '输入密码加密保存'"
        :description="target?.name ?? ''" confirm-label="保存" :busy="saving" :error="error"
        @close="closePassword" @submit="saveShare" />
    </div>
  </Teleport>
</template>

<style scoped>
.quick-share { display: flex; flex: 1; flex-direction: column; gap: 10px; }
.share-targets { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.share-space-picker {
  position: relative;
  min-width: 0;
  max-width: min(76%, 280px);
}
.share-space-trigger {
  display: flex;
  align-items: center;
  gap: 9px;
  max-width: 100%;
  min-height: 49px;
  padding: 5px 10px 5px 6px;
  border: 1px solid var(--line-strong);
  border-radius: 13px;
  background: var(--surface-2);
  color: var(--text);
  text-align: start;
}
.share-space-trigger[aria-expanded="true"] { border-color: var(--accent-line); background: var(--solid); }
.share-space-mark {
  display: grid; place-items: center; flex: none;
  width: 32px; height: 32px; border-radius: 8px;
  background: var(--accent-soft); color: var(--accent);
}
.share-space-mark .i { width: 16px; height: 16px; }
.share-space-label { display: grid; min-width: 0; gap: 2px; }
.share-space-label > span { color: var(--text-2); font-size: 10px; }
.share-space-label strong, .share-space-option-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.share-space-label strong { font-size: 13px; }
.share-space-chevron { width: 13px; height: 13px; flex: none; color: var(--text-2); }
.share-space-menu {
  position: absolute;
  inset-block-start: calc(100% + 6px);
  inset-inline-start: 0;
  z-index: 2;
  width: max-content;
  min-width: max(100%, 190px);
  max-width: min(290px, calc(100vw - 48px));
  max-height: 200px;
  overflow: auto;
  padding: 5px;
  border: 1px solid var(--line-strong);
  border-radius: 13px;
  background: var(--solid);
  box-shadow: var(--shadow-pop);
}
.share-space-option {
  display: flex; align-items: center; gap: 8px;
  width: 100%; min-height: 40px; padding: 5px 8px;
  border-radius: 8px; color: var(--text); font-size: 13px; text-align: start;
}
.share-space-option[aria-pressed="true"], .share-space-option:hover { background: var(--accent-soft); }
.share-space-option .i { width: 14px; height: 14px; flex: none; }
.share-space-option-name { flex: 1; }
.share-space-tier { color: var(--text-2); font-size: 11px; white-space: nowrap; }
.share-space-check { color: var(--accent); }
.share-file-button { flex: none; min-height: 42px; padding-inline: 11px; border: 1px solid var(--line); border-radius: 11px; }
.share-file-button .i { width: 16px; height: 16px; }
.share-text, .share-placeholder {
  flex: 1;
  min-height: 116px;
  padding: 13px 14px;
  border: 1px solid var(--line-strong);
  border-radius: 14px;
  background: var(--surface-2);
  font-size: 16px;
  line-height: 1.6;
  resize: none;
}
.share-placeholder { display: grid; place-items: center; color: var(--text-2); font-size: 13px; text-align: center; }
.share-attachment { display: flex; align-items: center; gap: 8px; padding-inline-start: 10px; border: 1px solid var(--line); border-radius: 10px; font-size: 13px; }
.share-attachment > .i { width: 16px; height: 16px; flex: none; color: var(--text-2); }
.share-attachment span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.share-actions { display: flex; justify-content: space-between; gap: 12px; }
.share-actions .btn { min-height: 42px; }
.share-save { min-width: 92px; }
.share-note, .share-error { margin: 0; font-size: 12px; }
.share-note { color: var(--text-2); }
.share-error { color: var(--danger); }
</style>
