<script setup lang="ts">
import { computed } from 'vue'
import { useData } from 'vitepress'

import { BRANCH, REPO } from '../../nav.mjs'

const { page } = useData()

const isIndex = computed(() => page.value.relativePath === 'index.md' || page.value.relativePath === 'en/index.md')
const isEnglish = computed(() => page.value.relativePath.startsWith('en/'))

const sourcePath = computed(() => {
  const relative = page.value.relativePath.replace(/^en\//, '')
  return isEnglish.value ? relative.replace(/\.md$/, '.en.md') : relative
})

const href = computed(() => `https://github.com/${REPO}/edit/${BRANCH}/docs/${sourcePath.value}`)
const label = computed(() => (isEnglish.value ? 'Edit this page on GitHub' : '在 GitHub 上编辑此页'))
</script>

<template>
  <p v-if="!isIndex" class="edit-on-github">
    <a :href="href" target="_blank" rel="noreferrer">{{ label }}</a>
  </p>
</template>

<style scoped>
.edit-on-github {
  margin: 24px 0 0;
  font-size: 13px;
}

.edit-on-github a {
  color: var(--vp-c-text-2);
  text-decoration: none;
}

.edit-on-github a:hover {
  color: var(--vp-c-brand-1);
  text-decoration: underline;
}
</style>
