# 配电网故障定位 Agent — Part 1 MVP 开发规范
## 拓扑映射导入、线路参数配置、监测点配置与正常基线

**版本**：MVP v1.0  
**目标部署**：单位内部闭源、本地部署  
**开发目标**：优先跑通稳定闭环。

---

## 0. MVP 范围

系统入口为：

```text
Topology_Mapping.xlsx
        ↓
Mapping Validator
        ↓
Topology Graph
        ↓
选择 Source
        ↓
Edge 线路参数配置
        ↓
Node 监测点配置
        ↓
上传正常历史数据
        ↓
监测点匹配
        ↓
Normal Baseline
        ↓
NETWORK_READY
```

### 本阶段必须实现
1. Excel Edge List 导入与校验。
2. 根据 Edge List 自动构建拓扑图。
3. 指定唯一 Source，并把无向拓扑自动定向。
4. 单选 / 多选 Edge 配置线路类型、型号、长度。
5. 独立“线路型号管理”CRUD 页面。
6. Node 配置监测点。
7. 历史正常数据上传、字段清洗、监测点名称匹配。
8. 生成每个 Monitor 的正常运行 Baseline。
9. NETWORK_READY 完整性校验。

### 本阶段明确不做
- 扫描 PDF / CAD 自动解析。
- OCR / CV / VLM 拓扑恢复。
- R1/X1/R0/X0、三相阻抗矩阵。
- 用正常数据反演线路 R/X/C。
- GNN / Transformer 故障定位。
- 真实故障位置误差评估。
- 生产系统实时 API 接入。

---

# 1. 技术栈建议

## Backend
- Python 3.11+
- FastAPI
- Pydantic
- SQLAlchemy
- SQLite（MVP）；后续可切 PostgreSQL
- NetworkX
- pandas / openpyxl 仅用于应用代码的数据导入层（若项目已有其他 Excel 组件可替换）

## Frontend
- React + TypeScript
- React Flow
- @dagrejs/dagre（自动布局）
- Ant Design / Arco Design（二选一即可）

## Agent
Qwen3.5-4B 暂时不进入本阶段核心流程。  
Part 1 所有操作应能通过确定性 API 完成。

---

# 2. 核心设计原则

## 2.1 ID 与现场名称分离

任何现场杆号、监测点名称都不能作为数据库主键。

### Node
```json
{
  "node_id": "N000067",
  "node_key": "#67"
}
```

- `node_id`：系统内部稳定 ID。
- `node_key`：现场可读标识，可以是 `#67`、`#28.87.2.2.21`、`J001` 等。

### Edge
```json
{
  "edge_id": "E000023",
  "edge_key": "L023"
}
```

### Monitor
```json
{
  "monitor_id": "M000012",
  "canonical_name": "10kV火龙线#67.7支"
}
```

---

## 2.2 拓扑映射表只描述“连接关系”

Excel 标准字段：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `edge_key` | 否 | 用户可读线路段编号；为空时系统仍生成 `edge_id` |
| `node_1` | 是 | Edge 一端节点 |
| `node_2` | 是 | Edge 另一端节点 |
| `status` | 否 | `closed/open`；空值按 closed |
| `remark` | 否 | 备注 |

**禁止在映射表放入：**
- 线路长度
- 导线/电缆
- 线路型号
- R/X/C
- 监测点
- 历史量测

这些信息全部在拓扑生成后通过 UI 配置。

---

# 3. 为什么使用 node_1 / node_2，而不是 from / to

上传映射表时，用户只负责“谁与谁相连”，不负责判断电源方向。

导入后先构建：

\[
G_u=(V,E)
\]

即无向图。

用户在拓扑页面选择唯一 Source 后，从 Source 做 BFS/DFS，将当前闭合运行图定向为：

\[
G_d=(V,E_d)
\]

内部得到：

```text
source_node → target_node
```

后续故障区段位置比例统一定义：

- `r = 0`：靠近电源侧
- `r = 1`：远离电源侧

该定义后续必须保持不变。

---

# 4. Mapping Validator

## 4.1 ERROR — 阻止导入

1. `node_1` 为空。
2. `node_2` 为空。
3. `node_1 == node_2`。
4. 完全重复无向 Edge。
5. `A-B` 与 `B-A` 同时出现。
6. 非空 `edge_key` 重复。
7. `status` 不属于 `closed/open/空`。

## 4.2 WARNING — 允许导入但必须提示

1. 多个连通分量。
2. 图中存在 cycle。
3. 尚未选择 Source。
4. 存在 `open` Edge。
5. Node Key 包含前后空格或疑似重复格式。

## 4.3 导入结果页面

示例：

```text
Mapping imported

Nodes       126
Edges       125
Components    1
Cycles        0
Open edges    2
Errors        0
Warnings      2
```

导入成功后才进入 Topology Workspace。

---

# 5. 数据模型

## 5.1 Network

```python
class Network:
    network_id: str
    name: str
    voltage_kv: float | None
    frequency_hz: float = 50.0
    source_node_id: str | None
    status: str  # DRAFT / CONFIGURING / READY
```

---

## 5.2 Node

```python
class Node:
    node_id: str
    network_id: str
    node_key: str
    label: str | None
```

MVP 不额外建复杂设备类型。

---

## 5.3 Edge

```python
class Edge:
    edge_id: str
    network_id: str

    edge_key: str | None

    node_a_id: str
    node_b_id: str

    source_node_id: str | None
    target_node_id: str | None

    status: str  # closed/open

    line_model_id: str | None
    length_km: float | None

    remark: str | None
```

`source_node_id / target_node_id` 在用户设置 Source 后由系统生成。

---

# 6. Edge 同质性规则

MVP 中定义：

\[
\boxed{Edge = 单一线路介质 + 单一线路型号 + 一个长度}
\]

如果：

```text
#10 -- 300m架空线 -- 200m电缆 -- #11
```

必须整理为：

```text
#10 -- E001 -- J001 -- E002 -- #11
```

其中：

- E001 = 架空导线
- E002 = 电缆

不要在一个 Edge 内保存多个型号或多段介质。

---

# 7. Line Model Catalog

系统增加一级功能：

```text
系统配置
└── 线路型号管理
```

## 7.1 MVP 数据结构

```python
class LineModel:
    line_model_id: str

    line_type: str
    # overhead / cable

    model_name: str

    r_ohm_per_km: float
    x_ohm_per_km: float
    c_nf_per_km: float

    source: str
    # preset / custom

    enabled: bool
    remark: str | None
```

MVP **只保存 R/X/C**。

不加入：
- R1/X1/R0/X0
- 阻抗矩阵
- 几何导线参数
- 温度修正

---

## 7.2 CRUD

必须支持：
- 查询
- 新增
- 编辑
- 启用/停用
- 删除未被引用型号

已被 Edge 引用的型号禁止物理删除，可停用。

---

## 7.3 预设型号

MVP 可以预置若干常用：
- 架空导线规格
- 电缆规格

但 **R/X/C 数值必须来自后续确认的标准或实际资料，不要由开发人员凭经验硬编码**。

允许用户新增实际规格。

---

# 8. Topology Workspace

## 8.1 页面布局

推荐：

```text
┌──────────────────────────────────────────────┐
│ Toolbar                                      │
├─────────────────────────────┬────────────────┤
│                             │ Properties     │
│       Topology Canvas       │ Panel          │
│                             │                │
└─────────────────────────────┴────────────────┘
```

Toolbar：
- 选择 Source
- 自动布局
- Edge 多选
- 查看未配置 Edge
- 校验
- 保存

---

# 9. Source 配置

用户点击某 Node：

```text
[设为电源节点]
```

规则：
- 当前 Network 只能有一个 Source。
- 更换 Source 时需二次确认。
- Source 设置后重新计算 Edge 方向。
- `open` Edge 不参与当前运行拓扑定向。

Source 未设置时：
- 可以查看/编辑拓扑。
- 不能进入 `NETWORK_READY`。
- 不能启动后续仿真。

---

# 10. Edge 配置

## 10.1 单选

点击 Edge 后属性栏：

```text
Edge: E000023
#66 → #67

线路类型    [架空导线 ▼]
线路型号    [JKLYJ-120 ▼]
线路长度    [0.850] km

R/km        自动展示
X/km        自动展示
C/km        自动展示
```

线路类型改变时，型号下拉列表只显示对应类型。

---

## 10.2 多选

必须支持 Ctrl / 框选多个 Edge。

批量设置：
- `line_type`
- `line_model_id`

长度默认不批量覆盖，除非用户显式选择“批量设置相同长度”。

---

## 10.3 物理参数计算

型号库存单位长度：

\[
R_{km},X_{km},C_{km}
\]

Edge：

\[
R_e=R_{km}L_e
\]

\[
X_e=X_{km}L_e
\]

\[
C_e=C_{km}L_e
\]

MVP 可以实时计算，不必冗余持久化总参数。

---

# 11. Edge 表格视图

大型拓扑必须同时提供表格模式。

| Edge | From | To | 类型 | 型号 | 长度(km) | 状态 |
|---|---|---|---|---|---:|---|
| E001 | #1 | #2 | 导线 | JKLYJ-120 | 0.32 | 已配置 |
| E002 | #2 | #3 | 导线 | JKLYJ-120 | 0.48 | 已配置 |

支持：
- 搜索 Node / Edge
- 未配置过滤
- 类型过滤
- 型号过滤
- 排序

---

# 12. Monitor 配置

Node 可以绑定 0..N 个 Monitor。

```python
class Monitor:
    monitor_id: str
    network_id: str
    node_id: str

    canonical_name: str
    aliases: list[str]

    enabled: bool
```

Node 右侧属性栏：

```text
节点：#67

[设置为监测点]

监测点标准名称：
[10kV火龙线#67.7支]

Aliases:
[火龙线#67.7支]
[10kV火龙线67.7支]
```

不要把监测点原始名称当 `node_id` 或 `monitor_id`。

---

# 13. 历史生产数据适配

参考当前生产 Excel，原始数据包含三相电压、电流、相位，以及状态字段和大量设备辅助字段。

MVP 主流程只标准化：

```text
monitor_name
device_type
terminal_status
line_status
warning_status

Va
Vb
Vc

Ia
Ib
Ic

phase_Va
phase_Vb
phase_Vc

phase_Ia
phase_Ib
phase_Ic

timestamp
```

原始 Excel 中其余列保留，但不参与 MVP Baseline。

---

# 14. Measurement Adapter

## 14.1 字段映射

针对当前生产 Excel，默认映射：

```text
监测点名称1          → monitor_name
设备类型             → device_type
终端状态             → terminal_status
线路状态             → line_status
预警状态             → warning_status

A相电压(kV)          → Va
B相电压(kV)          → Vb
C相电压(kV)          → Vc

A相电流(A)           → Ia
B相电流(A)           → Ib
C相电流(A)           → Ic

A相电压相位          → phase_Va
B相电压相位          → phase_Vb
C相电压相位          → phase_Vc

A相电流相位          → phase_Ia
B相电流相位          → phase_Ib
C相电流相位          → phase_Ic

量测时间             → timestamp
```

字段映射应做成可配置，而不是写死在代码里。

---

## 14.2 无效值清洗

当前生产数据中存在类似：

```text
-9.999
-9999
---
空单元格
```

MVP Adapter 统一转换为：

```python
None
```

注意：
- 不要把 `-9.999 kV` 当真实负电压进入算法。
- 原始值仍应保留在 raw record 中便于追溯。

---

# 15. Monitor Name Matching

生产数据名称可能存在：
- 额外空格
- `10kV / 10KkV`
- `松坪 / 松平`
- `#` 缺失
- 显示后缀差异

因此采用：

```text
Raw monitor name
       ↓
Normalize
       ↓
Exact canonical match
       ↓
Alias match
       ↓
未匹配 → Human Review
```

## 15.1 MVP normalize

只做低风险归一化：
- trim
- 多空格合一
- 全角→半角
- 英文字母大小写统一

**不要自动把“松平”改成“松坪”**。

这种语义修正放到 alias / 人工确认中，避免误绑定。

---

# 16. 正常历史数据筛选

MVP Baseline 优先使用：

```text
device_type == 配电线路
AND terminal_status == 正常
AND line_status == 正常
AND warning_status == 正常
```

再剔除无效值。

---

# 17. Normal Baseline

MVP 暂时不进行线路参数反演。

对于每个 Monitor、每个信号保存：

```python
class BaselineStat:
    monitor_id: str
    signal: str

    count: int
    mean: float | None
    std: float | None
    median: float | None

    start_time: datetime | None
    end_time: datetime | None
```

覆盖信号：

```text
Va Vb Vc
Ia Ib Ic
phase_Va phase_Vb phase_Vc
phase_Ia phase_Ib phase_Ic
```

后续异常特征可计算：

\[
\Delta V=V^{event}-V^{baseline}
\]

\[
\Delta I=I^{event}-I^{baseline}
\]

---

# 18. NETWORK_READY 校验

只有满足全部条件时：

```text
NETWORK_READY = true
```

## 必须条件
- Mapping 无 ERROR。
- 当前闭合运行拓扑为一个有效连通分量。
- 唯一 Source 已设置。
- 每个 `closed` Edge 已设置：
  - line_model_id
  - length_km > 0
- 每个 Line Model 有有效 R/X/C。
- 至少配置 1 个 Monitor。
- 每个 Monitor 有合法 Node。
- 历史数据 Monitor 映射已完成。
- 已生成至少一组有效 Baseline。

## UI

```text
Initialization

Topology Mapping     ✓
Source               ✓
Line Models          ✓
Edge Lengths         ✓
Monitor Mapping      ✓
Normal Data          ✓
Baseline             ✓

NETWORK READY
```

---

# 19. REST API 草案

## Network

```text
POST   /api/networks
GET    /api/networks/{id}
POST   /api/networks/{id}/mapping/import
GET    /api/networks/{id}/validation
POST   /api/networks/{id}/source
GET    /api/networks/{id}/graph
```

## Edge

```text
PATCH  /api/edges/{edge_id}
POST   /api/edges/batch-config
GET    /api/networks/{id}/edges
```

## Line Models

```text
GET    /api/line-models
POST   /api/line-models
PATCH  /api/line-models/{id}
DELETE /api/line-models/{id}
```

## Monitor

```text
GET    /api/networks/{id}/monitors
POST   /api/networks/{id}/monitors
PATCH  /api/monitors/{id}
DELETE /api/monitors/{id}
```

## Measurements

```text
POST   /api/networks/{id}/measurements/import
GET    /api/networks/{id}/measurements/mapping
POST   /api/networks/{id}/measurements/mapping
POST   /api/networks/{id}/baseline/build
GET    /api/networks/{id}/baseline
```

## Ready

```text
GET /api/networks/{id}/readiness
```

---

# 20. 推荐项目目录

```text
backend/
├── app/
│   ├── api/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   │   ├── mapping_import.py
│   │   ├── topology_service.py
│   │   ├── line_model_service.py
│   │   ├── monitor_service.py
│   │   ├── measurement_adapter.py
│   │   ├── monitor_matcher.py
│   │   └── baseline_service.py
│   └── db/
└── tests/

frontend/
├── src/
│   ├── pages/
│   │   ├── NetworkImport/
│   │   ├── TopologyWorkspace/
│   │   ├── LineModelManagement/
│   │   └── NormalDataCalibration/
│   ├── components/
│   └── api/

templates/
└── Topology_Mapping_Template.xlsx
```

---

# 21. 开发阶段与 PASS 条件

## Stage 0 — Schema + DB

完成：
- Network
- Node
- Edge
- LineModel
- Monitor
- BaselineStat

PASS：
- migration 成功
- CRUD 基础测试通过

禁止：
- 故障仿真
- Agent
- PDF 解析

---

## Stage 1 — Mapping Import

完成：
- 上传 Excel
- Validator
- 生成 Node/Edge
- Graph summary

PASS：
- Example_7Bus 能恢复正确 Node/Edge
- 重复边、自环、缺失节点能正确报错

---

## Stage 2 — Topology Workspace

完成：
- React Flow 图
- 自动布局
- Source 设置
- Edge 自动定向
- Edge 单选/多选

PASS：
- 修改 Source 后方向正确重算
- open Edge 不参与运行图

---

## Stage 3 — Line Model + Edge Config

完成：
- Line Model CRUD
- 导线/电缆分类
- Edge 型号 + 长度配置
- 批量型号配置
- 表格视图

PASS：
- 所有 closed Edge 可被完整配置
- R/X/C 引用正确
- 不允许引用停用/不存在型号

---

## Stage 4 — Monitor Configuration

完成：
- Node 添加 Monitor
- canonical_name
- aliases

PASS：
- Monitor 与 Node 稳定关联
- 删除 Node 前检查 Monitor 引用

---

## Stage 5 — Normal Data Adapter

完成：
- 当前生产 Excel 导入
- 字段映射
- `-9.999 / -9999 / ---` 清洗
- Monitor name matching
- 未匹配人工确认

PASS：
- 生产数据可以被标准化
- 不存在异常编码进入数值计算

---

## Stage 6 — Baseline + NETWORK_READY

完成：
- 正常数据筛选
- mean/std/median/count
- readiness 检查

PASS：
- 配置完整网络进入 READY
- 任一必填项缺失时不能 READY

---

# 22. Codex / Claude Code 实施约束

1. **严格按 Stage 顺序开发。**
2. 每次只实现一个 Stage。
3. 不提前添加“未来可能需要”的复杂抽象。
4. 不添加 PDF 自动识别。
5. 不加入 GNN、LLM 数值定位。
6. 不引入 R1/X1/R0/X0。
7. 不用哈希、复杂缓存、事件总线等“防御性工程”扩大 MVP。
8. 每个 Stage 必须有最小自动测试。
9. DB 主键与现场显示名称严格分离。
10. 所有运行拓扑方向必须由 Source 推导，不从 Excel 行顺序推断。

---

# 23. MVP 完成后的下一阶段

当：

```text
Topology Mapping
→ Topology Graph
→ Edge Physics
→ Monitor
→ Normal Baseline
→ NETWORK_READY
```

稳定后，再进入：

```text
PART 2
NETWORK_READY
        ↓
Physics Model Builder
        ↓
Fault Scenario Generator
        ↓
Fault Signature Library
        ↓
Physics Matcher
        ↓
(e*, r*)
```

不要在 Part 1 尚未稳定时开始故障定位算法开发。
