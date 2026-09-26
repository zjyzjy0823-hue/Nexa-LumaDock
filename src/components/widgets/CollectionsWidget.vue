<script setup lang="ts">
import { ref } from 'vue'
import { ChevronRight, CreditCard, Folder, Globe2, JapaneseYen, Plus, X } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import { collectionItems, type CollectionItem } from '../../data/operations'

const icons = {
  transactions: JapaneseYen,
  subscriptions: CreditCard,
  domains: Globe2,
  projects: Folder,
}

const items = ref<{ id: string; name: string; count: number; unit: string }[]>(collectionItems.map((item) => ({ ...item })))
const selectedId = ref<string | null>(null)
const isAdding = ref(false)
const newName = ref('')

const iconFor = (id: string) => icons[id as CollectionItem['id']] ?? Folder

function addCollection() {
  const name = newName.value.trim()
  if (!name) return
  const id = `custom-${Date.now()}`
  items.value.push({ id, name, count: 0, unit: '条' })
  selectedId.value = id
  newName.value = ''
  isAdding.value = false
}

function cancelAdd() {
  isAdding.value = false
  newName.value = ''
}
</script>

<template>
  <GlassCard title="数据集" class="collections-card">
    <template #action><ChevronRight class="collections-action-arrow" :size="20" aria-hidden="true" /></template>
    <div class="collection-content">
      <div class="collection-grid">
        <button
          v-for="item in items"
          :key="item.id"
          type="button"
          class="collection-tile"
          :class="{ selected: selectedId === item.id }"
          :aria-pressed="selectedId === item.id"
          :title="`${item.name}: ${item.count} ${item.unit}`"
          @click="selectedId = item.id"
        >
          <span class="collection-icon" :data-type="item.id"><component :is="iconFor(item.id)" :size="28" :stroke-width="1.8" /></span>
          <span class="collection-name">{{ item.name }}</span>
          <strong>{{ item.count }}</strong>
        </button>
        <button type="button" class="collection-tile add-tile" aria-label="添加数据集" @click="isAdding = true">
          <span class="collection-icon add-icon"><Plus :size="31" :stroke-width="1.7" /></span>
          <span class="collection-name">添加</span>
        </button>
      </div>

      <form v-if="isAdding" class="add-popover" @submit.prevent="addCollection" @keydown.esc="cancelAdd">
        <label for="collection-name">新建数据集</label>
        <div class="add-controls">
          <input id="collection-name" v-model="newName" autofocus placeholder="数据集名称" maxlength="32" />
          <button type="submit" :disabled="!newName.trim()" aria-label="保存数据集"><Plus :size="18" /></button>
          <button type="button" aria-label="取消" @click="cancelAdd"><X :size="17" /></button>
        </div>
      </form>
    </div>
  </GlassCard>
</template>

<style scoped>
.collections-card{padding:12px 20px 12px}
.collections-card :deep(.glass-card__header){margin-bottom:17px}
.collections-card :deep(.glass-card__title){color:#fff;font-size:20px;font-weight:500}
.collections-card :deep(.glass-card__title)::after{content:'›';display:inline-block;margin-left:12px;font-size:26px;font-weight:300;line-height:.5;vertical-align:-1px}
.collections-action-arrow{color:#fff}
.collection-content{position:relative;height:100%;display:flex;align-items:safe center}
.collection-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(70px,1fr));grid-auto-flow:row;gap:clamp(6px,1.3cqw,15px);width:100%}
.collection-tile{min-width:0;min-height:111px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;padding:6px 3px;border:1px solid rgba(255,255,255,.56);border-radius:17px;background:linear-gradient(145deg,rgba(255,255,255,.51),rgba(255,255,255,.30));box-shadow:inset 0 1px rgba(255,255,255,.42);color:#161b26;font:inherit;cursor:pointer;transition:transform .2s ease,background .2s ease,box-shadow .2s ease}
.collection-tile:hover{transform:translateY(-3px);background:rgba(255,255,255,.68);box-shadow:0 7px 19px rgba(46,65,132,.13),inset 0 1px rgba(255,255,255,.52)}
.collection-tile.selected{border-color:rgba(164,191,255,.85);background:rgba(196,212,255,.58)}
.collection-tile:focus-visible,.add-popover :focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.collection-icon{width:42px;height:42px;display:grid;place-items:center;margin-bottom:5px;border-radius:13px;color:#cf4dc9;background:rgba(255,255,255,.57)}
.collection-icon[data-type="transactions"]{width:34px;height:34px;margin:4px 0 9px;border:2px solid #d14cc4;border-radius:50%;background:rgba(255,255,255,.5)}
.collection-icon[data-type="transactions"] :deep(svg){width:22px;height:22px}
.collection-icon[data-type="subscriptions"]{color:#ffa500;background:rgba(255,255,255,.57)}
.collection-icon[data-type="domains"]{color:#16a7d8;background:rgba(255,255,255,.57)}
.collection-icon[data-type="projects"]{color:#5578e9;background:rgba(255,255,255,.57)}
.collection-name{max-width:100%;color:#1b2029;font-size:12px;line-height:1.15;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.collection-tile strong{font-size:16px;line-height:1.1;font-weight:670;font-variant-numeric:tabular-nums}
.add-icon{width:48px;height:48px;color:#121b29;background:rgba(255,255,255,.32);border-radius:50%}
.add-tile .collection-name{margin-top:8px;font-size:14px}
.add-popover{position:absolute;z-index:5;right:0;bottom:0;width:min(280px,100%);padding:13px;border:1px solid rgba(255,255,255,.55);border-radius:15px;background:rgba(81,107,160,.91);box-shadow:0 14px 30px rgba(24,40,86,.25);backdrop-filter:blur(18px)}
.add-popover label{display:block;margin-bottom:7px;color:#fff;font-size:12px;font-weight:650}
.add-controls{display:flex;gap:5px}
.add-controls input{min-width:0;flex:1;padding:7px 8px;border:1px solid rgba(255,255,255,.35);border-radius:8px;background:rgba(255,255,255,.18);color:#fff;font:inherit;font-size:12px}
.add-controls input::placeholder{color:rgba(255,255,255,.68)}
.add-controls button{width:29px;display:grid;place-items:center;border:1px solid rgba(255,255,255,.34);border-radius:8px;background:rgba(255,255,255,.19);color:#fff;cursor:pointer}
.add-controls button:disabled{opacity:.45;cursor:default}
@container (max-height: 200px) {
  .collections-card { padding: 10px 14px; }
  .collections-card :deep(.glass-card__header) { margin-bottom: 8px; }
  .collection-tile { min-height: 76px; gap: 1px; padding: 4px 2px; border-radius: 13px; }
  .collection-icon { width: 31px; height: 31px; margin-bottom: 2px; border-radius: 9px; }
  .collection-icon :deep(svg) { width: 22px; height: 22px; }
  .collection-icon[data-type="transactions"] { width: 27px; height: 27px; margin: 2px 0 4px; }
  .add-icon { width: 34px; height: 34px; }
  .add-tile .collection-name { margin-top: 2px; }
}
@container (max-width: 310px) {
  .collection-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media(max-width:700px){.collection-grid{grid-template-columns:repeat(3,minmax(0,1fr));grid-auto-flow:row;grid-auto-columns:auto;gap:8px;overflow-x:visible}.collection-tile{min-height:100px}}
@media(prefers-reduced-motion:reduce){.collection-tile{transition:none}}
</style>
