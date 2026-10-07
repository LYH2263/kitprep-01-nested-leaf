export interface PrepLine {
  ingredient_id: number
  ingredient_code: string
  ingredient_name: string
  unit: string
  kind: 'leaf' | 'semi'
  need_qty: number
  book_qty: number
  occupied_qty: number
  available_qty: number
  shortage: number
}

export interface PrepStats {
  ingredient_count: number
  shortage_count: number
  total_shortage_qty: number
  total_need_qty: number
}

export interface PrepResponse {
  id: number | null
  order_id: number
  status: string | null
  legacy: boolean
  version?: number
  superseded_run_ids?: number[]
  order?: { id: number; code: string; outlet: string }
  prep_lines: PrepLine[]
  shortages: PrepLine[]
  stats: PrepStats
}

export interface ShortagesResponse {
  order_id: number
  run_id: number | null
  status: string | null
  legacy: boolean
  shortages: PrepLine[]
  stats: PrepStats
}

export interface LedgerRow {
  ingredient_id: number
  code: string
  name: string
  unit: string
  book_qty: number
  occupied_qty: number
  available_qty: number
}

export interface InventoryResponse {
  leaf: LedgerRow[]
  semi: LedgerRow[]
}

export interface BomNode {
  ingredient_id: number
  ingredient: string
  code: string
  qty: number
  unit: string
  kind: 'leaf' | 'semi'
  children?: BomNode[]
  cycle?: boolean
  empty?: boolean
}

export interface BomTreeRoot {
  dish: string
  code: string
  children: BomNode[]
}

export interface Order {
  id: number
  code: string
  outlet: string
  status: string
}
