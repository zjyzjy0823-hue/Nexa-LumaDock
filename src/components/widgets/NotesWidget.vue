<script setup lang="ts">
import { ref } from 'vue'
import { ChevronRight, FileText, Folder, Lightbulb, List, Plus, SquareCheck, X } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import { recentNotes } from '../../data/operations'

const noteIcons = {
  'project-ideas': Folder,
  'shopping-list': SquareCheck,
  'server-tasks': List,
  ideas: Lightbulb,
}
const iconFor = (id: string) => noteIcons[id as keyof typeof noteIcons] ?? FileText
const notes = ref(recentNotes.map((note) => ({ ...note })))
const isAdding = ref(false)
const newTitle = ref('')

function addNote() {
  const title = newTitle.value.trim()
  if (!title) return
  notes.value.unshift({ id: `note-${Date.now()}`, title, preview: '', updatedAt: '今天', color: 'blue' })
  isAdding.value = false
  newTitle.value = ''
}
</script>

<template>
  <GlassCard title="便签" class="notes-card">
    <template #action><ChevronRight class="notes-action-arrow" :size="20" aria-hidden="true" /></template>
    <div class="notes-list">
      <article v-for="note in notes.slice(0, 4)" :key="note.id" class="note-row" :title="note.preview">
        <component :is="iconFor(note.id)" class="note-icon" :size="16" :stroke-width="1.9" />
        <strong>{{ note.title }}</strong>
        <time>{{ note.updatedAt }}</time>
      </article>
    </div>
    <form v-if="isAdding" class="new-note-form" @submit.prevent="addNote" @keydown.esc="isAdding = false">
      <input v-model="newTitle" autofocus aria-label="新便签标题" placeholder="便签标题" maxlength="40" />
      <button type="submit" :disabled="!newTitle.trim()" aria-label="保存便签"><Plus :size="14" /></button>
      <button type="button" aria-label="取消" @click="isAdding = false; newTitle = ''"><X :size="14" /></button>
    </form>
    <button v-else class="new-note" type="button" @click="isAdding = true"><Plus :size="15" /> 新建便签</button>
  </GlassCard>
</template>

<style scoped>
.notes-card{padding:12px 17px 11px;background:linear-gradient(145deg,rgba(205,220,246,.4),rgba(151,170,209,.34))}
.notes-card :deep(.glass-card__header){margin-bottom:11px}
.notes-card :deep(.glass-card__title){color:#fff;font-size:20px;font-weight:500}
.notes-card :deep(.glass-card__title)::after{content:'›';display:inline-block;margin-left:10px;font-size:26px;font-weight:300;line-height:.5;vertical-align:-1px}
.notes-action-arrow{color:#fff}
.notes-list{display:flex;flex-direction:column}
.note-row{min-width:0;min-height:29px;display:flex;align-items:center;gap:9px;border-bottom:1px solid rgba(255,255,255,.13)}
.note-row:last-child{border-bottom:0}
.note-icon{flex:none;color:rgba(255,255,255,.98)}
.note-row strong{min-width:0;flex:1;color:rgba(255,255,255,.97);font-size:12px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.note-row time{flex:none;color:rgba(238,242,255,.72);font-size:11px;white-space:nowrap}
.new-note,.new-note-form{height:31px;display:flex;align-items:center;gap:7px;margin-top:4px;padding:0 12px;border:1px solid rgba(255,255,255,.26);border-radius:10px;background:rgba(196,213,251,.20);color:rgba(255,255,255,.92);font:inherit;font-size:12px}
.new-note{cursor:pointer;transition:background .2s ease}
.new-note:hover{background:rgba(255,255,255,.32)}
.new-note-form{padding-right:4px}
.new-note-form input{min-width:0;width:100%;border:0;outline:0;background:transparent;color:#fff;font:inherit;font-size:12px}
.new-note-form input::placeholder{color:rgba(255,255,255,.7)}
.new-note-form button{width:22px;height:22px;flex:none;display:grid;place-items:center;border:0;border-radius:6px;background:rgba(255,255,255,.16);color:#fff;cursor:pointer}
.new-note-form button:disabled{opacity:.5;cursor:default}
.new-note:focus-visible,.new-note-form :focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@container (max-height: 200px) {
  .notes-card { padding: 9px 11px; }
  .notes-card :deep(.glass-card__header) { margin-bottom: 5px; }
  .note-row { min-height: 23px; gap: 5px; }
  .note-row strong { font-size: 11px; }
  .note-row time { font-size: 9px; }
  .new-note, .new-note-form { height: 27px; margin-top: 3px; }
}
@container (max-width: 190px) {
  .note-row time { display: none; }
  .notes-card { padding-inline: 9px; }
}
@media(prefers-reduced-motion:reduce){.new-note{transition:none}}
</style>
