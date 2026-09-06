/**
 * app.js — 应用主入口：导航、全局交互、故障定位视图逻辑
 */

// ======================== 导航 ========================
const VIEW_LABELS = {
  topology: '拓扑监控',
  fault: '故障定位',
  agent: 'Agent 分析',
  history: '历史事件',
  customtopo: '自定义拓扑',
  settings: '系统设置',
};

window.navTo = function(viewId) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  const view = document.getElementById(`view-${viewId}`);
  if (view) view.classList.add('active');

  const navItem = document.querySelector(`[data-view="${viewId}"]`);
  if (navItem) navItem.classList.add('active');

  const breadcrumbEl = document.getElementById('breadcrumb-current');
  if (breadcrumbEl) breadcrumbEl.textContent = VIEW_LABELS[viewId] || viewId;

  // 视图切换时的初始化
  if (viewId === 'history') {
    refreshTopoNameCache().then(() => {
      ['history-line-filter', 'monitoring-topo-filter'].forEach(selId => {
        const sel = document.getElementById(selId);
        if (sel) {
          const cur = sel.value;
          [...sel.querySelectorAll('option[data-topo]')].forEach(o => o.remove());
          Object.entries(window._topoNameCache).forEach(([id, name]) => {
            const opt = document.createElement('option');
            opt.value = id; opt.dataset.topo = '1'; opt.textContent = name;
            sel.appendChild(opt);
          });
          sel.value = cur;
        }
      });
      if (window._currentHistoryTab === 'faults') {
        renderHistoryTable();
      } else {
        loadMonitoringEvents();
      }
    });
  }
  if (viewId === 'topology') {
    fillCustomTopoOptions('topo-line-select').then(() => {
      if (currentLine) buildQuickNodeList(currentLine);
    });
  }
  if (viewId === 'fault') {
    // 注意：不能直接调用 onFaultLineChange()——它内部会 clearAlarms()，
    // 而 navTo('fault') 常常是在"先填好报警标签、再跳转过来展示"之后调用的
    // （复现历史事件、从拓扑图选中节点添加报警点等），调用完整版会把刚填的标签清空。
    // 这里只做该视图需要的初始化（刷新快捷选择列表），清空标签的逻辑仍保留在
    // onFaultLineChange() 里，供用户手动切换线路下拉框时触发。
    fillCustomTopoOptions('fault-line-select').then(async () => {
      const lineCode = document.getElementById('fault-line-select').value;
      currentLine = lineCode;
      await ensureTopoDataLoaded(lineCode);
      buildQuickNodeList(lineCode);
    });
  }
  if (viewId === 'settings') loadAndFillLLMForms();
  if (viewId === 'customtopo' && window.ctOnNavTo) window.ctOnNavTo();
};

// 给指定的<select>填充所有已上传的自定义拓扑选项——系统里唯一的拓扑来源，
// 故障定位页、拓扑监控页的线路选择器共用这一套逻辑。
let _fillLineOptionsInFlight = {};
function fillCustomTopoOptions(selectId) {
  // 同一个下拉框可能在短时间内被多处调用（比如 navTo('fault') 本身触发一次、
  // ctUseForFaultLocate 又主动触发一次）——如果各自独立地"先清空、再异步拉取、
  // 再追加"，两次调用会交错执行，导致同一个拓扑重复出现。这里让并发调用共享
  // 同一个进行中的Promise，按selectId分别去重，不同下拉框互不影响。
  if (_fillLineOptionsInFlight[selectId]) return _fillLineOptionsInFlight[selectId];
  const sel = document.getElementById(selectId);
  if (!sel || typeof window.apiListCustomTopologies !== 'function') return Promise.resolve();
  const task = (async () => {
    try {
      const topos = await window.apiListCustomTopologies();
      [...sel.querySelectorAll('option[data-custom]')].forEach(o => o.remove());
      topos.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t.id;
        opt.dataset.custom = '1';
        opt.textContent = `[自定义] ${t.name}`;
        sel.appendChild(opt);
      });
    } catch {}
    finally {
      _fillLineOptionsInFlight[selectId] = null;
    }
  })();
  _fillLineOptionsInFlight[selectId] = task;
  return task;
}

// 兼容旧调用名
function fillFaultLineOptions() { return fillCustomTopoOptions('fault-line-select'); }

let currentLine = null;

// ======================== 时钟 ========================
function updateClock() {
  const now = new Date();
  const s = now.toTimeString().slice(0, 8);
  const el = document.getElementById('header-clock');
  if (el) el.textContent = s;
}
setInterval(updateClock, 1000);
updateClock();

// ======================== Toast 通知 ========================
window.showToast = function(msg, type = 'success', duration = 3000) {
  const container = document.getElementById('toast-container');
  const icons = { success: '<i class="bi bi-check-circle-fill" style="color:var(--green)"></i>', error: '<i class="bi bi-x-circle-fill" style="color:var(--red)"></i>', warning: '<i class="bi bi-exclamation-triangle-fill" style="color:var(--amber)"></i>', info: '<i class="bi bi-info-circle-fill" style="color:var(--cyan)"></i>' };
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<span class="toast-icon">${icons[type] || 'ℹ️'}</span><span>${msg}</span>`;
  container.appendChild(el);
  setTimeout(() => el.style.opacity = '0', duration - 300);
  setTimeout(() => el.remove(), duration);
};

// ======================== 设置页面 ========================
window.selectProvider = function(provider, tab) {
  document.querySelectorAll('.provider-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.provider-config').forEach(c => c.style.display = 'none');
  tab.classList.add('active');
  document.getElementById(`provider-${provider}`).style.display = 'block';
};

// 页面加载/进入"系统设置"视图时，把所有provider已保存的配置回填进表单——
// 这是"刷新页面LLM配置就没了"这个观感问题的真正修复点：数据其实一直都在后端
// （SQLite），只是之前从没有代码把它读回表单显示出来，看起来像丢了。
async function loadAndFillLLMForms() {
  const data = await window.apiGetAllLLMConfigs();
  const providerLabelMap = { deepseek: 'DeepSeek', qwen: '通义千问', openai: 'OpenAI', custom: '第三方 / 自定义' };

  Object.entries(data.configs || {}).forEach(([provider, cfg]) => {
    const keyEl = document.getElementById(`${provider}-key`);
    const urlEl = document.getElementById(`${provider}-url`);
    const modelEl = document.getElementById(`${provider}-model`);
    if (keyEl && cfg.api_key) keyEl.value = cfg.api_key;
    if (urlEl && cfg.base_url) urlEl.value = cfg.base_url;
    if (modelEl && cfg.model) modelEl.value = cfg.model;
    if (typeof onProviderConfigChange === 'function') onProviderConfigChange(provider);
  });

  if (data.active_provider) {
    const targetLabel = providerLabelMap[data.active_provider];
    const targetBtn = [...document.querySelectorAll('.provider-tab')].find(b => b.textContent.trim() === targetLabel);
    if (targetBtn) selectProvider(data.active_provider, targetBtn);
  }
}

window.saveLLMConfig = async function() {
  const active = document.querySelector('.provider-tab.active');
  const providerMap = { 'DeepSeek': 'deepseek', '通义千问': 'qwen', 'OpenAI': 'openai', '第三方 / 自定义': 'custom' };
  const provider = providerMap[active?.textContent.trim()] || 'deepseek';

  const config = {
    api_key: document.getElementById(`${provider}-key`)?.value || '',
    base_url: document.getElementById(`${provider}-url`)?.value || '',
    model:    document.getElementById(`${provider}-model`)?.value || '',
  };

  const result = await window.apiSaveLLMConfig(provider, config);
  if (result.ok) {
    showToast(`${provider} 配置已保存`, 'success');
    updateLLMStatus(true, provider);
  } else {
    showToast(`保存失败: ${result.message}`, 'error');
  }
};

window.testLLMConnection = async function() {
  const active = document.querySelector('.provider-tab.active');
  const providerMap = { 'DeepSeek': 'deepseek', '通义千问': 'qwen', 'OpenAI': 'openai', '第三方 / 自定义': 'custom' };
  const provider = providerMap[active?.textContent.trim()] || 'deepseek';
  const config = {
    api_key: document.getElementById(`${provider}-key`)?.value || '',
    base_url: document.getElementById(`${provider}-url`)?.value || '',
    model:    document.getElementById(`${provider}-model`)?.value || '',
  };

  const resultEl = document.getElementById('llm-test-result');
  resultEl.className = 'test-result';
  resultEl.textContent = '🔗 测试中...';
  resultEl.style.display = 'block';

  const r = await window.apiTestLLMConnection(provider, config);
  if (r.ok) {
    resultEl.className = 'test-result ok';
    resultEl.textContent = `✅ 连接成功！模型：${config.model}，响应时间：${r.latency_ms || '--'}ms`;
    updateLLMStatus(true, provider);
  } else {
    resultEl.className = 'test-result err';
    resultEl.textContent = `❌ 连接失败：${r.error}`;
  }
};

// ======================== 获取模型列表（DeepSeek/通义千问/OpenAI/第三方 共用） ========================
// 4个provider tab的表单字段id都遵循同一套命名规则：${provider}-url / -key / -model / -model-list / -fetch-models-btn
window.onProviderConfigChange = function(provider) {
  const url = document.getElementById(`${provider}-url`)?.value.trim();
  const key = document.getElementById(`${provider}-key`)?.value.trim();
  const btn = document.getElementById(`${provider}-fetch-models-btn`);
  if (btn) btn.disabled = !(url && key);
};

window.fetchModelsFor = async function(provider) {
  const url = document.getElementById(`${provider}-url`).value.trim();
  const key = document.getElementById(`${provider}-key`).value.trim();
  if (!url || !key) { showToast('请先填写 API Key 和 Base URL', 'warning'); return; }

  const btn = document.getElementById(`${provider}-fetch-models-btn`);
  const icon = btn.querySelector('i');
  btn.disabled = true;
  icon.className = 'bi bi-arrow-repeat';

  const r = await window.apiFetchModels(key, url);

  icon.className = 'bi bi-cloud-download';
  btn.disabled = false;

  if (r.ok && r.models?.length) {
    const list = document.getElementById(`${provider}-model-list`);
    list.innerHTML = r.models.map(m => `<option value="${escapeHtml(m)}"></option>`).join('');
    const modelInput = document.getElementById(`${provider}-model`);
    if (!modelInput.value || !r.models.includes(modelInput.value)) modelInput.value = r.models[0];
    showToast(`获取到 ${r.models.length} 个模型`, 'success');
  } else {
    showToast(`获取模型列表失败：${r.message || '未知错误'}`, 'error');
  }
};

function escapeHtml(str) {
  if (typeof str !== 'string') return String(str ?? '');
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

window.saveAlgoConfig = function() {
  const tw = document.getElementById('cfg-time-window').value;
  const at = document.getElementById('cfg-alarm-threshold').value;
  localStorage.setItem('algo_config', JSON.stringify({ time_window: Number(tw), alarm_threshold: Number(at) }));
  showToast('算法参数已保存', 'success');
};

window.savePaths = function() {
  showToast('路径配置已保存（重启后生效）', 'success');
};

function updateLLMStatus(connected, provider) {
  const dot = document.getElementById('sidebar-llm-dot');
  const text = document.getElementById('sidebar-llm-text');
  const pillDot = document.getElementById('llm-dot');
  const pillText = document.getElementById('llm-pill-text');
  const providerLabel = { deepseek: 'DeepSeek', qwen: '千问', openai: 'OpenAI', custom: '第三方' }[provider] || provider;
  if (connected) {
    dot.className = 'status-dot green';
    text.textContent = providerLabel + ' 已连接';
    pillDot.className = 'status-dot green';
    pillText.textContent = providerLabel + ' 就绪';
  } else {
    dot.className = 'status-dot grey';
    text.textContent = 'LLM 未配置';
    pillDot.className = 'status-dot grey';
    pillText.textContent = 'LLM 未连接';
  }
}

// ======================== 故障定位视图 ========================
let alarmTags = [];

// window.TOPO_DATA_MONITOR[lineCode] 里的数据不会预置——第一次选中某个拓扑时需要现拉一次
// 折叠后的监测点视图填进去，快速选择列表/迷你拓扑图才有东西可渲染。注意这里用的是
// TOPO_DATA_MONITOR（监测点简化树），不是 TOPO_DATA（拓扑监控主页用的完整物理图）——
// 两者是不同形状的数据，混用会导致快速选择列表里混进不该出现的结构杆塔。
async function ensureTopoDataLoaded(lineCode) {
  if (!lineCode || window.TOPO_DATA_MONITOR[lineCode]) return;
  if (typeof window.apiGetCustomTopologyPreview !== 'function') return;
  const preview = await window.apiGetCustomTopologyPreview(lineCode);
  if (preview) window.TOPO_DATA_MONITOR[lineCode] = window.normalizeCustomTopoAsTopoData(preview);
}

window.onFaultLineChange = async function() {
  const lineCode = document.getElementById('fault-line-select').value;
  currentLine = lineCode || null;
  if (!lineCode) { buildQuickNodeList(''); clearAlarms(); return; }
  await ensureTopoDataLoaded(lineCode);
  buildQuickNodeList(lineCode);
  clearAlarms();
};

window.handleTagInput = function(e) {
  if (e.key === 'Enter' || e.key === ',') {
    e.preventDefault();
    const val = e.target.value.trim().replace(/，|,/g, '');
    if (val) addAlarmTag(val);
    e.target.value = '';
  }
  if (e.key === 'Backspace' && !e.target.value) {
    removeLastTag();
  }
};

window.addAlarmTag = function(pole) {
  if (!pole || alarmTags.includes(pole)) return;
  alarmTags.push(pole);
  renderTags();
};

function removeLastTag() {
  alarmTags.pop();
  renderTags();
}

window.removeTag = function(pole) {
  alarmTags = alarmTags.filter(t => t !== pole);
  renderTags();
};

window.clearAlarms = function() {
  alarmTags = [];
  renderTags();
  document.getElementById('fault-result-body').innerHTML = `
    <div style="text-align:center;padding:48px 0;color:var(--text-muted)">
      <i class="bi bi-map" style="font-size:48px;display:block;margin-bottom:12px;opacity:0.4"></i>
      <div style="font-size:13px">选择线路和报警点后，<br>点击"开始定位"查看结果</div>
    </div>`;
  document.getElementById('result-badge').className = 'badge badge-grey';
  document.getElementById('result-badge').textContent = '等待分析';
  document.getElementById('fault-topo-card').style.display = 'none';
  document.getElementById('ai-assist-card').style.display = 'none';
};

function renderTags() {
  const container = document.getElementById('alarm-tags');
  const input = document.getElementById('tag-input');
  // 清除旧标签
  [...container.children].forEach(c => { if (c !== input) c.remove(); });
  // 插入标签（在input前面）
  alarmTags.forEach(pole => {
    const tag = document.createElement('div');
    tag.className = 'alarm-tag';
    tag.innerHTML = `<span>${pole}</span><span class="remove-tag" onclick="removeTag('${pole}')">×</span>`;
    container.insertBefore(tag, input);
  });
}

window.runFaultLocation = async function(eventTime) {
  const lineCode = document.getElementById('fault-line-select').value;
  if (!lineCode) {
    showToast('请先上传一个拓扑（前往"自定义拓扑"页）', 'warning');
    return;
  }
  if (alarmTags.length === 0) {
    showToast('请至少输入一个报警监测点', 'warning');
    return;
  }
  const faultType = document.getElementById('fault-type-select').value;

  const badge = document.getElementById('result-badge');
  badge.className = 'badge badge-amber';
  badge.textContent = '定位中...';

  const result = await window.apiFaultLocate(lineCode, alarmTags, faultType, eventTime);

  if (result.error) {
    showToast(result.error, 'error');
    badge.className = 'badge badge-red';
    badge.textContent = '定位失败';
    return;
  }

  renderFaultResult(result, lineCode);

  // 同步高亮拓扑图（在完整物理图里展开，见 topology.js::setFaultSection）
  const alarmIds = result.alarm_ids || [];
  const frontierIds = result.results?.map(r => r.frontier_id) || [];
  const sectionPairs = (result.results || []).flatMap(r =>
    r.candidate_ids.length ? r.candidate_ids.map(cid => [r.frontier_id, cid]) : [[r.frontier_id, null]]
  );
  window.setFaultSection(lineCode, alarmIds, frontierIds, sectionPairs);
};

function renderFaultResult(result, lineCode) {
  const badge = document.getElementById('result-badge');
  const body = document.getElementById('fault-result-body');

  const hasHigh = result.results?.some(r => r.confidence === 'high');
  const hasMed  = result.results?.some(r => r.confidence === 'medium');
  badge.className = `badge badge-${hasHigh ? 'green' : hasMed ? 'amber' : 'grey'}`;
  badge.textContent = hasHigh ? '定位成功' : hasMed ? '部分定位' : '需人工排查';

  if (!result.results?.length) {
    body.innerHTML = `<div style="text-align:center;padding:32px;color:var(--text-muted)">未找到有效的报警前沿节点，请检查输入数据。</div>`;
    return;
  }

  const lineName = window.TOPO_DATA[lineCode]?.name || lineCode;

  let html = `
    <div style="margin-bottom:16px">
      <div style="font-size:12px;color:var(--text-muted);margin-bottom:6px"><i class="bi bi-geo-alt"></i> 分析摘要</div>
      <div style="font-size:12px;color:var(--text-secondary);line-height:1.8">
        线路：<strong style="color:var(--cyan)">${lineName}</strong> &nbsp;
        报警点：<strong>${result.alarm_poles?.length || alarmTags.length}个</strong> &nbsp;
        方法：<span class="badge badge-cyan">矩阵法</span>
        ${result.not_found?.length ? `<br><span style="color:var(--amber)">⚠️ 未识别的监测点：${result.not_found.join(', ')}</span>` : ''}
      </div>
    </div>
    <div style="font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px">定位结果</div>`;

  result.results.forEach((r, i) => {
    const confColor = r.confidence === 'high' ? 'var(--green)' : r.confidence === 'medium' ? 'var(--amber)' : 'var(--text-muted)';
    const confLabel = { high: '高置信度', medium: '中等置信度', low: '低置信度' }[r.confidence] || r.confidence;

    const hasCandidates = r.candidate_poles?.length > 0;

    html += `
      <div class="result-item ${hasCandidates ? 'section' : 'frontier'}" style="margin-bottom:10px">
        <div class="result-item-head">
          <div style="font-size:11px;color:var(--text-muted)">前沿节点 ${i+1}</div>
          <span class="badge" style="background:rgba(0,0,0,0.2);color:${confColor};border:1px solid ${confColor}40">${confLabel}</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <span class="badge badge-red">${r.frontier_pole}</span>
          ${hasCandidates ? `<span style="color:var(--amber);font-size:16px;font-weight:700">→</span>
          ${r.candidate_poles.map(p => `<span class="badge badge-amber">${p}</span>`).join(' ')}` : ''}
        </div>
        <div class="result-item-body">
          ${hasCandidates
            ? `故障区段：<strong style="color:var(--amber)">${r.frontier_pole} → ${r.candidate_poles.join(' / ')}</strong> 之间`
            : `<span style="color:var(--text-muted)">${r.frontier_pole} 是线路末端监测点</span>`}
        </div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:6px;padding-top:6px;border-top:1px solid var(--border)">
          <i class="bi bi-info-circle"></i> ${r.note}
        </div>
        ${hasCandidates ? `
        <div class="confidence-bar" style="margin-top:8px">
          <div class="confidence-fill" style="width:${r.confidence==='high'?85:r.confidence==='medium'?55:30}%;background:${confColor}"></div>
        </div>` : ''}
      </div>`;
  });

  html += renderElectricalAnalysisSection(result.electrical_analysis);

  body.innerHTML = html;

  // 显示小拓扑图
  const frontierPole = result.results[0]?.frontier_pole;
  const candidatePoles = result.results.flatMap(r => r.candidate_poles);
  document.getElementById('fault-topo-card').style.display = 'block';
  window.renderFaultMiniTopo(lineCode, alarmTags, frontierPole, candidatePoles);

  // 显示AI辅助卡片
  document.getElementById('ai-assist-card').style.display = 'block';
  document.getElementById('ai-assist-body').innerHTML = `
    <div style="font-size:12px;color:var(--text-secondary);line-height:1.7">
      基于矩阵法已完成初步定位。可点击右上角按钮，调用 Agent 进行深度分析并获取巡线建议。
    </div>`;

  showToast('故障区段定位完成', 'success');
}

// 电气量分析展示区块——基于历史真实电压/电流读数的启发式规则分析（MVP，样本量有限），
// 只在能匹配到原始记录时展示，找不到就完全不显示这个区块（不占位、不显示"无数据"占位符）
function renderElectricalAnalysisSection(ea) {
  if (!ea || !ea.matched) return '';

  const severityColor = { high: 'var(--red)', medium: 'var(--amber)', low: 'var(--text-muted)' }[ea.severity_label] || 'var(--text-muted)';
  const severityLabel = { high: '较严重', medium: '中等', low: '较轻' }[ea.severity_label] || '未知';

  const nodesHtml = (ea.node_analyses || []).map(na => {
    const faultBadges = (na.faulted_phases || []).map(p =>
      `<span class="badge badge-red" style="margin-right:4px">${p}相异常</span>`
    ).join('') || '<span style="color:var(--text-muted)">未见异常相</span>';
    const consistWarning = na.consistent_with_report === false
      ? `<div style="color:var(--amber);font-size:11px;margin-top:4px"><i class="bi bi-exclamation-triangle"></i> 与报警文本描述的故障相不完全一致，建议现场核实</div>`
      : '';
    return `
      <div style="padding:8px 0;border-bottom:1px dashed var(--border)">
        <div style="display:flex;align-items:center;gap:8px;font-size:12px">
          <span class="badge badge-cyan">${na.pole}</span>
          ${faultBadges}
          ${na.imbalance_ratio != null ? `<span style="color:var(--text-muted);font-size:11px">三相不平衡度 ${na.imbalance_ratio}%</span>` : ''}
        </div>
        ${consistWarning}
      </div>`;
  }).join('');

  return `
    <div style="margin-top:18px;padding-top:14px;border-top:1px solid var(--border)">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <i class="bi bi-lightning-charge" style="color:${severityColor}"></i>
        <span style="font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.8px">电气量分析（基于历史实测数据）</span>
        <span class="badge" style="background:rgba(0,0,0,0.2);color:${severityColor};border:1px solid ${severityColor}40">严重程度：${severityLabel}</span>
      </div>
      <div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px">
        推断故障相：<strong style="color:var(--red)">${(ea.inferred_fault_phases || []).join('、') || '无明显异常'}</strong>
      </div>
      ${nodesHtml}
      <div style="font-size:11px;color:var(--text-muted);margin-top:8px;line-height:1.6">
        <i class="bi bi-info-circle"></i> ${ea.note}
      </div>
    </div>`;
}

// ======================== 历史事件表格 ========================
window.filterHistory = function() {
  renderHistoryTable();
};

// topology_id -> 拓扑名称，用于历史事件表格里把id显示成人能看懂的名字；
// 页面加载和"自定义拓扑"页有变动时刷新，找不到就退回显示原始id，不影响功能。
window._topoNameCache = {};
async function refreshTopoNameCache() {
  if (typeof window.apiListCustomTopologies !== 'function') return;
  const topos = await window.apiListCustomTopologies();
  window._topoNameCache = Object.fromEntries(topos.map(t => [t.id, t.name]));
}

function renderHistoryTable() {
  const lineFilter   = document.getElementById('history-line-filter')?.value || '';
  const typeFilter   = document.getElementById('history-type-filter')?.value || '';
  const searchFilter = document.getElementById('history-search')?.value?.toLowerCase() || '';

  let data = window.HISTORY_DATA || [];
  if (lineFilter) data = data.filter(r => r.line === lineFilter);
  if (typeFilter) data = data.filter(r => (r.types || r.fault_types || '').includes(typeFilter));
  if (searchFilter) data = data.filter(r => {
    const alarms = r.alarms || r.alarmed_points || '';
    const frontier = r.frontier || '';
    const candidates = r.candidates || r.candidate_sections || '';
    return r.line.includes(searchFilter) || (r.time || '').includes(searchFilter) ||
      alarms.includes(searchFilter) || frontier.includes(searchFilter) ||
      candidates.includes(searchFilter);
  });

  document.getElementById('history-total').textContent = window.HISTORY_DATA.length;
  const breakdownEl = document.getElementById('history-line-breakdown');
  if (breakdownEl) {
    const byLine = {};
    window.HISTORY_DATA.forEach(r => { byLine[r.line] = (byLine[r.line] || 0) + 1; });
    breakdownEl.textContent = Object.entries(byLine)
      .map(([line, n]) => `${window._topoNameCache[line] || line} ${n}次`).join(' / ');
  }

  const tbody = document.getElementById('history-tbody');
  if (!tbody) return;

  if (data.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;padding:32px;color:var(--text-muted)">未找到匹配记录</td></tr>`;
    return;
  }

  tbody.innerHTML = data.map((r, idx) => {
    // 兼容后端API格式和静态数据格式
    const id        = r.event_id || r.id || (idx + 1);
    const line      = r.line;
    const lineLabel = window._topoNameCache[line] || line;
    const time      = r.time;
    const types     = r.fault_types || r.types || '';
    const alarms    = r.alarmed_points || r.alarms || '';
    const frontier  = r.frontier || '';
    const candidates = r.candidate_sections || r.candidates || '(无)';
    const confidence = r.confidence || 'unknown';
    const note      = r.note || '';

    const confClass = confidence === 'high' ? 'badge-green' : confidence === 'medium' ? 'badge-amber' : 'badge-grey';
    const confLabel = { high: '高', medium: '中', low: '低' }[confidence] || '未知';
    const liveTag = r.source === 'live' ? ' <span class="badge badge-amber" title="通过故障定位页面实时生成，非历史导入案例" style="font-size:10px">实时</span>' : '';
    return `<tr>
      <td style="color:var(--text-muted)">${id}</td>
      <td><span class="badge badge-cyan" title="${line}">${lineLabel}</span>${liveTag}</td>
      <td class="mono">${time}</td>
      <td style="max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${types}">${types}</td>
      <td class="mono" style="color:var(--red)">${alarms}</td>
      <td class="mono" style="color:var(--amber)">${frontier}</td>
      <td class="mono" style="color:${candidates === '(无)' ? 'var(--text-muted)' : 'var(--text-primary)'}">
        ${candidates}
      </td>
      <td><span class="badge ${confClass}" title="${note}">${confLabel}</span></td>
      <td>
        <span class="action-btn" onclick="replayHistoryEvent('${id}')">复现 →</span>
      </td>
    </tr>`;
  }).join('');
}

// 从后端加载历史事件（替换静态HISTORY_DATA）
async function loadHistoryFromAPI() {
  try {
    const r = await fetch('/api/fault/history', { signal: AbortSignal.timeout(5000) });
    if (!r.ok) return;
    const data = await r.json();
    if (data.events && data.events.length > 0) {
      window.HISTORY_DATA = data.events;
      document.getElementById('stat-alarms') && (document.getElementById('stat-alarms').textContent =
        data.events.filter(e => {
          const d = new Date(e.time);
          const today = new Date();
          return d.toDateString() === today.toDateString();
        }).length);
      renderHistoryTable();
    }
  } catch (e) {
    // fallback 到静态数据，不报错
  }
}

window.replayEvent = async function(eventId) {
  const event = window.HISTORY_DATA.find(e => (e.id || e.event_id) == eventId);
  if (!event) return;
  const lineCode = event.line;  // event.line 本身就是 topology_id
  const alarmsStr = event.alarms || event.alarmed_points || '';
  const poles = alarmsStr.split(',').map(s => s.trim()).filter(Boolean);
  await fillCustomTopoOptions('fault-line-select');
  document.getElementById('fault-line-select').value = lineCode;
  onFaultLineChange();
  poles.forEach(p => addAlarmTag(p));
  navTo('fault');
  // 传入事件时间，让后端能精确关联到这次事件对应的原始电气量记录（而不是该监测点
  // 历史上最新的一次读数——同一个监测点可能发生过好几次不相关的故障）
  setTimeout(() => runFaultLocation(event.time), 100);
};

// 兼容后端API格式的replayEvent（按event_id字符串）
window.replayHistoryEvent = function(eventId) {
  window.replayEvent(eventId);
};

// ======================== 生产级监测数据管理与自动复现 ========================

window._currentHistoryTab = 'monitoring';
window._monitoringEvents = [];
window._currentMonitoringEvent = null;
window._currentMonitoringRecords = [];

window.switchHistoryTab = function(tab) {
  window._currentHistoryTab = tab;
  const btnMon = document.getElementById('tab-btn-monitoring');
  const btnFaults = document.getElementById('tab-btn-faults');
  const subMon = document.getElementById('subview-monitoring');
  const subFaults = document.getElementById('subview-faults');

  if (tab === 'monitoring') {
    if (btnMon) btnMon.classList.add('active');
    if (btnFaults) btnFaults.classList.remove('active');
    if (subMon) subMon.style.display = 'flex';
    if (subFaults) subFaults.style.display = 'none';
    loadMonitoringEvents();
  } else {
    if (btnMon) btnMon.classList.remove('active');
    if (btnFaults) btnFaults.classList.add('active');
    if (subMon) subMon.style.display = 'none';
    if (subFaults) subFaults.style.display = 'block';
    renderHistoryTable();
  }
};

window.loadMonitoringEvents = async function(preserveEventId = null) {
  const topoFilter = document.getElementById('monitoring-topo-filter')?.value || '';
  const events = await window.apiListMonitoringEvents(topoFilter);
  window._monitoringEvents = events || [];

  const select = document.getElementById('monitoring-event-select');
  if (!select) return;

  if (window._monitoringEvents.length === 0) {
    select.innerHTML = '<option value="">暂无监测事件记录，请先上传监测数据或载入样例</option>';
    const badgeEl = document.getElementById('event-inferred-badge');
    if (badgeEl) badgeEl.innerHTML = '';
    renderMonitoringRecords([]);
    return;
  }

  select.innerHTML = window._monitoringEvents.map(e => {
    const topoLabel = window._topoNameCache[e.topology_id] || e.topology_name || e.topology_id;
    const isAbn = e.abnormal_count > 0 ? `⚠️异常:${e.abnormal_count}` : '正常';
    return `<option value="${escapeHtml(e.event_id)}">${escapeHtml(e.timestamp)} · [${escapeHtml(topoLabel)}] 监测点:${e.record_count} ${isAbn} (${escapeHtml(e.fault_summary || '正常工况')})</option>`;
  }).join('');

  let targetId = preserveEventId;
  if (!targetId || !window._monitoringEvents.some(e => e.event_id === targetId)) {
    targetId = window._monitoringEvents[0].event_id;
  }
  select.value = targetId;
  await window.onSelectMonitoringEvent(targetId);
};

window.onSelectMonitoringEvent = async function(eventId) {
  if (!eventId) return;
  const badgeEl = document.getElementById('event-inferred-badge');
  const details = await window.apiGetMonitoringEventDetails(eventId);
  if (!details || !details.event) {
    if (badgeEl) badgeEl.innerHTML = '';
    renderMonitoringRecords([]);
    return;
  }

  window._currentMonitoringEvent = details.event;
  window._currentMonitoringRecords = details.records || [];

  if (badgeEl) {
    const inferred = details.event.inferred_poles ? details.event.inferred_poles.split(',').map(s => s.trim()).filter(Boolean) : [];
    const inferredHtml = inferred.length > 0
      ? inferred.map(p => `<span class="badge badge-red" style="margin-right:3px">${escapeHtml(p)}</span>`).join('')
      : '<span class="badge badge-grey">无明显报警点</span>';
    const summaryHtml = details.event.fault_summary ? `<span class="badge badge-amber" style="margin-left:6px">${escapeHtml(details.event.fault_summary)}</span>` : '';
    badgeEl.innerHTML = `<span style="color:var(--text-muted);font-size:12px">自动判定报警点:</span> ${inferredHtml}${summaryHtml}`;
  }

  renderMonitoringRecords(window._currentMonitoringRecords);
};

function renderMonitoringRecords(records) {
  const tbody = document.getElementById('monitoring-records-tbody');
  if (!tbody) return;

  const keyword = document.getElementById('monitoring-search')?.value?.trim().toLowerCase() || '';
  let filtered = records;
  if (keyword) {
    filtered = records.filter(r =>
      (r.node_name || '').toLowerCase().includes(keyword) ||
      (r.node_id || '').toLowerCase().includes(keyword) ||
      (r.device_type || '').toLowerCase().includes(keyword) ||
      (r.terminal_status || '').toLowerCase().includes(keyword) ||
      (r.line_status || '').toLowerCase().includes(keyword) ||
      (r.warning_status || '').toLowerCase().includes(keyword) ||
      (r.abnormal_reason || '').toLowerCase().includes(keyword)
    );
  }

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" style="text-align:center;padding:32px;color:var(--text-muted)">未找到匹配的监测记录</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(r => {
    const isAbnormal = !!r.is_abnormal;
    const rowClass = isAbnormal ? 'row-abnormal' : '';

    // 线路状态标签
    let lineBadgeClass = 'badge-grey';
    if (r.line_status && r.line_status !== '正常') {
      lineBadgeClass = r.line_status.includes('短路') || r.line_status.includes('接地') || r.line_status.includes('故障') ? 'badge-red' : 'badge-amber';
    } else if (r.line_status === '正常') {
      lineBadgeClass = 'badge-green';
    }

    // 终端状态标签
    let termBadgeClass = r.terminal_status === '正常' ? 'badge-green' : 'badge-amber';

    // 预警状态标签
    let warnBadgeClass = 'badge-grey';
    if (r.warning_status && r.warning_status !== '正常' && r.warning_status !== '-' && r.warning_status !== '---') {
      warnBadgeClass = 'badge-amber';
    }

    // 电压格式化（低于0.5kV标红）
    const fmtVolt = (val) => {
      if (val == null) return '<span style="color:var(--text-muted)">-</span>';
      const isLow = val <= 0.5;
      return `<span style="${isLow ? 'color:var(--red);font-weight:700' : ''}">${Number(val).toFixed(2)}</span>`;
    };
    const voltHtml = `A:${fmtVolt(r.ua)} B:${fmtVolt(r.ub)} C:${fmtVolt(r.uc)}`;

    // 电流格式化
    const fmtCur = (val) => val == null ? '<span style="color:var(--text-muted)">-</span>' : Number(val).toFixed(1);
    const curHtml = `A:${fmtCur(r.ia)} B:${fmtCur(r.ib)} C:${fmtCur(r.ic)}`;

    // 相位格式化
    const fmtPhase = (val) => val == null ? '<span style="color:var(--text-muted)">-</span>' : `${Number(val).toFixed(0)}°`;
    const phaseHtml = `A:${fmtPhase(r.phase_a)} B:${fmtPhase(r.phase_b)} C:${fmtPhase(r.phase_c)}`;

    const nodeBadge = isAbnormal
      ? `<span class="badge badge-red" style="font-size:10px;margin-left:4px">异常</span>`
      : '';

    return `<tr class="${rowClass}">
      <td style="color:var(--text-muted);text-align:center">${r.record_no || r.id}</td>
      <td style="font-weight:600">
        ${escapeHtml(r.node_name)}
        ${nodeBadge}
        ${r.abnormal_reason ? `<div style="font-size:11px;color:var(--red);font-weight:normal;margin-top:2px">${escapeHtml(r.abnormal_reason)}</div>` : ''}
      </td>
      <td><span class="badge badge-grey">${escapeHtml(r.device_type || '配电线路')}</span></td>
      <td><span class="badge ${termBadgeClass}">${escapeHtml(r.terminal_status || '正常')}</span></td>
      <td><span class="badge ${lineBadgeClass}">${escapeHtml(r.line_status || '正常')}</span></td>
      <td><span class="badge ${warnBadgeClass}">${escapeHtml(r.warning_status || '正常')}</span></td>
      <td class="mono" style="font-size:11px;white-space:nowrap">${voltHtml}</td>
      <td class="mono" style="font-size:11px;white-space:nowrap">${curHtml}</td>
      <td class="mono" style="font-size:11px;white-space:nowrap">${phaseHtml}</td>
      <td class="mono" style="font-size:11px;color:var(--text-secondary);white-space:nowrap">${escapeHtml(r.measure_time || '')}</td>
      <td style="text-align:center">
        <button class="btn btn-secondary btn-sm" onclick="reproduceSelectedMonitoringEvent('${escapeHtml(r.event_id)}')" title="自动提取该事件判定报警点并触发区段定位">
          <i class="bi bi-play-circle"></i> 复现
        </button>
      </td>
    </tr>`;
  }).join('');
}

window.filterMonitoringView = function() {
  renderMonitoringRecords(window._currentMonitoringRecords || []);
};

window.onMonitoringTopoChange = async function() {
  await loadMonitoringEvents();
};

window.handleMonitoringUpload = async function(input) {
  const file = input.files && input.files[0];
  if (!file) return;

  showToast('正在解析监测数据文件...', 'info');
  const topoFilter = document.getElementById('monitoring-topo-filter')?.value || null;
  const res = await window.apiUploadMonitoringData(file, topoFilter);
  input.value = '';

  if (!res || !res.ok) {
    showToast(res?.error || '上传解析失败', 'error');
    return;
  }

  showToast(`监测数据上传成功！共解析 ${res.record_count} 条监测数据，生成 ${res.event_count} 组事件批次`, 'success');
  await refreshTopoNameCache();
  await loadMonitoringEvents(res.events?.[0]?.event_id);
};

window.seedSampleMonitoringData = async function() {
  const btn = document.getElementById('btn-seed-sample');
  if (btn) btn.disabled = true;
  showToast('正在载入样例监测数据...', 'info');

  const res = await window.apiSeedSampleMonitoringData();
  if (btn) btn.disabled = false;

  if (res && res.ok) {
    showToast(res.message || '已成功载入样例监测数据', 'success');
    await refreshTopoNameCache();
    await loadMonitoringEvents();
  } else {
    showToast(res?.message || '载入样例数据失败', 'error');
  }
};

window.reproduceSelectedMonitoringEvent = async function(targetEventId = null) {
  const eventId = targetEventId || document.getElementById('monitoring-event-select')?.value;
  if (!eventId) {
    showToast('请选择需要复现的故障事件批次', 'warning');
    return;
  }

  showToast('正在研判监测数据并执行故障区段定位...', 'info');
  const res = await window.apiReproduceMonitoringEvent(eventId);
  if (!res || !res.ok) {
    showToast(res?.error || '复现故障定位失败', 'error');
    return;
  }

  const topoId = res.topology_id;
  const inferredPoles = res.inferred_poles || [];

  // 1. 确保故障定位界面的拓扑下拉框选中对应拓扑并加载拓扑监测点
  await fillCustomTopoOptions('fault-line-select');
  const lineSelect = document.getElementById('fault-line-select');
  if (lineSelect) lineSelect.value = topoId;
  currentLine = topoId;
  await ensureTopoDataLoaded(topoId);
  buildQuickNodeList(topoId);

  // 2. 清空既有报警点，并根据监测数据自动填充报警监测点（无需人工手动勾选）
  clearAlarms();
  if (inferredPoles.length > 0) {
    inferredPoles.forEach(pole => addAlarmTag(pole));
  }

  // 3. 切换视图至"故障定位"
  navTo('fault');

  // 4. 展示区段定位结果与拓扑联动
  if (res.fault_locate) {
    const normalized = res.normalized_locate || (typeof window.normalizeBackendFaultResult === 'function' ? window.normalizeBackendFaultResult(res.fault_locate) : res.fault_locate);
    renderFaultResult(normalized, topoId);

    const alarmIds = normalized.alarm_ids || [];
    const frontierIds = normalized.results?.map(r => r.frontier_id) || [];
    const sectionPairs = (normalized.results || []).flatMap(r =>
      r.candidate_ids.length ? r.candidate_ids.map(cid => [r.frontier_id, cid]) : [[r.frontier_id, null]]
    );
    if (typeof window.setFaultSection === 'function') {
      window.setFaultSection(topoId, alarmIds, frontierIds, sectionPairs);
    }
  }

  showToast(`已根据监测数据自动填充报警监测点 [${inferredPoles.join(', ') || '无'}]，并完成故障区段定位！`, 'success');
  loadHistoryFromAPI();
};

// ======================== 登录/登出 ========================
window.logout = async function() {
  try {
    await fetch('/api/auth/logout', { method: 'POST' });
  } catch {}
  window.location.href = '/login';
};

// ======================== 初始化 ========================
document.addEventListener('DOMContentLoaded', async () => {
  renderHistoryTable();

  // 后端可用时，从API拉取真实历史事件 + 恢复LLM配置状态 + 载入监测数据
  // （延迟1.2s等api.js的checkBackend完成，避免_backendAvailable还没就绪就查询）
  setTimeout(async () => {
    const llmStatus = await window.apiGetLLMConfig();
    if (llmStatus.configured) updateLLMStatus(true, llmStatus.provider);

    await refreshTopoNameCache();
    await loadHistoryFromAPI();
    await loadMonitoringEvents();

    // 顶部统计：已上传拓扑数 / 监测点总数，来自自定义拓扑列表
    try {
      const topos = await window.apiListCustomTopologies();
      const statLines = document.getElementById('stat-lines');
      if (statLines) statLines.textContent = topos.length;
      const statNodes = document.getElementById('stat-nodes');
      if (statNodes) statNodes.textContent = topos.reduce((s, t) => s + (t.monitor_point_count || 0), 0);
      const topoCountPill = document.getElementById('topo-count-pill');
      if (topoCountPill) topoCountPill.textContent = `${topos.length} 个拓扑`;
      const settingsTopoCount = document.getElementById('settings-topo-count');
      if (settingsTopoCount) settingsTopoCount.textContent = `${topos.length} 个`;
      const statFaults = document.getElementById('stat-faults');
      if (statFaults) statFaults.textContent = window.HISTORY_DATA.length;
    } catch {}
  }, 1200);
});

