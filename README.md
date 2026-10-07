# KitPrep 中央厨房 BOM 备料

按菜品 BOM（出品定额）展开订单行，可经半成品多级展平到叶原料、合并同原料需求，对照叶料仓账面与备料占用计算缺料并生成备料单。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 三套独立账

- **叶料仓账面** `leaf_balances`：叶原料（叶料）的账面结存。
- **半成品仓账面** `semi_balances`：半成品（如卤肉）的账面结存，与叶料仓是两张物理独立的表。
- **备料占用** `prep_occupations`：外键指向 `leaf_balances`，只能占用叶料。

规则：

- 「生成备料单」只锁单（写备料占用），**任何账面结存都不被改小或改动**；备料单与缺料贴只出现叶原料。
- 账面调整只加不减：`POST /api/inventory/ingredients/{id}/adjust {"delta": >0}`，按原料 kind 派发到叶料仓或半成品仓。
- 同一张订单重复生成会原子顶替旧单（旧单置 `superseded`，占用不翻倍）；`status IS NULL` 的历史旧单快照永不改写。
- 半成品下层为空或 BOM 成环时整次失败，两本仓、最新单、缺料贴全部回到失败前。
- 生成不读不锁半成品仓，生成途中改半成品仓账面不影响正在形成的单。

> 种子示例：红烧肉套餐 → 卤肉 0.25/份 → 五花肉 0.25/kg。40 份订单展开为五花肉 2.5kg；卤肉不出现在备料单，半成品仓账面不随生成变化。

## 启动

旧库结构已变更且无迁移工具，首次升级需重建数据卷：

```bash
docker compose down -v
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:5000 |
| API | http://localhost:10100 |
| API 文档 | http://localhost:10100/docs |
| Postgres | localhost:5451 |

健康检查：`GET http://localhost:10100/api/health`

## 使用说明

1. 在「菜品」「BOM」维护出品定额：菜品可挂叶料或半成品，半成品再挂叶料。
2. 在「库存」分别查看/入库叶料仓与半成品仓（仅正数入库）。
3. 打开「备料单」，选择订单后点「生成备料单」锁单；表中可见需求、叶料账面、本单占用、可再用、缺料。
4. 在「缺料」查看 need − 可再用数量（叶料账面 − 备料占用）为正的叶原料。

## 开发与测试

```bash
docker compose exec api pytest -q
```

- `tests/test_bom_engine.py`：纯引擎测试（多级展平、成环、空下层、缺料口径），无需数据库。
- `tests/test_prep_api.py` / `tests/test_concurrency.py`：`db` 标记，需要真实 PostgreSQL（行锁语义 sqlite 无法验证）；数据库不可达时自动 skip。可用 `TEST_DATABASE_URL` 覆盖测试库连接。
