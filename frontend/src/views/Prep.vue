<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { BomTreeRoot, Order, PrepResponse } from '../types'
import BomTreeNode from '../components/BomTreeNode.vue'

const tree = ref<BomTreeRoot[]>([])
const data = ref<PrepResponse | null>(null)
const orders = ref<Order[]>([])
const orderId = ref<number>(1)
const running = ref(false)
const error = ref('')

async function loadLatest() {
  error.value = ''
  data.value = await api<PrepResponse>(`/prep/latest?order_id=${orderId.value}`)
}

async function run() {
  if (running.value) return  // double-click: second click cannot double-occupy
  running.value = true; error.value = ''
  try {
    data.value = await api<PrepResponse>(`/prep/run?order_id=${orderId.value}`, { method: 'POST' })
  } catch (e: any) {
    try {
      const d = JSON.parse(e.message)
      error.value = d?.detail?.message ? `${d.detail.code}: ${d.detail.message}` : e.message
    } catch { error.value = e.message }
  } finally { running.value = false }
}

async function selectOrder(id: number) {
  orderId.value = id
  await loadLatest()
}

onMounted(async () => {
  tree.value = await api<BomTreeRoot[]>('/bom/tree')
  orders.value = await api<Order[]>('/orders')
  if (orders.value.length && !orders.value.some(o => o.id === orderId.value)) {
    orderId.value = orders.value[0].id
  }
  await loadLatest()
})
</script>
<template>
  <h1>备料工作台</h1>
  <p class="sub">生成只锁叶料占用，不改任何账面；备料单与缺料贴只出现叶原料</p>
  <div class="kp-chips" style="margin-bottom:0.75rem" v-if="orders.length">
    <span v-for="o in orders" :key="o.id" class="kp-chip"
      :class="{ 'router-link-active': o.id === orderId }"
      style="cursor:pointer" @click="selectOrder(o.id)">
      {{ o.code }} · {{ o.outlet }}
    </span>
  </div>
  <div style="display:flex;align-items:center;gap:0.8rem">
    <button class="btn" :disabled="running" @click="run">
      {{ running ? '生成中…' : '生成备料单' }}
    </button>
    <span v-if="error" class="badge badge-bad">{{ error }}</span>
    <span v-if="data?.legacy" class="badge badge-warn">当前为历史旧单快照（只读，已不可改）</span>
  </div>
  <div class="kp-workbench" style="margin-top:0.85rem">
    <aside class="kp-bom-tree">
      <h2>菜品 / BOM</h2>
      <div v-for="d in tree" :key="d.code" class="kp-dish-node">
        <strong>{{ d.dish }}</strong>
        <span style="font-size:0.7rem;color:#8a8078">{{ d.code }}</span>
        <BomTreeNode :node="c" v-for="c in d.children" :key="c.ingredient_id + '-' + c.code" />
      </div>
    </aside>
    <section class="kp-worksheet" v-if="data">
      <h2>备料单 · {{ data.order?.code }} · {{ data.order?.outlet }}</h2>
      <p v-if="!data.prep_lines.length" style="font-size:0.85rem">尚未生成，点「生成备料单」锁单。</p>
      <table v-else>
        <thead><tr>
          <th>原料</th><th>需求</th><th>叶料账面</th><th>本单占用</th>
          <th>可再用</th><th>缺料</th><th>单位</th>
        </tr></thead>
        <tbody>
          <tr v-for="l in data.prep_lines" :key="l.ingredient_id">
            <td>{{ l.ingredient_name }}</td>
            <td>{{ l.need_qty }}</td>
            <td>{{ l.book_qty }}</td>
            <td>{{ l.need_qty }}</td>
            <td :class="l.available_qty < 0 ? 'badge badge-bad' : ''">{{ l.available_qty }}</td>
            <td>
              <span v-if="l.shortage > 0" class="badge badge-bad">{{ l.shortage }}</span>
              <span v-else>—</span>
            </td>
            <td>{{ l.unit }}</td>
          </tr>
        </tbody>
      </table>
    </section>
    <aside class="kp-shortage-sticky">
      <h2>⚠ 缺料便利贴 <span style="font-size:0.75rem">{{ data?.stats?.shortage_count ?? 0 }}</span></h2>
      <div v-for="r in data?.shortages ?? []" :key="r.ingredient_id" class="kp-shortage-item">
        <span>{{ r.ingredient_name }}</span>
        <span class="kp-qty">−{{ r.shortage }} {{ r.unit }}</span>
      </div>
      <p v-if="!(data?.shortages?.length)" style="font-size:0.8rem;margin:0.5rem 0 0">暂无缺料</p>
    </aside>
  </div>
</template>
