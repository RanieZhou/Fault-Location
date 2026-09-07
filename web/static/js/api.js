/**
 * api.js — 后端API封装（目前使用本地算法实现，后端完成后自动切换）
 */

const API_BASE = '';  // 同源，后端启动后自动有效

// 判断后端是否可用
let _backendAvailable = false;
async function checkBackend() {
  try {
    const r = await fetch(`${API_BASE}/api/health`, { signal: AbortSignal.timeout(2000) });
    _backendAvailable = r.ok;
  } catch {
    _backendAvailable = false;
  }
  updateBackendStatus();
  return _backendAvailable;
}

function updateBackendStatus() {
  const el = document.getElementById('backend-status');
  if (el) el.textContent = _backendAvailable ? '✅ 在线' : '⚠️ 离线（使用本地模式）';
  if (el) el.style.color = _backendAvailable ? 'var(--green)' : 'var(--amber)';
}

// ======================== 故障定位 API ========================

// 后端 /api/fault/locate 返回的是"扁平"结构（frontier_points + candidate_sections 整体一份，
// 整体confidence/note），而前端渲染(renderFaultResult)和本地矩阵法fallback用的是"按前沿点分组"
// 结构（results: [{frontier_pole, candidate_poles, confidence, note}, ...]）。
// 这里把后端响应转换成和本地fallback一致的形状，这样调用方不用关心数据到底来自后端还是本地。
function normalizeBackendFaultResult(backendResult) {
  const byFrontierPole = {};
  (backendResult.candidate_sections || []).forEach(s => {
    if (!byFrontierPole[s.from_pole]) {
      byFrontierPole[s.from_pole] = { from_id: s.from_id, sections: [] };
    }
    byFrontierPole[s.from_pole].sections.push(s);
  });

  const results = (backendResult.frontier_points || []).map(frontierPole => {
    const group = byFrontierPole[frontierPole];
    const sections = group ? group.sections : [];
    const validCands = sections.filter(s => s.to_pole !== '(末端)');
    return {
      frontier_id: group ? group.from_id : '',
      frontier_pole: frontierPole,
      candidate_ids: validCands.map(s => s.to_id),
      candidate_poles: validCands.map(s => s.to_pole),
      note: backendResult.note || '',
      confidence: (sections[0] && sections[0].confidence) || backendResult.confidence || 'low',
    };
  });

  return {
    event_id: backendResult.event_id,
    line_code: backendResult.line_code || backendResult.line,
    alarm_poles: backendResult.alarm_poles || backendResult.alarm_points || [],
    alarm_ids: backendResult.alarmed_node_ids || [],
    results,
    not_found: [],
    method: 'backend_matrix',
    electrical_analysis: backendResult.electrical_analysis || null,
  };
}
window.normalizeBackendFaultResult = normalizeBackendFaultResult;


window.apiFaultLocate = async function(lineCode, alarmPoles, faultType, eventTime) {
  if (!_backendAvailable) return { error: '后端服务未启动，无法定位' };
  try {
    const r = await fetch(`${API_BASE}/api/fault/locate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ line_code: lineCode, alarm_poles: alarmPoles, fault_type: faultType, event_time: eventTime || null }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return { error: data.detail || '定位失败' };
    return normalizeBackendFaultResult(data);
  } catch (e) {
    return { error: e.message || '定位请求失败' };
  }
};

// ======================== LLM 配置 API ========================
window.apiSaveLLMConfig = async function(provider, config) {
  if (_backendAvailable) {
    try {
      const r = await fetch(`${API_BASE}/api/settings/llm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, ...config }),
      });
      if (r.ok) return await r.json();
    } catch {}
  }
  // 本地存储 fallback
  localStorage.setItem('llm_config', JSON.stringify({ provider, ...config }));
  return { ok: true, message: '已保存到本地（后端离线）' };
};

// 查询当前LLM配置状态（用于页面加载时恢复顶部"已连接/未连接"显示）。
// 配置的权威来源是后端（.env文件 + 运行时内存），不是浏览器localStorage——
// 通过网页"系统设置"保存时，后端在线的话配置只会写到后端，从不写localStorage，
// 所以恢复状态必须真的去问后端，不能只看本地缓存。
window.apiGetLLMConfig = async function() {
  if (_backendAvailable) {
    try {
      const r = await fetch(`${API_BASE}/api/settings/llm`, { signal: AbortSignal.timeout(3000) });
      if (r.ok) return await r.json();
    } catch {}
  }
  // 后端不可用时，退回看本地缓存（离线模式下保存的配置）
  try {
    const saved = JSON.parse(localStorage.getItem('llm_config') || '{}');
    return { provider: saved.provider || '', configured: !!saved.provider };
  } catch {
    return { provider: '', configured: false };
  }
};

window.apiTestLLMConnection = async function(provider, config) {
  if (_backendAvailable) {
    try {
      const r = await fetch(`${API_BASE}/api/settings/llm/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, ...config }),
        signal: AbortSignal.timeout(15000),
      });
      return await r.json();
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }
  return { ok: false, error: '后端未启动，无法测试连接' };
};

// 拉取指定 api_key/base_url 下可用的模型列表（"第三方/自定义"面板的"获取模型列表"按钮用）
window.apiFetchModels = async function(apiKey, baseUrl) {
  if (!_backendAvailable) {
    return { ok: false, message: '后端未启动，无法获取模型列表', models: [] };
  }
  try {
    const r = await fetch(`${API_BASE}/api/settings/llm/models`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: apiKey, base_url: baseUrl }),
      signal: AbortSignal.timeout(20000),
    });
    return await r.json();
  } catch (e) {
    return { ok: false, message: e.message, models: [] };
  }
};

// 拉取所有provider已保存的完整配置（含明文key），用于"系统设置"页面加载时把表单
// 回填成上次保存的样子——否则每次进这个页面表单都是空的，看起来像"配置丢了"
window.apiGetAllLLMConfigs = async function() {
  if (!_backendAvailable) return { active_provider: '', configs: {} };
  try {
    const r = await fetch(`${API_BASE}/api/settings/llm/all`, { signal: AbortSignal.timeout(5000) });
    if (r.ok) return await r.json();
  } catch {}
  return { active_provider: '', configs: {} };
};

// ======================== Agent 聊天 API ========================
window.apiAgentChat = async function* (messages, provider) {
  if (!_backendAvailable) {
    yield { type: 'error', content: '后端服务未启动。请先运行：\n\npython -m uvicorn web.app:app --reload\n\n然后刷新页面重试。' };
    return;
  }
  const r = await fetch(`${API_BASE}/api/agent/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, provider }),
  });
  if (!r.ok) {
    yield { type: 'error', content: `API错误 ${r.status}: ${await r.text()}` };
    return;
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop();
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6).trim();
        if (data === '[DONE]') return;
        try { yield JSON.parse(data); } catch {}
      }
    }
  }
};

// ======================== 自定义拓扑 API ========================
// 用户上传节点表+边表，通用于任意拓扑——系统里唯一的拓扑数据来源。
// 完整设计见 core/custom_topology.py 顶部注释。

window.apiListCustomTopologies = async function() {
  const r = await fetch(`${API_BASE}/api/custom-topology/`);
  if (!r.ok) return [];
  const data = await r.json();
  return data.topologies || [];
};

window.apiUploadCustomTopology = async function(name, nodesFile, edgesFile) {
  const form = new FormData();
  form.append('name', name);
  if (nodesFile) form.append('nodes_file', nodesFile);
  form.append('edges_file', edgesFile);
  const r = await fetch(`${API_BASE}/api/custom-topology/upload`, { method: 'POST', body: form });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) return { ok: false, error: data.detail || '上传失败' };
  return data;
};

window.apiGetCustomTopologyDetail = async function(id) {
  const r = await fetch(`${API_BASE}/api/custom-topology/${id}`);
  if (!r.ok) return null;
  return await r.json();
};

window.apiGetCustomTopologyPreview = async function(id) {
  const r = await fetch(`${API_BASE}/api/custom-topology/${id}/preview`);
  if (!r.ok) return null;
  return await r.json();
};

window.apiSetCustomMonitorPoints = async function(id, nodeIds, isMonitorPoint) {
  const r = await fetch(`${API_BASE}/api/custom-topology/${id}/nodes`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ node_ids: nodeIds, is_monitor_point: isMonitorPoint }),
  });
  return await r.json().catch(() => ({ ok: false }));
};

window.apiSetCustomEdgeParams = async function(id, edges, params) {
  const r = await fetch(`${API_BASE}/api/custom-topology/${id}/edges`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ edges, ...params }),
  });
  const data = await r.json().catch(() => ({ ok: false }));
  if (!r.ok) return { ok: false, error: data.detail || '设置失败' };
  return data;
};

window.apiDeleteCustomTopology = async function(id) {
  const r = await fetch(`${API_BASE}/api/custom-topology/${id}`, { method: 'DELETE' });
  return await r.json().catch(() => ({ ok: false }));
};

// ── 历史电气量数据（基线+事件）+ 自动推理 ──────────────────────────

window.apiUploadHistoricalData = async function(topoId, baselineFile, eventFile) {
  const form = new FormData();
  if (baselineFile) form.append('baseline_file', baselineFile);
  if (eventFile) form.append('event_file', eventFile);
  const r = await fetch(`${API_BASE}/api/custom-topology/${topoId}/historical-data/upload`, { method: 'POST', body: form });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) return { ok: false, error: data.detail || '上传失败' };
  return data;
};

window.apiListTopologyEvents = async function(topoId) {
  const r = await fetch(`${API_BASE}/api/custom-topology/${topoId}/historical-data/events`);
  if (!r.ok) return [];
  const data = await r.json();
  return data.events || [];
};

window.apiInferFaultFromEvent = async function(topoId, eventId) {
  const r = await fetch(`${API_BASE}/api/custom-topology/${topoId}/historical-data/events/${eventId}/infer`, { method: 'POST' });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) return { ok: false, note: data.detail || '推理失败' };
  return data;
};

// ======================== 生产级监测数据 API ========================

window.apiUploadMonitoringData = async function(file, topologyId) {
  const form = new FormData();
  form.append('file', file);
  if (topologyId) form.append('topology_id', topologyId);
  try {
    const r = await fetch(`${API_BASE}/api/fault/monitoring/upload`, { method: 'POST', body: form });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return { ok: false, error: data.detail || '上传解析失败' };
    return data;
  } catch (e) {
    return { ok: false, error: e.message };
  }
};

window.apiListMonitoringEvents = async function(topologyId) {
  try {
    let url = `${API_BASE}/api/fault/monitoring/events`;
    if (topologyId) url += `?topology_id=${encodeURIComponent(topologyId)}`;
    const r = await fetch(url);
    if (!r.ok) return [];
    const data = await r.json().catch(() => ({ events: [] }));
    return data.events || [];
  } catch {
    return [];
  }
};

window.apiQueryMonitoringRecords = async function(params) {
  try {
    const qs = new URLSearchParams();
    Object.entries(params || {}).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') qs.set(k, v); });
    const r = await fetch(`${API_BASE}/api/fault/monitoring/records?${qs.toString()}`);
    if (!r.ok) return { items: [], total: 0, page: 1, page_size: 10 };
    return await r.json();
  } catch {
    return { items: [], total: 0, page: 1, page_size: 10 };
  }
};

window.apiGetMonitoringFilterOptions = async function(topologyId) {
  try {
    let url = `${API_BASE}/api/fault/monitoring/records/filter-options`;
    if (topologyId) url += `?topology_id=${encodeURIComponent(topologyId)}`;
    const r = await fetch(url);
    if (!r.ok) return { device_types: [], line_statuses: [], terminal_statuses: [], warning_statuses: [] };
    return await r.json();
  } catch {
    return { device_types: [], line_statuses: [], terminal_statuses: [], warning_statuses: [] };
  }
};

window.apiGetMonitoringEventDetails = async function(eventId) {
  try {
    const r = await fetch(`${API_BASE}/api/fault/monitoring/events/${encodeURIComponent(eventId)}`);
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
};

window.apiReproduceMonitoringEvent = async function(eventId) {
  try {
    const r = await fetch(`${API_BASE}/api/fault/monitoring/events/${encodeURIComponent(eventId)}/reproduce`, { method: 'POST' });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) return { ok: false, error: data.detail || '复现失败' };
    // 归一化后端定位结果结构
    if (data.fault_locate) {
      data.normalized_locate = normalizeBackendFaultResult(data.fault_locate);
    }
    return data;
  } catch (e) {
    return { ok: false, error: e.message };
  }
};

window.apiSeedSampleMonitoringData = async function() {
  try {
    const r = await fetch(`${API_BASE}/api/fault/monitoring/seed-sample`, { method: 'POST' });
    return await r.json();
  } catch (e) {
    return { ok: false, message: e.message };
  }
};

window.apiClearMonitoringData = async function(topologyId) {
  try {
    let url = `${API_BASE}/api/fault/monitoring/clear`;
    if (topologyId) url += `?topology_id=${encodeURIComponent(topologyId)}`;
    const r = await fetch(url, { method: 'DELETE' });
    return await r.json();
  } catch (e) {
    return { ok: false, error: e.message };
  }
};


// 把自定义拓扑的"折叠后监测点视图"转换成前端渲染统一形状——这是算法实际使用的
// 简化树（跳过了所有非监测点的结构杆塔），只适合用在"只关心监测点"的场景：
// 故障定位页的报警点快速选择列表、迷你结果图（只有监测点才可能真的"报警"）。
window.normalizeCustomTopoAsTopoData = function(preview) {
  const nodes = [{ id: 'SOURCE', label: '变电站', depth: -1, parent: null, pole: 'SOURCE' }];
  preview.nodes.forEach(n => {
    nodes.push({
      id: n.id, label: n.orig_pole, pole: n.orig_pole,
      depth: n.depth, parent: n.parent_id || 'SOURCE',
    });
  });
  return {
    name: preview.name, nodeCount: preview.node_count, faultCount: 0, branchCount: 0,
    nodes, loads: {}, __fromApi: true, __isCustom: true,
  };
};

// 把自定义拓扑的"完整物理图"（含未装监测设备的结构杆塔）转换成前端渲染统一形状——
// "拓扑监控"主页要看的是真实拓扑长什么样（监测点只是其中一部分，会单独着色区分），
// 不是算法内部用的折叠简化树，两者是不同的展示目的，不能共用同一份数据。
window.normalizeCustomTopoFullAsTopoData = function(detail) {
  const nodes = [{ id: 'SOURCE', label: '变电站', depth: -1, parent: null, pole: 'SOURCE', isMonitorPoint: false }];
  const childCount = {};
  let monitorCount = 0;
  detail.nodes.forEach(n => {
    nodes.push({
      id: n.node_id, label: n.label, pole: n.label,
      depth: n.depth, parent: n.parent_id || 'SOURCE',
      isMonitorPoint: !!n.is_monitor_point,
    });
    if (n.is_monitor_point) monitorCount++;
    if (n.parent_id) childCount[n.parent_id] = (childCount[n.parent_id] || 0) + 1;
  });
  const branchCount = Object.values(childCount).filter(c => c > 1).length;
  return {
    name: detail.name, nodeCount: monitorCount, totalNodeCount: detail.nodes.length,
    faultCount: 0, branchCount,
    nodes, loads: {}, __fromApi: true, __isCustom: true, __isFullView: true,
  };
};

// 启动时检查后端
setTimeout(checkBackend, 500);
setInterval(checkBackend, 30000);
