<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { BomTreeRoot } from '../types'
import BomTreeNode from '../components/BomTreeNode.vue'
const tree = ref<BomTreeRoot[]>([])
onMounted(async () => { tree.value = await api<BomTreeRoot[]>('/bom/tree') })
</script>
<template>
  <h1>BOM 树</h1>
  <p class="sub">菜品用料树 · 出品定额可挂半成品，半成品再挂叶原料</p>
  <div class="kp-bom-tree" style="max-width:520px">
    <h2>菜品 / BOM</h2>
    <div v-for="d in tree" :key="d.code" class="kp-dish-node">
      <strong>{{ d.dish }}</strong>
      <span style="font-size:0.7rem;color:#8a8078">{{ d.code }}</span>
      <BomTreeNode :node="c" v-for="c in d.children" :key="c.ingredient_id + '-' + c.code" />
    </div>
  </div>
</template>
