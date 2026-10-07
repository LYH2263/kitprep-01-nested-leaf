<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { InventoryResponse, LedgerRow } from '../types'

const data = ref<InventoryResponse>({ leaf: [], semi: [] })
const loading = ref(false)
const error = ref('')
// pending inbound delta per ingredient in each ledger
const leafDeltas = ref<Record<number, string>>({})
const semiDeltas = ref<Record<number, string>>({})

async function load() {
  data.value = await api<InventoryResponse>('/inventory')
}

async function inbound(row: LedgerRow, kind: 'leaf' | 'semi') {
  const map = kind === 'leaf' ? leafDeltas.value : semiDeltas.value
  const delta = parseFloat(map[row.ingredient_id] || '0')
  if (!(delta > 0)) return
  loading.value = true; error.value = ''
  try {
    await api(`/inventory/ingredients/${row.ingredient_id}/adjust`, {
      method: 'POST', body: JSON.stringify({ delta }),
    })
    map[row.ingredient_id] = ''
    await load()
  } catch (e: any) {
    error.value = `入库失败：${e.message}`
  } finally { loading.value = false }
}

onMounted(load)
</script>
<template>
  <h1>库存</h1>
  <p class="sub">叶料仓 / 半成品仓是两本独立账面；备料占用只来自叶料仓，入库只加账面</p>
  <p v-if="error" class="badge badge-bad" style="margin:0.5rem 0">{{ error }}</p>

  <div class="card">
    <h2>叶料仓</h2>
    <table>
      <thead><tr>
        <th>编码</th><th>名称</th><th>账面结存</th><th>备料占用</th><th>可再用数量</th>
        <th>单位</th><th>入库（仅正数）</th>
      </tr></thead>
      <tbody>
        <tr v-for="r in data.leaf" :key="r.ingredient_id">
          <td>{{ r.code }}</td><td>{{ r.name }}</td>
          <td>{{ r.book_qty }}</td><td>{{ r.occupied_qty }}</td>
          <td>
            <span :class="r.available_qty < 0 ? 'badge badge-bad' : ''">{{ r.available_qty }}</span>
          </td>
          <td>{{ r.unit }}</td>
          <td>
            <input v-model.number="leafDeltas[r.ingredient_id]" type="number" min="0" step="0.01"
              style="width:80px" :disabled="loading" />
            <button class="btn" style="padding:0.15rem 0.6rem;margin-left:0.4rem"
              :disabled="loading || !(parseFloat(leafDeltas[r.ingredient_id] || '0') > 0)"
              @click="inbound(r, 'leaf')">入库</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="card" style="margin-top:1rem">
    <h2>半成品仓</h2>
    <table>
      <thead><tr>
        <th>编码</th><th>名称</th><th>账面结存</th><th>备料占用</th><th>可再用数量</th>
        <th>单位</th><th>入库（仅正数）</th>
      </tr></thead>
      <tbody>
        <tr v-for="r in data.semi" :key="r.ingredient_id">
          <td>{{ r.code }}</td><td>{{ r.name }}</td>
          <td>{{ r.book_qty }}</td>
          <td><span class="badge">—</span></td>
          <td>{{ r.available_qty }}</td>
          <td>{{ r.unit }}</td>
          <td>
            <input v-model.number="semiDeltas[r.ingredient_id]" type="number" min="0" step="0.01"
              style="width:80px" :disabled="loading" />
            <button class="btn" style="padding:0.15rem 0.6rem;margin-left:0.4rem"
              :disabled="loading || !(parseFloat(semiDeltas[r.ingredient_id] || '0') > 0)"
              @click="inbound(r, 'semi')">入库</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
