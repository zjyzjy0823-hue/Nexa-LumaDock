<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { InlineMediaAttachment } from '../../services/messageSegments'
import { useFleetStore } from '../../stores/fleet'
import type { ArtifactRef } from '../../types/fleet'
import OpusIcon from '../ui/OpusIcon.vue'
import { formatBytes } from './providerMeta'

const props = defineProps<{
  attachment: InlineMediaAttachment
  compact?: boolean
}>()

const emit = defineEmits<{
  previewImage: [src: string, alt: string]
  openFile: [path: string]
  handoff: [artifact: ArtifactRef]
  status: [message: string]
}>()

const fleet = useFleetStore()
const downloading = ref(false)

onMounted(() => {
  if (props.attachment.artifact && props.attachment.mime.startsWith('image/')) {
    void fleet.ensureArtifactImagePreview(props.attachment.artifact)
  }
})

const effectiveUrl = computed(() => {
  if (props.attachment.url) return props.attachment.url
  if (props.attachment.artifact) {
    return fleet.imagePreviewByArtifactId[props.attachment.artifact.artifactId] || ''
  }
  return ''
})

const isImage = computed(() =>
  props.attachment.mime.startsWith('image/') || effectiveUrl.value.startsWith('data:image/'),
)

const isGif = computed(() =>
  props.attachment.mime.toLowerCase().includes('gif') ||
  props.attachment.fileName.toLowerCase().endsWith('.gif') ||
  effectiveUrl.value.startsWith('data:image/gif'),
)

const isVideo = computed(() =>
  props.attachment.mime.startsWith('video/') || effectiveUrl.value.startsWith('data:video/'),
)

const isAudio = computed(() =>
  props.attachment.mime.startsWith('audio/') || effectiveUrl.value.startsWith('data:audio/'),
)

const subLabel = computed(() => {
  const parts: string[] = []
  if (props.attachment.sizeBytes && props.attachment.sizeBytes > 0) {
    parts.push(formatBytes(props.attachment.sizeBytes))
  }
  if (props.attachment.artifact) {
    parts.push('AES-256-GCM')
  } else if (props.attachment.mime && props.attachment.mime !== 'application/octet-stream') {
    parts.push(props.attachment.mime)
  } else if (props.attachment.filePath) {
    parts.push(props.attachment.filePath)
  }
  return parts.join(' · ') || '文件附件'
})

function handleCardClick() {
  if (isImage.value && effectiveUrl.value) {
    emit('previewImage', effectiveUrl.value, props.attachment.fileName)
    return
  }
  if (props.attachment.filePath) {
    emit('openFile', props.attachment.filePath)
  }
}

async function handleDownload() {
  if (downloading.value) return
  if (props.attachment.artifact) {
    downloading.value = true
    try {
      await fleet.downloadArtifactToBrowser(props.attachment.artifact)
      emit('status', `已解密下载 ${props.attachment.fileName}`)
    } catch (err) {
      emit('status', err instanceof Error ? err.message : '下载失败')
    } finally {
      downloading.value = false
    }
    return
  }
  if (effectiveUrl.value) {
    const a = document.createElement('a')
    a.href = effectiveUrl.value
    a.download = props.attachment.fileName || 'download'
    a.target = '_blank'
    a.rel = 'noopener noreferrer'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    emit('status', `正在下载 ${props.attachment.fileName}`)
    return
  }
  if (props.attachment.filePath) {
    fleet.downloadWorkspaceFile(props.attachment.filePath)
    emit('status', `正在请求节点下载 ${props.attachment.fileName}`)
  }
}
</script>

<template>
  <!-- 1. 内联图片 / GIF 卡片（参考 hermes-mobile InlineAttachment.isImage） -->
  <div v-if="isImage && effectiveUrl" class="inline-att-img-card">
    <button
      type="button"
      class="inline-att-img-btn"
      :title="`点击查看大图：${attachment.fileName}`"
      @click="emit('previewImage', effectiveUrl, attachment.fileName)"
    >
      <img :src="effectiveUrl" :alt="attachment.fileName" loading="lazy" class="inline-att-img" />
      <span v-if="isGif" class="inline-att-gif-badge">GIF</span>
    </button>
    <div class="inline-att-img-bar">
      <div class="inline-att-meta">
        <span class="inline-att-name" :title="attachment.filePath || attachment.fileName">{{ attachment.fileName }}</span>
        <span v-if="attachment.sizeBytes" class="inline-att-sub num">{{ formatBytes(attachment.sizeBytes) }}</span>
      </div>
      <div class="inline-att-actions">
        <button
          v-if="attachment.artifact && !compact"
          type="button"
          class="btn btn-subtle btn-sm"
          title="将此产物交接给其他节点"
          @click.stop="emit('handoff', attachment.artifact)"
        >@Handoff</button>
        <button
          type="button"
          class="btn btn-subtle btn-sm inline-att-dl-btn"
          :disabled="downloading"
          title="下载原图"
          @click.stop="handleDownload"
        >
          <OpusIcon name="download" />
          <span>{{ downloading ? '下载中' : '下载' }}</span>
        </button>
      </div>
    </div>
  </div>

  <!-- 2. 内联音视频播放器（参考 hermes-mobile InlineMediaPlayer） -->
  <div v-else-if="(isVideo || isAudio) && effectiveUrl" class="inline-att-media-card">
    <video v-if="isVideo" :src="effectiveUrl" controls preload="metadata" class="inline-att-video" />
    <audio v-else :src="effectiveUrl" controls preload="metadata" class="inline-att-audio" />
    <div class="inline-att-img-bar">
      <span class="inline-att-name" :title="attachment.fileName">{{ attachment.fileName }}</span>
      <button
        type="button"
        class="btn btn-subtle btn-sm inline-att-dl-btn"
        :disabled="downloading"
        @click.stop="handleDownload"
      >
        <OpusIcon name="download" />
        <span>下载</span>
      </button>
    </div>
  </div>

  <!-- 3. 内联文件卡片（参考 hermes-mobile InlineAttachment 文件 Surface 卡片） -->
  <div
    v-else
    class="inline-att-file-card"
    :class="{ 'is-clickable': Boolean(attachment.filePath) }"
    @click="handleCardClick"
  >
    <div class="inline-att-file-ic">
      <OpusIcon name="file" />
    </div>
    <div class="inline-att-file-copy">
      <div class="inline-att-name" :title="attachment.filePath || attachment.fileName">{{ attachment.fileName }}</div>
      <div class="inline-att-sub">{{ subLabel }}</div>
    </div>
    <button
      v-if="attachment.filePath"
      type="button"
      class="btn btn-subtle btn-sm"
      title="在文件抽屉中预览"
      @click.stop="emit('openFile', attachment.filePath)"
    >预览</button>
    <button
      v-if="attachment.artifact && !compact"
      type="button"
      class="btn btn-subtle btn-sm"
      title="将此加密文件交接给其他节点"
      @click.stop="emit('handoff', attachment.artifact)"
    >@Handoff</button>
    <button
      type="button"
      class="btn btn-ghost btn-sm inline-att-dl-btn"
      :disabled="downloading"
      :title="`下载 ${attachment.fileName}`"
      @click.stop="handleDownload"
    >
      <OpusIcon name="download" />
      <span>{{ downloading ? '下载中' : '下载' }}</span>
    </button>
  </div>
</template>

<style scoped>
.inline-att-img-card,
.inline-att-media-card {
  display: flex;
  flex-direction: column;
  width: fit-content;
  max-width: min(360px, 100%);
  margin: 6px 0;
  border: 1px solid var(--line-strong);
  border-radius: 12px;
  overflow: hidden;
  background: var(--surface-2);
  box-shadow: var(--shadow-1);
}
.inline-att-img-btn {
  position: relative;
  display: block;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: zoom-in;
  line-height: 0;
}
.inline-att-img {
  display: block;
  max-width: 100%;
  max-height: 240px;
  width: auto;
  height: auto;
  object-fit: contain;
}
.inline-att-gif-badge {
  position: absolute;
  top: 8px;
  right: 8px;
  padding: 2px 6px;
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.72);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  line-height: 1.3;
}
.inline-att-video {
  display: block;
  max-width: 100%;
  max-height: 240px;
  background: #000;
}
.inline-att-audio {
  display: block;
  width: min(320px, 100%);
  margin: 8px 10px 4px;
}
.inline-att-img-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 10px;
  border-top: 1px solid var(--line);
  background: var(--solid);
  color: var(--text);
}
.inline-att-meta {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}
.inline-att-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: none;
}
.inline-att-file-card {
  display: flex;
  align-items: center;
  gap: 10px;
  width: min(380px, 100%);
  margin: 6px 0;
  padding: 9px 12px;
  border: 1px solid var(--line-strong);
  border-radius: 12px;
  background: color-mix(in srgb, var(--surface-2) 85%, var(--solid));
  color: var(--text);
}
.inline-att-file-card.is-clickable {
  cursor: pointer;
}
.inline-att-file-card.is-clickable:hover {
  border-color: var(--accent-line);
}
.inline-att-file-ic {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: var(--accent-soft);
  color: var(--accent);
  flex: none;
}
.inline-att-file-ic .i {
  width: 18px;
  height: 18px;
}
.inline-att-file-copy {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 2px;
}
.inline-att-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
  font-weight: 560;
  color: var(--text);
}
.inline-att-sub {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: var(--text-3);
}
.inline-att-dl-btn {
  flex: none;
  height: 28px;
  padding: 0 9px;
  font-size: 11.5px;
}
</style>
