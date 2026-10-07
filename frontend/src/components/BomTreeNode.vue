<script setup lang="ts">
import type { BomNode } from '../types'
defineProps<{ node: BomNode }>()
</script>
<template>
  <ul style="margin:0.15rem 0 0.15rem 0.6rem;padding-left:0.6rem;border-left:1px dashed #c9bfb3">
    <li>
      <span class="badge" :class="node.kind === 'semi' ? 'badge-warn' : 'badge-ok'">
        {{ node.kind === 'semi' ? '半成品' : '叶料' }}
      </span>
      {{ node.ingredient }} · {{ node.qty }} {{ node.unit }}
      <span v-if="node.cycle" class="badge badge-bad">循环</span>
      <span v-if="node.empty" class="badge badge-bad">下层为空</span>
      <BomTreeNode v-for="c in node.children" :key="c.ingredient_id + '-' + c.code" :node="c" />
    </li>
  </ul>
</template>
