"""
Pydantic 数据模型 — API请求/响应、内部数据结构
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


# ════════════════════════════════════════════════
# 拓扑相关
# ════════════════════════════════════════════════

class NodeModel(BaseModel):
    """单个监测点节点"""
    id: str                    # 节点清洁编号
    orig_pole: str             # 原始杆号/母线号
    line: str                  # 所属拓扑的 topology_id
    depth: int                 # 在树中的深度（电源侧=0）
    parent_id: Optional[str]   # 父节点ID，SOURCE 或 None 表示根
    sides_observed: str        # 大/小/大/小 故障指示器侧面记录
    load_kva: float = 0.0      # 节点本地负荷（kVA，KCL反推）
    status: str = "normal"     # normal | alarm | fault
    is_monitor_point: bool = True  # 是否装有故障指示器（自定义拓扑里可能为False——纯结构性杆塔）


class EdgeModel(BaseModel):
    """拓扑边（线段）"""
    line: str
    from_id: str
    to_id: str
    label: str                 # 如 "27 -> 27.3"
    length_km: float = 0.0
    resistance_ohm: float = 0.0
    reactance_ohm: float = 0.0


class TopologyResponse(BaseModel):
    line: str
    nodes: list[NodeModel]
    edges: list[EdgeModel]
    node_count: int
    edge_count: int


# ════════════════════════════════════════════════
# 自定义拓扑（用户上传节点/边表，通用于任意线路）
# ════════════════════════════════════════════════

class CustomTopologyMeta(BaseModel):
    id: str
    name: str
    node_count: int
    edge_count: int
    monitor_point_count: int = 0
    created_at: str = ""


class CustomNodeRaw(BaseModel):
    """上传/展示用的原始节点（未做监测点折叠），管理页表格用这个"""
    node_id: str
    label: str
    is_monitor_point: bool
    depth: int
    parent_id: Optional[str] = None


class CustomEdgeRaw(BaseModel):
    from_id: str
    to_id: str
    length_km: float = 0.0
    resistance_ohm: float = 0.0
    reactance_ohm: float = 0.0


class CustomTopologyDetail(BaseModel):
    id: str
    name: str
    nodes: list[CustomNodeRaw]
    edges: list[CustomEdgeRaw]


class CustomTopologyUploadResult(BaseModel):
    ok: bool
    id: str = ""
    name: str = ""
    node_count: int = 0
    edge_count: int = 0
    warnings: list[str] = []
    error: str = ""


class SetMonitorPointsRequest(BaseModel):
    node_ids: list[str]
    is_monitor_point: bool


class SetEdgeParamsRequest(BaseModel):
    """
    length_km 是每条边各自的物理长度，同批边不一定相等，提供了就统一覆盖成这个值。
    resistance_ohm_per_km / reactance_ohm_per_km 是"每公里"电抗参数——这才是"同规格
    线路批量设置"里真正相同的东西（同一种导线的单位电阻电抗），不是总电阻/电抗；
    每条边最终存的 resistance_ohm/reactance_ohm 由 (per_km值 × 该边的length_km) 算出，
    这样长度不同的边套用同一种导线规格时，各自的总阻抗依然是对的。
    """
    edges: list[tuple[str, str]] = Field(..., description="[(from_id, to_id), ...] 需要批量设置的边")
    length_km: Optional[float] = None
    resistance_ohm_per_km: Optional[float] = None
    reactance_ohm_per_km: Optional[float] = None


# ════════════════════════════════════════════════
# 故障定位相关
# ════════════════════════════════════════════════

class FaultLocateRequest(BaseModel):
    line: str = Field(..., description="拓扑的 topology_id")
    alarm_points: list[str] = Field(..., description="报警监测点列表（node_id 或 label）")
    fault_type: Optional[str] = Field(None, description="已知故障类型，可选")
    event_time: Optional[str] = Field(None, description="该次事件发生时间，可选——用于精确关联电气量原始记录（同一监测点历史上可能有多次不同事件），不提供则电气量分析取该点最新一条记录")


class FaultSection(BaseModel):
    from_pole: str
    to_pole: str
    from_id: str
    to_id: str
    confidence: str            # high | medium | low


class FaultLocateResponse(BaseModel):
    event_id: str
    line: str
    alarm_points: list[str]
    frontier_points: list[str]     # 报警前沿节点（最下游报警点）
    candidate_sections: list[FaultSection]
    confidence: str
    note: str
    alarmed_node_ids: list[str]    # 用于前端高亮
    electrical_analysis: Optional["EventElectricalAnalysis"] = None  # 电气量推理（可选增强，无匹配数据时为None）


# ════════════════════════════════════════════════
# 电气量分析 / 推理相关（core/electrical_inference.py）
# 数据源是用户为每个自定义拓扑上传的历史电气量数据（基线+事件），不再绑定任何
# 固定线路或固定文件——同一套模型/算法对任意拓扑通用。
# ════════════════════════════════════════════════

class PhaseReading(BaseModel):
    """单相在某一时刻的电气量读数与初步判断"""
    phase: str                             # A | B | C
    voltage_kv: Optional[float] = None     # None 表示该相读数为哨兵值（传感器未测得有效值）
    current_a: Optional[float] = None
    is_faulted: bool = False               # 读数是哨兵值，或显著偏离该节点正常基准
    deviation_pct: Optional[float] = None  # 相对该点正常基准电压的偏离百分比（仅当有有效读数时）


class NodeElectricalAnalysis(BaseModel):
    """单个监测点在某次事件中的电气量分析"""
    pole: str
    node_id: str
    reading_time: Optional[str] = None
    phases: list[PhaseReading] = []
    faulted_phases: list[str] = []          # 判定异常的相，如 ["B"]
    imbalance_ratio: Optional[float] = None  # 三相不平衡度（最大偏差/平均值，仅统计有效相）
    severity_score: float = 0.0             # 综合异常评分 0-100，越高越严重（启发式，非精确物理量）
    consistent_with_report: Optional[bool] = None  # 电压异常相 是否与报警文本描述的故障相一致（若有提供）


class EventElectricalAnalysis(BaseModel):
    """
    一次故障事件的电气量分析汇总——基于该拓扑自己上传的历史电气量数据。
    这是 MVP 阶段的启发式规则算法（不是训练出的模型），样本量取决于用户上传了多少历史数据，
    误差可能较大，定位为矩阵法主结论的辅助佐证，不替代矩阵法。
    """
    matched: bool = False                   # 是否找到了对应的原始电气量记录
    node_analyses: list[NodeElectricalAnalysis] = []
    inferred_fault_phases: list[str] = []   # 综合推断的故障相（跨所有匹配到数据的监测点）
    severity_label: str = "unknown"         # high | medium | low | unknown
    note: str = ""


# ── 历史电气量数据上传 + 自动推理（不需要人工先给报警点） ──────────────

class UploadHistoricalDataResult(BaseModel):
    ok: bool
    baseline_rows: int = 0       # 写入的基线（正常）读数行数
    event_count: int = 0         # 识别出的历史事件个数（按 event_id 分组）
    event_rows: int = 0          # 写入的事件读数行数
    warnings: list[str] = []
    error: str = ""


class HistoricalEventSummary(BaseModel):
    event_id: str
    timestamp: str = ""
    node_ids: list[str] = []     # 该事件快照里出现读数的监测点


class InferResult(BaseModel):
    """
    自动推理入口的结果：不需要人工先指定报警点，直接从一次事件的原始电气量快照里
    自动判断哪些监测点异常（推断报警点），再复用现成的矩阵法算出故障区段。
    """
    ok: bool = False
    inferred_alarm_points: list[str] = []
    fault_locate: Optional["FaultLocateResponse"] = None
    note: str = ""


# ════════════════════════════════════════════════
# 历史事件相关
# ════════════════════════════════════════════════

class HistoryEvent(BaseModel):
    event_id: str
    line: str
    time: str
    fault_types: str
    alarmed_points: str
    frontier: str
    candidate_sections: str
    note: str
    confidence: str = "unknown"
    source: str = "historical"  # historical=历史导入 | live=系统实际使用中生成


# ════════════════════════════════════════════════
# Agent对话相关
# ════════════════════════════════════════════════

class AgentMessage(BaseModel):
    role: str                  # user | assistant
    content: str


class AgentChatRequest(BaseModel):
    messages: list[AgentMessage]
    provider: str = "deepseek"  # deepseek | qwen | openai
    line: Optional[str] = None  # 当前上下文线路


class AgentChatResponse(BaseModel):
    content: str
    tool_calls: list[dict] = []
    finish_reason: str = "stop"


# ════════════════════════════════════════════════
# 系统配置相关
# ════════════════════════════════════════════════

class LLMConfigRequest(BaseModel):
    provider: str
    api_key: str
    base_url: str
    model: str


class LLMTestResponse(BaseModel):
    ok: bool
    message: str
    provider: str
    model: str


# FaultLocateResponse 引用了下面才定义的 EventElectricalAnalysis，InferResult 引用了
# 上面的 FaultLocateResponse（字符串前向引用，配合文件头部 from __future__ import
# annotations）；显式 rebuild 确保引用关系被正确解析。
FaultLocateResponse.model_rebuild()
InferResult.model_rebuild()
