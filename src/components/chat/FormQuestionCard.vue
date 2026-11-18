<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { FormFieldSchema, MessageFormRequest } from '../../types/fleet'
import OpusIcon from '../ui/OpusIcon.vue'

const props = defineProps<{
  form: MessageFormRequest
}>()

const emit = defineEmits<{
  submit: [formId: string, answer: Record<string, unknown>]
  cancel: [formId: string]
}>()

const draft = reactive<Record<string, unknown>>({})
const validationError = ref('')

watch(
  () => props.form.formId,
  () => {
    for (const key of Object.keys(draft)) {
      delete draft[key]
    }
    for (const f of props.form.fields) {
      if (f.type === 'boolean') {
        draft[f.key] = typeof f.default === 'boolean' ? f.default : false
      } else if (f.type === 'multiselect') {
        draft[f.key] = Array.isArray(f.default) ? [...f.default] : []
      } else if (f.default !== undefined && f.default !== null) {
        draft[f.key] = f.default
      } else {
        draft[f.key] = ''
      }
    }
    validationError.value = ''
  },
  { immediate: true },
)

const isPending = computed(() => props.form.status === 'pending')

function isFieldVisible(field: FormFieldSchema): boolean {
  if (field.hidden) return false
  if (!field.when) return true
  const cur = draft[field.when.key]
  return field.when.op === 'eq' ? cur === field.when.value : cur !== field.when.value
}

const visibleFields = computed(() => props.form.fields.filter(isFieldVisible))

function toggleMultiOption(fieldKey: string, val: string) {
  if (!isPending.value) return
  const cur = Array.isArray(draft[fieldKey]) ? [...(draft[fieldKey] as unknown[])] : []
  const idx = cur.indexOf(val)
  if (idx >= 0) cur.splice(idx, 1)
  else cur.push(val)
  draft[fieldKey] = cur
}

function isMultiSelected(fieldKey: string, val: string): boolean {
  return Array.isArray(draft[fieldKey]) && (draft[fieldKey] as unknown[]).includes(val)
}

function safeExternalHref(raw?: string): string | null {
  if (!raw) return null
  try {
    const parsed = new URL(raw)
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.toString() : null
  } catch {
    return null
  }
}

function submitForm() {
  if (!isPending.value) return
  validationError.value = ''
  const payload: Record<string, unknown> = {}

  for (const field of visibleFields.value) {
    if (field.type === 'external') continue
    const val = draft[field.key]
    if (field.required) {
      const emptyStr = typeof val === 'string' && !val.trim()
      const emptyArr = Array.isArray(val) && val.length === 0
      if (val === undefined || val === null || emptyStr || emptyArr) {
        validationError.value = `请填写「${field.title || field.key}」`
        return
      }
    }
    if (field.type === 'number' || field.type === 'integer') {
      if (val !== '' && val !== undefined && val !== null) {
        const num = Number(val)
        if (Number.isNaN(num)) {
          validationError.value = `「${field.title || field.key}」必须为有效数字`
          return
        }
        payload[field.key] = field.type === 'integer' ? Math.trunc(num) : num
      }
      continue
    }
    if (field.type === 'multiselect') {
      const arr = Array.isArray(val) ? val : []
      if (field.minItems && arr.length < field.minItems) {
        validationError.value = `「${field.title || field.key}」至少选择 ${field.minItems} 项`
        return
      }
      payload[field.key] = arr
      continue
    }
    payload[field.key] = val
  }

  emit('submit', props.form.formId, payload)
}
</script>

<template>
  <section class="form-card" :class="`is-${form.status}`" :aria-label="form.title || '智能体确认表单'">
    <header class="form-card-hdr">
      <OpusIcon name="tasks" class="form-card-ic" />
      <span class="form-card-title">{{ form.title }}</span>
      <span v-if="form.status === 'submitted'" class="form-badge is-ok">
        <OpusIcon name="check" />
        <span>已提交</span>
      </span>
      <span v-else-if="form.status === 'cancelled'" class="form-badge is-cancel">
        <span>已跳过</span>
      </span>
      <span v-else class="form-badge is-pending">待确认</span>
    </header>

    <form v-if="isPending" class="form-body" @submit.prevent="submitForm">
      <div v-for="field in visibleFields" :key="field.key" class="form-field">
        <label v-if="field.type !== 'external'" class="form-label" :for="`fld-${form.formId}-${field.key}`">
          <span>{{ field.title || field.key }}</span>
          <span v-if="field.required" class="form-req" aria-hidden="true">*</span>
        </label>
        <p v-if="field.description" class="form-desc">{{ field.description }}</p>

        <!-- 单选预设选项（带可选自定义输入） -->
        <template v-if="field.type === 'string' && field.options?.length">
          <div class="form-options" role="radiogroup" :aria-label="field.title || field.key">
            <button
              v-for="opt in field.options"
              :key="opt.value"
              type="button"
              class="form-opt-btn"
              :class="{ 'is-active': draft[field.key] === opt.value }"
              :title="opt.description || opt.label"
              @click="draft[field.key] = opt.value"
            >
              <span class="form-opt-lbl">{{ opt.label }}</span>
              <span v-if="opt.description" class="form-opt-sub">{{ opt.description }}</span>
            </button>
          </div>
          <input
            v-if="field.custom"
            :id="`fld-${form.formId}-${field.key}`"
            v-model="draft[field.key]"
            type="text"
            class="form-input form-input--custom"
            :placeholder="field.placeholder || '或输入自定义值…'"
          >
        </template>

        <!-- 多选标签（带可选补充自定义输入） -->
        <template v-else-if="field.type === 'multiselect'">
          <div class="form-options" role="group" :aria-label="field.title || field.key">
            <button
              v-for="opt in field.options || []"
              :key="opt.value"
              type="button"
              class="form-opt-btn"
              :class="{ 'is-active': isMultiSelected(field.key, opt.value) }"
              :aria-pressed="isMultiSelected(field.key, opt.value)"
              @click="toggleMultiOption(field.key, opt.value)"
            >
              <OpusIcon v-if="isMultiSelected(field.key, opt.value)" name="check" class="form-opt-ck" />
              <span class="form-opt-lbl">{{ opt.label }}</span>
            </button>
          </div>
        </template>

        <!-- 布尔确认开关 -->
        <template v-else-if="field.type === 'boolean'">
          <div class="form-bool-row">
            <button
              type="button"
              class="form-opt-btn"
              :class="{ 'is-active': draft[field.key] === true }"
              @click="draft[field.key] = true"
            >
              是
            </button>
            <button
              type="button"
              class="form-opt-btn"
              :class="{ 'is-active': draft[field.key] === false }"
              @click="draft[field.key] = false"
            >
              否
            </button>
          </div>
        </template>

        <!-- 数值输入 -->
        <template v-else-if="field.type === 'number' || field.type === 'integer'">
          <input
            :id="`fld-${form.formId}-${field.key}`"
            v-model="draft[field.key]"
            type="number"
            class="form-input"
            :min="field.minimum"
            :max="field.maximum"
            :step="field.type === 'integer' ? 1 : 'any'"
            :placeholder="field.placeholder"
            :required="field.required"
          >
        </template>

        <!-- 外部跳转鉴权或补充说明 -->
        <template v-else-if="field.type === 'external'">
          <a
            v-if="safeExternalHref(field.url)"
            :href="safeExternalHref(field.url)!"
            target="_blank"
            rel="noopener noreferrer"
            class="btn btn-subtle btn-sm form-ext-link"
          >
            <OpusIcon name="external" />
            <span>{{ field.title || '打开外部链接完成操作' }}</span>
          </a>
        </template>

        <!-- 文本/密码输入 -->
        <template v-else>
          <input
            :id="`fld-${form.formId}-${field.key}`"
            v-model="draft[field.key]"
            :type="field.format === 'password' ? 'password' : 'text'"
            class="form-input"
            :placeholder="field.placeholder || '请输入…'"
            :required="field.required"
          >
        </template>
      </div>

      <p v-if="validationError" class="form-err" role="alert">{{ validationError }}</p>

      <div class="form-actions">
        <button type="button" class="btn btn-subtle btn-sm" @click="emit('cancel', form.formId)">跳过</button>
        <button type="submit" class="btn btn-primary btn-sm">
          <OpusIcon name="send" />
          <span>确认提交</span>
        </button>
      </div>
    </form>

    <div v-else-if="form.status === 'submitted' && form.answer" class="form-summary">
      <span v-for="(val, k) in form.answer" :key="k" class="form-ans-pill">
        <b>{{ k }}:</b> {{ Array.isArray(val) ? val.join(', ') : String(val) }}
      </span>
    </div>
  </section>
</template>

<style scoped>
.form-card {
  margin-top: 8px;
  border: 1px solid var(--accent-line);
  border-radius: var(--r-md);
  background: var(--surface-1);
  overflow: hidden;
  font-size: 12.5px;
}
.form-card.is-submitted {
  border-color: var(--line);
  background: var(--surface-2);
}
.form-card.is-cancelled {
  border-color: var(--line);
  opacity: 0.78;
}
.form-card-hdr {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 11px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--line);
}
.form-card-ic { width: 14px; height: 14px; color: var(--accent); flex: none; }
.form-card-title { font-weight: 600; color: var(--text); flex: 1; min-width: 0; }
.form-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border-radius: var(--r-full);
  font-size: 11px;
  font-weight: 500;
}
.form-badge.is-pending { background: var(--accent-soft); color: var(--accent); }
.form-badge.is-ok { background: color-mix(in srgb, var(--ok) 14%, transparent); color: var(--ok); }
.form-badge.is-cancel { background: var(--surface-3); color: var(--text-3); }
.form-body {
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.form-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.form-label { font-weight: 600; font-size: 12px; color: var(--text-2); }
.form-req { color: var(--warn); margin-left: 3px; }
.form-desc { margin: 0; font-size: 11.5px; color: var(--text-3); }
.form-options, .form-bool-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.form-opt-btn {
  display: inline-flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 6px 10px;
  border-radius: var(--r-sm);
  border: 1px solid var(--line-strong);
  background: var(--surface-2);
  color: var(--text);
  font-size: 12px;
  cursor: pointer;
  transition: border-color 0.14s, background 0.14s;
}
.form-opt-btn:hover { background: var(--surface-3); }
.form-opt-btn.is-active {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
}
.form-opt-ck { width: 12px; height: 12px; margin-right: 4px; }
.form-opt-lbl { font-weight: 500; }
.form-opt-sub { font-size: 11px; color: var(--text-3); }
.form-input {
  width: 100%;
  padding: 6px 9px;
  border-radius: var(--r-sm);
  border: 1px solid var(--line-strong);
  background: var(--surface-2);
  color: var(--text);
  font-size: 12.5px;
}
.form-input:focus-visible { outline: 2px solid var(--accent); outline-offset: -1px; }
.form-err { margin: 0; font-size: 11.5px; color: var(--warn); }
.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 2px;
}
.form-summary {
  padding: 8px 11px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.form-ans-pill {
  padding: 2px 8px;
  border-radius: var(--r-full);
  background: var(--surface-3);
  font-size: 11.5px;
  color: var(--text-2);
}
.form-ext-link { align-self: flex-start; text-decoration: none; }
</style>
