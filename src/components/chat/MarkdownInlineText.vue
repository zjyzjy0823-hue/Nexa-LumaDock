<script setup lang="ts">
import type { MarkdownInline } from '../../services/markdownBlocks'

defineProps<{
  tokens: MarkdownInline[]
}>()
</script>

<template>
  <template v-for="(tok, idx) in tokens" :key="`${tok.type}-${idx}`">
    <strong v-if="tok.type === 'bold'">{{ tok.text }}</strong>
    <em v-else-if="tok.type === 'italic'">{{ tok.text }}</em>
    <del v-else-if="tok.type === 'strike'">{{ tok.text }}</del>
    <code v-else-if="tok.type === 'code'" class="md-inline-code">{{ tok.text }}</code>
    <a v-else-if="tok.type === 'link'" :href="tok.href" target="_blank" rel="noopener noreferrer" class="md-link">{{ tok.text }}</a>
    <template v-else>{{ tok.text }}</template>
  </template>
</template>
