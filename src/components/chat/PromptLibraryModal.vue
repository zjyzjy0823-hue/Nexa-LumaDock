<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { CustomPromptTemplate } from '../../services/customPrompts'
import OpusIcon from '../ui/OpusIcon.vue'

const props = defineProps<{
  open: boolean
  prompts: CustomPromptTemplate[]
}>()

const emit = defineEmits<{
  close: []
  save: [payload: { id?: string; trigger: string; title: string; description: string; template: string }]
  remove: [id: string]
  usePrompt: [template: string]
}>()

const dialogEl = ref<HTMLDialogElement | null>(null)
const triggerInputEl = ref<HTMLInputElement | null>(null)
const editingId = ref<string | undefined>(undefined)
const trigger = ref('')
const title = ref('')
const description = ref('')
const template = ref('')
const formErr = ref('')

watch(
  () => props.open,
  async (val) => {
    const dlg = dialogEl.value
    if (!dlg) return
    if (val) {
      resetForm()
      if (!dlg.open) dlg.showModal()
      await nextTick()
      triggerInputEl.value?.focus()
    } else if (dlg.open) {
      dlg.close()
    }
  },
)

function resetForm() {
  editingId.value = undefined
  trigger.value = ''
  title.value = ''
  description.value = ''
  template.value = ''
  formErr.value = ''
}

function editItem(item: CustomPromptTemplate) {
  editingId.value = item.id
  trigger.value = item.trigger
  title.value = item.title
  description.value = item.description
  template.value = item.template
  formErr.value = ''
}

function submitForm() {
  const cleanTrig = trigger.value.trim().replace(/^\/+/, '')
  const cleanTpl = template.value.trim()
  if (!cleanTrig || !cleanTpl) {
    formErr.value = '请填写斜杠触发词（如 audit）和模板正文'
    return
  }
  emit('save', {
    id: editingId.value,
    trigger: cleanTrig,
    title: title.value.trim() || `/${cleanTrig}`,
    description: description.value.trim() || cleanTpl.slice(0, 48),
    template: cleanTpl,
  })
  resetForm()
}

function onDialogClick(ev: MouseEvent) {
  if (ev.target === dialogEl.value) emit('close')
}

function onNativeClose() {
  if (dialogEl.value) dialogEl.value.returnValue = ''
  if (props.open) emit('close')
}
</script>

<template>
  <dialog
    ref="dialogEl"
    class="pl-dialog"
    aria-labelledby="pl-dialog-title"
    closedby="any"
    @close="onNativeClose"
    @click="onDialogClick"
  >
    <div class="pl-shell">
      <header class="pl-hdr">
        <div class="pl-title-wrap">
          <OpusIcon name="zap" class="pl-ic" />
          <h2 id="pl-dialog-title">自定义斜杠指令模板 (/prompts)</h2>
        </div>
        <button type="button" class="icon-btn" aria-label="关闭模板弹窗" @click="emit('close')">
          <OpusIcon name="x" />
        </button>
      </header>

      <div class="pl-body">
        <form class="pl-form" @submit.prevent="submitForm">
          <div class="pl-row">
            <div class="pl-col">
              <label for="pl-trig">斜杠名称（输入 / 可触发）</label>
              <input id="pl-trig" ref="triggerInputEl" v-model="trigger" autofocus class="input" placeholder="例如 security-audit">
            </div>
            <div class="pl-col">
              <label for="pl-title">展示标题</label>
              <input id="pl-title" v-model="title" class="input" placeholder="例如 安全审计检查">
            </div>
          </div>
          <label for="pl-desc">简短说明</label>
          <input id="pl-desc" v-model="description" class="input" placeholder="一句话说明模板用途">
          <label for="pl-tpl">提示词正文（支持自定义占位或前置约束）</label>
          <textarea id="pl-tpl" v-model="template" class="input" rows="4" placeholder="请从输入校验、权限边界与并发安全角度逐项检查：" />
          <p v-if="formErr" class="pl-err" role="alert">{{ formErr }}</p>
          <div class="pl-form-foot">
            <button v-if="editingId" type="button" class="btn btn-ghost btn-sm" @click="resetForm">取消编辑</button>
            <button type="submit" class="btn btn-primary btn-sm">{{ editingId ? '保存修改' : '添加模板' }}</button>
          </div>
        </form>

        <div class="pl-list">
          <p v-if="!prompts.length" class="faint" style="font-size:12px;margin:8px 0">
            暂未创建自定义模板；添加后在输入框键入 <code>/</code> 或进入 <code>+</code> 菜单即可快速调用。
          </p>
          <div v-for="item in prompts" :key="item.id" class="pl-card">
            <div class="pl-card-top">
              <code class="pl-trig-badge">{{ item.trigger }}</code>
              <strong class="pl-card-title">{{ item.title }}</strong>
              <span class="spacer" />
              <button type="button" class="btn btn-subtle btn-sm" @click="emit('usePrompt', item.template); emit('close')">使用</button>
              <button type="button" class="icon-btn" aria-label="编辑模板" @click="editItem(item)"><OpusIcon name="pencil" /></button>
              <button type="button" class="icon-btn" aria-label="删除模板" @click="emit('remove', item.id)"><OpusIcon name="trash" /></button>
            </div>
            <p class="pl-card-desc faint">{{ item.description }}</p>
          </div>
        </div>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
.pl-dialog {
  margin: auto;
  padding: 0;
  width: min(620px, 92vw);
  max-height: 82vh;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-lg);
  background: var(--surface-1);
  color: var(--text);
  box-shadow: var(--shadow-pop);
}
dialog.pl-dialog:modal { overscroll-behavior: contain; }
dialog.pl-dialog::backdrop {
  background: rgba(15, 23, 42, 0.48);
  overflow: hidden;
  overscroll-behavior: contain;
}
.pl-shell { display: flex; flex-direction: column; max-height: 82vh; }
.pl-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
}
.pl-title-wrap { display: flex; align-items: center; gap: 7px; }
.pl-ic { width: 16px; height: 16px; color: var(--accent); }
.pl-hdr h2 { margin: 0; font-size: 14px; font-weight: 620; }
.pl-body { padding: 12px 14px; overflow: auto; display: grid; gap: 14px; }
.pl-form { display: grid; gap: 6px; padding-bottom: 12px; border-bottom: 1px solid var(--line); font-size: 12px; }
.pl-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.pl-col { display: grid; gap: 4px; }
.pl-err { margin: 0; font-size: 11.5px; color: var(--warn); }
.pl-form-foot { display: flex; justify-content: flex-end; gap: 6px; margin-top: 2px; }
.pl-list { display: grid; gap: 8px; }
.pl-card {
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface-2);
  display: grid;
  gap: 4px;
}
.pl-card-top { display: flex; align-items: center; gap: 6px; }
.pl-trig-badge { padding: 1px 6px; border-radius: 5px; background: var(--accent-soft); color: var(--accent); font-size: 11.5px; }
.pl-card-title { font-size: 12.5px; }
.pl-card-desc { margin: 0; font-size: 11.5px; }
</style>
