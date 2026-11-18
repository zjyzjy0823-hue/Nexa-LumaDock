<script setup lang="ts">
import { computed, ref } from 'vue'
import { splitDiffPath } from '../../services/diffHelpers'
import type { SessionDiffState } from '../../types/fleet'
import OpusIcon from '../ui/OpusIcon.vue'

const props = defineProps<{
  diff: SessionDiffState | null
}>()

const emit = defineEmits<{
  review: [focusFile?: string]
}>()

const expanded = ref(false)

const visible = computed(() =>
  Boolean(props.diff && props.diff.isGitRepo !== false && props.diff.files.length > 0),
)

const fileRows = computed(() =>
  (props.diff?.files ?? []).map(file => ({
    file,
    meta: splitDiffPath(file.path),
  })),
)
</script>

<template>
  <section v-if="visible && diff" class="cfs-bar" aria-label="本会话工作区变更文件汇总">
    <div class="cfs-head">
      <button
        type="button"
        class="cfs-toggle"
        :aria-expanded="expanded"
        @click="expanded = !expanded"
      >
        <span class="cfs-title num">{{ diff.files.length }} 个文件变更</span>
        <span class="cfs-stats num">
          <span class="sum-add">+{{ diff.summary.additions }}</span>
          <span class="sum-del">-{{ diff.summary.deletions }}</span>
        </span>
        <OpusIcon name="chevD" class="cfs-chev" :class="{ 'is-open': expanded }" />
      </button>

      <button
        type="button"
        class="cfs-review-btn"
        title="打开工作台 Diff 评审面板"
        @click="emit('review')"
      >
        <OpusIcon name="eye" />
        <span>评审</span>
      </button>
    </div>

    <div v-if="expanded" class="cfs-list" role="list">
      <button
        v-for="{ file, meta } in fileRows"
        :key="file.path"
        type="button"
        role="listitem"
        class="cfs-row"
        :title="`在 Diff 评审面板查看 ${file.path}`"
        @click="emit('review', file.path)"
      >
        <span class="cfs-lang" :class="`is-${meta.badgeTone}`">{{ meta.badge }}</span>
        <span class="cfs-name">{{ meta.fileName }}</span>
        <span v-if="meta.dirName" class="cfs-dir">{{ meta.dirName }}</span>
        <span class="cfs-row-stats num">
          <span v-if="file.additions" class="sum-add">+{{ file.additions }}</span>
          <span v-if="file.deletions" class="sum-del">-{{ file.deletions }}</span>
        </span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.cfs-bar {
  margin-bottom: 8px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--solid);
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.04);
  overflow: hidden;
}
.cfs-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 5px 8px 5px 12px;
  background: var(--surface-1);
}
.cfs-toggle {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 0;
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: 12px;
  cursor: pointer;
  text-align: left;
}
.cfs-title {
  font-weight: 550;
  color: var(--text-2);
}
.cfs-stats {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-weight: 600;
}
.sum-add { color: var(--ok); }
.sum-del { color: var(--warn); }
.cfs-chev {
  width: 13px;
  height: 13px;
  color: var(--text-3);
  transition: transform 0.16s ease;
  transform: rotate(-90deg);
}
.cfs-chev.is-open {
  transform: rotate(0deg);
}
.cfs-review-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-sm);
  background: var(--solid);
  color: var(--text);
  font-size: 11.5px;
  font-weight: 550;
  cursor: pointer;
  flex: none;
}
.cfs-review-btn:hover {
  border-color: var(--accent-line);
  background: var(--accent-soft);
  color: var(--accent);
}
.cfs-review-btn .i { width: 13px; height: 13px; }
.cfs-list {
  max-height: 196px;
  overflow-y: auto;
  border-top: 1px solid var(--line);
  padding: 4px;
  display: grid;
  gap: 1px;
  scrollbar-width: thin;
}
.cfs-row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  border: 0;
  border-radius: var(--r-xs);
  background: transparent;
  text-align: left;
  font-size: 12px;
  cursor: pointer;
}
.cfs-row:hover {
  background: var(--surface-2);
}
.cfs-lang {
  flex: none;
  min-width: 22px;
  height: 18px;
  padding: 0 3px;
  border-radius: 4px;
  display: inline-grid;
  place-items: center;
  font-family: var(--mono);
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: -0.02em;
  background: var(--surface-2);
  color: var(--text-3);
}
.cfs-lang.is-ts { color: #0284c7; background: rgba(2, 132, 199, 0.12); }
.cfs-lang.is-vue { color: #16a34a; background: rgba(22, 163, 74, 0.12); }
.cfs-lang.is-py { color: #ca8a04; background: rgba(202, 138, 4, 0.14); }
.cfs-lang.is-js { color: #d97706; background: rgba(217, 119, 6, 0.14); }
.cfs-lang.is-style,
.cfs-lang.is-json { color: #9333ea; background: rgba(147, 51, 234, 0.12); }
.cfs-lang.is-doc,
.cfs-lang.is-sh { color: var(--accent); background: var(--accent-soft); }
.cfs-name {
  flex: none;
  font-weight: 600;
  color: var(--text);
}
.cfs-dir {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11.5px;
  color: var(--text-3);
}
.cfs-row-stats {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 550;
}
</style>
