<script setup lang="ts">
import { ref, watch } from 'vue'
import Modal from './Modal.vue'
import ActionButton from './ActionButton.vue'
import { confirmation, resolveConfirmation } from '../../composables/useConfirm'

const cachedMessage = ref('')
watch(() => confirmation.value?.message, message => {
  if (message) cachedMessage.value = message
}, { immediate: true })
</script>

<template>
  <Modal :open="!!confirmation" :layer="250" title="确认操作" @close="resolveConfirmation(false)">
    <p class="confirm-message">{{ confirmation?.message ?? cachedMessage }}</p>
    <template #footer>
      <ActionButton variant="secondary" @click="resolveConfirmation(false)">取消</ActionButton>
      <ActionButton variant="danger" @click="resolveConfirmation(true)">确认</ActionButton>
    </template>
  </Modal>
</template>

<style scoped>
.confirm-message { margin: 0; line-height: 1.65; overflow-wrap: anywhere; font-size: 13.5px; color: var(--text-2); }
</style>
