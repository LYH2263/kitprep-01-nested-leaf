<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { ShortagesResponse } from '../types'
const rows = ref<ShortagesResponse['shortages']>([])
const stats = ref<ShortagesResponse['stats']>({
  ingredient_count: 0, shortage_count: 0, total_shortage_qty: 0, total_need_qty: 0,
})
const legacy = ref(false)
onMounted(async () => {
  const res = await api<ShortagesResponse>('/prep/shortages?order_id=1')
  rows.value = res.shortages
  stats.value = res.stats
  legacy.value = res.legacy
})
</script>
<template>
  <h1>缺料便利贴</h1>
  <p class="sub">shortage = need − 可再用数量（叶料账面 − 备料占用，仅正数）</p>
  <p v-if="legacy" class="badge badge-warn">当前缺料贴来自历史旧单快照（只读，未被新生成改写）</p>
  <div class="kp-shortage-sticky" style="max-width:360px;transform:rotate(-1deg);margin-bottom:1rem">
    <h2>⚠ 缺料 {{ stats.shortage_count }} · 合计 {{ stats.total_shortage_qty }}</h2>
    <div v-for="r in rows" :key="r.ingredient_id" class="kp-shortage-item">
      <span>{{ r.ingredient_name }}</span>
      <span class="kp-qty">−{{ r.shortage }} {{ r.unit }}</span>
    </div>
    <p v-if="!rows.length" style="font-size:0.8rem;margin:0.5rem 0 0">暂无缺料</p>
  </div>
  <div class="card" v-if="rows.length">
    <table>
      <thead><tr><th>原料</th><th>需求</th><th>叶料账面</th><th>可再用</th><th>缺料</th><th>单位</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.ingredient_id">
          <td>{{ r.ingredient_name }}</td><td>{{ r.need_qty }}</td>
          <td>{{ r.book_qty }}</td>
          <td :class="r.available_qty < 0 ? 'badge badge-bad' : ''">{{ r.available_qty }}</td>
          <td><span class="badge badge-bad">{{ r.shortage }}</span></td><td>{{ r.unit }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
