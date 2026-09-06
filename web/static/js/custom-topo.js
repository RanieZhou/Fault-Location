/**
 * custom-topo.js — "自定义拓扑"页面：上传节点/边表 → 标记监测点 → 设置线路参数
 * → （可选）上传历史电气量数据 + 自动推理。管理面板用的树形预览是独立于
 * topology.js（拓扑监控主页专用）的一套简化渲染逻辑，避免互相影响。
 */
(function() {
  let currentTopoId = null;
  let currentDetail = null;  // 最近一次 apiGetCustomTopologyDetail 的结果

  // ======================== 导航进入时刷新列表 ========================
  window.ctOnNavTo = function() {
    ctRefreshList();
  };

  async function ctRefreshList() {
    const el = document.getElementById('ct-list');
    const topos = await window.apiListCustomTopologies();
    if (!topos.length) {
      el.innerHTML = `<div style="text-align:center;padding:20px 0;color:var(--text-muted);font-size:12px">暂无自定义拓扑</div>`;
      return;
    }
    el.innerHTML = topos.map(t => `
      <div class="ct-topo-item ${t.id === currentTopoId ? 'active' : ''}"
           style="padding:10px;border-radius:8px;margin-bottom:6px;cursor:pointer;border:1px solid ${t.id === currentTopoId ? 'var(--cyan)' : 'transparent'};background:var(--bg-card)"
           onclick="ctSelectTopology('${t.id}')">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <div style="font-size:13px;font-weight:600;color:var(--text-primary)">${escapeHtml(t.name)}</div>
          <i class="bi bi-trash3" style="color:var(--text-muted);cursor:pointer" onclick="event.stopPropagation();ctDeleteTopology('${t.id}')" title="删除"></i>
        </div>
        <div style="font-size:11px;color:var(--text-muted);margin-top:4px">
          ${t.node_count}个节点 · ${t.edge_count}条边 · ${t.monitor_point_count}个监测点
        </div>
      </div>
    `).join('');
  }

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  // ======================== 边表模板预览 ========================
  const TEMPLATE_ROWS = [
    ['变电站', '1号杆', '0.6'],
    ['1号杆', '2号杆', '0.9'],
    ['2号杆', '3号杆', '0.5'],
    ['2号杆', '7号杆', '1.1'],
    ['3号杆', '4号杆', '0.4'],
  ];

  window.ctToggleTemplatePreview = function() {
    const el = document.getElementById('ct-template-preview');
    if (!el) return;
    const showing = el.style.display !== 'none';
    if (showing) { el.style.display = 'none'; return; }
    el.innerHTML = `
      <div style="border:1px solid var(--border-color,rgba(255,255,255,0.08));border-radius:8px;padding:10px;background:var(--bg-card)">
        <table class="data-table" style="margin-bottom:8px">
          <thead><tr><th>from_id</th><th>to_id</th><th>length_km</th></tr></thead>
          <tbody>
            ${TEMPLATE_ROWS.map(([f, t, l]) => `
              <tr><td class="mono">${escapeHtml(f)}</td><td class="mono">${escapeHtml(t)}</td><td>${escapeHtml(l)}</td></tr>
            `).join('')}
          </tbody>
        </table>
        <div style="font-size:11px;color:var(--text-muted);line-height:1.6">
          上传后会自动识别：<span style="color:var(--cyan)">变电站</span>没有入边，作为电源根节点；
          <span style="color:var(--cyan)">2号杆</span>同时是<span style="color:var(--cyan)">3号杆</span>和<span style="color:var(--cyan)">7号杆</span>的父节点，会形成一条分支——
          不用单独传节点表，5个节点都从这张边表里自动反推出来。
        </div>
      </div>`;
    el.style.display = 'block';
  };

  // ======================== 上传 ========================
  window.ctUpload = async function() {
    const name = document.getElementById('ct-upload-name').value.trim();
    const nodesFile = document.getElementById('ct-upload-nodes').files[0];
    const edgesFile = document.getElementById('ct-upload-edges').files[0];
    const resultEl = document.getElementById('ct-upload-result');

    if (!name) { showToast('请填写拓扑名称', 'warning'); return; }
    if (!edgesFile) { showToast('请至少选择边表CSV（节点表可选）', 'warning'); return; }

    resultEl.innerHTML = `<div style="font-size:12px;color:var(--text-muted);margin-top:8px">上传中...</div>`;
    const result = await window.apiUploadCustomTopology(name, nodesFile, edgesFile);

    if (!result.ok) {
      resultEl.innerHTML = `<div style="font-size:12px;color:var(--red);margin-top:8px;white-space:pre-wrap">${escapeHtml(result.error || '上传失败')}</div>`;
      return;
    }
    resultEl.innerHTML = `<div style="font-size:12px;color:var(--green);margin-top:8px">上传成功：${result.node_count}个节点，${result.edge_count}条边</div>`;
    document.getElementById('ct-upload-name').value = '';
    document.getElementById('ct-upload-nodes').value = '';
    document.getElementById('ct-upload-edges').value = '';
    await ctRefreshList();
    window.ctSelectTopology(result.id);
  };

  // ======================== 删除 ========================
  window.ctDeleteTopology = async function(id) {
    if (!confirm('确定删除这个自定义拓扑吗？此操作不可恢复。')) return;
    await window.apiDeleteCustomTopology(id);
    if (currentTopoId === id) {
      currentTopoId = null;
      document.getElementById('ct-manage-panel').innerHTML = `
        <div style="text-align:center;padding:64px 0;color:var(--text-muted)">
          <i class="bi bi-diagram-2" style="font-size:48px;display:block;margin-bottom:12px;opacity:0.4"></i>
          <div>上传新拓扑，或从左侧列表选择已有拓扑<br>开始标记监测点、设置线路参数</div>
        </div>`;
    }
    showToast('已删除', 'info');
    ctRefreshList();
  };

  // ======================== 选中一个拓扑 → 渲染管理面板 ========================
  window.ctSelectTopology = async function(id) {
    currentTopoId = id;
    ctRefreshList();
    const detail = await window.apiGetCustomTopologyDetail(id);
    if (!detail) { showToast('加载失败', 'error'); return; }
    currentDetail = detail;
    renderManagePanel(detail);
  };

  function renderManagePanel(detail) {
    const monitorCount = detail.nodes.filter(n => n.is_monitor_point).length;
    const panel = document.getElementById('ct-manage-panel');
    panel.innerHTML = `
      <div class="card" style="margin-bottom:14px">
        <div class="card-header">
          <div class="card-title"><i class="bi bi-diagram-2 icon"></i>${escapeHtml(detail.name)}
            <span style="font-size:11px;color:var(--text-muted);font-weight:400;margin-left:8px" class="mono">${detail.id}</span>
          </div>
          <button class="btn btn-primary btn-sm" onclick="ctUseForFaultLocate('${detail.id}')">
            <i class="bi bi-search"></i> 用于故障定位
          </button>
        </div>
        <div class="card-body">
          ${detail.tree_errors && detail.tree_errors.length ? `
            <div style="font-size:12px;color:var(--red);background:var(--red-dim);padding:8px 10px;border-radius:6px;margin-bottom:10px;white-space:pre-wrap">
              树结构校验未通过，故障定位暂时无法使用这个拓扑：<br>${detail.tree_errors.map(escapeHtml).join('<br>')}
            </div>` : ''}
          <div style="font-size:12px;color:var(--text-secondary);margin-bottom:10px">
            共 ${detail.nodes.length} 个节点，${detail.edges.length} 条边，其中 <span style="color:var(--cyan)">${monitorCount}</span> 个已标记为监测点
            ${monitorCount === 0 ? '<span style="color:var(--amber)">（还没有标记监测点，无法用于故障定位）</span>' : ''}
          </div>
          <svg id="ct-preview-svg" style="width:100%;height:220px;background:var(--bg-base);border-radius:8px"></svg>
          <div style="display:flex;gap:14px;margin-top:6px;font-size:11px;color:var(--text-muted)">
            <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#00d4ff;margin-right:4px"></span>监测点</span>
            <span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#64748b;margin-right:4px"></span>结构杆塔（未装监测设备）</span>
          </div>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
        <div class="card">
          <div class="card-header">
            <div class="card-title"><i class="bi bi-check2-square icon"></i>标记监测点</div>
          </div>
          <div class="card-body">
            <div style="display:flex;gap:6px;margin-bottom:8px">
              <button class="btn btn-ghost btn-sm" onclick="ctToggleAllNodes(true)">全选</button>
              <button class="btn btn-ghost btn-sm" onclick="ctToggleAllNodes(false)">全不选</button>
              <div style="flex:1"></div>
              <button class="btn btn-primary btn-sm" onclick="ctSaveMonitorPoints()">保存</button>
            </div>
            <div style="max-height:280px;overflow-y:auto">
              <table class="data-table">
                <thead><tr><th style="width:32px"></th><th>node_id</th><th>label</th><th>父节点</th></tr></thead>
                <tbody id="ct-node-tbody">
                  ${detail.nodes.map(n => `
                    <tr>
                      <td><input type="checkbox" class="ct-node-cb" data-id="${escapeHtml(n.node_id)}" ${n.is_monitor_point ? 'checked' : ''}></td>
                      <td class="mono">${escapeHtml(n.node_id)}</td>
                      <td>${escapeHtml(n.label)}</td>
                      <td class="mono">${n.parent_id ? escapeHtml(n.parent_id) : '(根)'}</td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <div class="card-title"><i class="bi bi-rulers icon"></i>线路参数</div>
          </div>
          <div class="card-body">
            <div style="display:flex;gap:6px;margin-bottom:8px">
              <button class="btn btn-ghost btn-sm" onclick="ctToggleAllEdges(true)">全选</button>
              <button class="btn btn-ghost btn-sm" onclick="ctToggleAllEdges(false)">全不选</button>
            </div>
            <div style="max-height:180px;overflow-y:auto;margin-bottom:8px">
              <table class="data-table">
                <thead><tr><th style="width:32px"></th><th>边</th><th>长度(km)</th><th>R(Ω)</th><th>X(Ω)</th></tr></thead>
                <tbody id="ct-edge-tbody">
                  ${detail.edges.map(e => `
                    <tr>
                      <td><input type="checkbox" class="ct-edge-cb" data-from="${escapeHtml(e.from_id)}" data-to="${escapeHtml(e.to_id)}"></td>
                      <td class="mono" style="font-size:11px">${escapeHtml(e.from_id)}→${escapeHtml(e.to_id)}</td>
                      <td>${e.length_km.toFixed(3)}</td>
                      <td>${e.resistance_ohm.toFixed(4)}</td>
                      <td>${e.reactance_ohm.toFixed(4)}</td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
            <div class="form-hint" style="margin-bottom:6px">
              对勾选的边批量设置——电阻/电抗填"每公里"的值，系统会按每条边自己的长度换算成总值，
              所以同一种导线规格套用到长度不同的线段上也不会错。留空 = 不改该项。
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:8px">
              <div class="form-group" style="margin-bottom:0">
                <label class="form-label">长度(km)</label>
                <input class="input" id="ct-batch-length" type="number" step="0.001" placeholder="不改">
              </div>
              <div class="form-group" style="margin-bottom:0">
                <label class="form-label">R(Ω/km)</label>
                <input class="input" id="ct-batch-r" type="number" step="0.001" placeholder="如 0.15">
              </div>
              <div class="form-group" style="margin-bottom:0">
                <label class="form-label">X(Ω/km)</label>
                <input class="input" id="ct-batch-x" type="number" step="0.001" placeholder="如 0.35">
              </div>
            </div>
            <button class="btn btn-primary btn-sm" style="width:100%" onclick="ctApplyEdgeBatch()">应用到勾选的边</button>
          </div>
        </div>
      </div>

      <div class="card" style="margin-top:14px">
        <div class="card-header">
          <div class="card-title"><i class="bi bi-graph-up icon"></i>历史电气量数据 → 自动推理</div>
        </div>
        <div class="card-body">
          <div class="form-hint" style="margin-bottom:8px">
            上传历史电压/电流数据后，不用人工先指定报警点——系统会自动从原始读数里判断哪些监测点异常，
            再用矩阵法给出故障区段。基线数据用于建立"正常"基准，事件数据是真实故障发生时刻的快照。
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:8px">
            <div class="form-group" style="margin-bottom:0">
              <label class="form-label">基线数据 CSV（可选）</label>
              <input class="input" type="file" id="ct-baseline-file" accept=".csv">
              <div class="form-hint">列：node_id,phase,voltage_kv[,current_a]</div>
            </div>
            <div class="form-group" style="margin-bottom:0">
              <label class="form-label">事件数据 CSV（可选）</label>
              <input class="input" type="file" id="ct-event-file" accept=".csv">
              <div class="form-hint">列：event_id,timestamp,node_id,phase,voltage_kv[,current_a]</div>
            </div>
          </div>
          <button class="btn btn-primary btn-sm" onclick="ctUploadHistoricalData()"><i class="bi bi-cloud-upload"></i> 上传</button>
          <div id="ct-hist-upload-result"></div>

          <div style="margin-top:14px">
            <div style="font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.8px;margin-bottom:6px">已上传的历史事件</div>
            <div id="ct-events-list" style="display:flex;flex-direction:column;gap:6px">
              <div style="color:var(--text-muted);font-size:12px">加载中...</div>
            </div>
          </div>

          <div id="ct-infer-result"></div>
        </div>
      </div>
    `;

    renderPreviewSvg(detail);
    loadTopologyEvents(detail.id);
  }

  // ======================== 历史电气量数据 + 自动推理 ========================
  async function loadTopologyEvents(topoId) {
    const el = document.getElementById('ct-events-list');
    if (!el) return;
    const events = await window.apiListTopologyEvents(topoId);
    if (!events.length) {
      el.innerHTML = `<div style="color:var(--text-muted);font-size:12px">还没有上传事件数据</div>`;
      return;
    }
    el.innerHTML = events.map(e => `
      <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 10px;background:var(--bg-card);border-radius:6px;font-size:12px">
        <div>
          <span class="mono" style="color:var(--cyan)">${escapeHtml(e.event_id)}</span>
          <span style="color:var(--text-muted);margin-left:8px">${escapeHtml(e.timestamp || '')}</span>
          <span style="color:var(--text-muted);margin-left:8px">${e.node_ids.length}个监测点有读数</span>
        </div>
        <button class="btn btn-primary btn-sm" onclick="ctRunInference('${topoId}','${escapeHtml(e.event_id)}')">运行推理</button>
      </div>
    `).join('');
  }

  window.ctUploadHistoricalData = async function() {
    const baselineFile = document.getElementById('ct-baseline-file').files[0];
    const eventFile = document.getElementById('ct-event-file').files[0];
    const resultEl = document.getElementById('ct-hist-upload-result');
    if (!baselineFile && !eventFile) { showToast('请至少选择一个文件', 'warning'); return; }

    resultEl.innerHTML = `<div style="font-size:12px;color:var(--text-muted);margin-top:6px">上传中...</div>`;
    const result = await window.apiUploadHistoricalData(currentTopoId, baselineFile, eventFile);
    if (!result.ok) {
      resultEl.innerHTML = `<div style="font-size:12px;color:var(--red);margin-top:6px">${escapeHtml(result.error || '上传失败')}</div>`;
      return;
    }
    resultEl.innerHTML = `<div style="font-size:12px;color:var(--green);margin-top:6px">
      已写入 ${result.baseline_rows} 条基线读数，${result.event_count} 个事件（${result.event_rows} 条读数）
      ${(result.warnings || []).length ? '<br>' + result.warnings.map(escapeHtml).join('<br>') : ''}
    </div>`;
    document.getElementById('ct-baseline-file').value = '';
    document.getElementById('ct-event-file').value = '';
    loadTopologyEvents(currentTopoId);
  };

  window.ctRunInference = async function(topoId, eventId) {
    const resultEl = document.getElementById('ct-infer-result');
    resultEl.innerHTML = `<div style="font-size:12px;color:var(--text-muted);margin-top:10px">推理中...</div>`;
    const result = await window.apiInferFaultFromEvent(topoId, eventId);

    if (!result.ok) {
      resultEl.innerHTML = `<div style="font-size:12px;color:var(--red);margin-top:10px">${escapeHtml(result.note || '推理失败')}</div>`;
      return;
    }
    const fl = result.fault_locate;
    if (!fl) {
      resultEl.innerHTML = `<div style="font-size:12px;color:var(--amber);margin-top:10px">${escapeHtml(result.note)}</div>`;
      return;
    }

    const confColor = fl.confidence === 'high' ? 'var(--green)' : fl.confidence === 'medium' ? 'var(--amber)' : 'var(--text-muted)';
    const sectionsHtml = fl.candidate_sections.map(s => `
      <span class="badge badge-red">${escapeHtml(s.from_pole)}</span>
      ${s.to_pole !== '(末端)'
        ? `<span style="color:var(--amber);margin:0 4px">→</span><span class="badge badge-amber">${escapeHtml(s.to_pole)}</span>`
        : `<span style="color:var(--text-muted);margin-left:6px">(末端)</span>`}
    `).join('<br>');

    window._lastInferResult = { topoId, fl };

    resultEl.innerHTML = `
      <div class="card" style="margin-top:10px;background:var(--bg-card)">
        <div class="card-header">
          <div class="card-title"><i class="bi bi-cpu icon"></i>自动推理结果 — ${escapeHtml(eventId)}</div>
          <span class="badge" style="background:rgba(0,0,0,0.2);color:${confColor};border:1px solid ${confColor}40">${escapeHtml(fl.confidence)}</span>
        </div>
        <div class="card-body" style="font-size:12px">
          <div style="margin-bottom:8px;color:var(--text-secondary)">
            自动识别出的异常点：<strong style="color:var(--red)">${result.inferred_alarm_points.map(escapeHtml).join('、')}</strong>
          </div>
          <div style="margin-bottom:8px">${sectionsHtml}</div>
          <div style="color:var(--text-muted);margin-bottom:10px">${escapeHtml(fl.note)}</div>
          <button class="btn btn-secondary btn-sm" onclick="ctViewInferOnTopology()">
            <i class="bi bi-diagram-2"></i> 在拓扑图中查看
          </button>
        </div>
      </div>`;
  };

  window.ctViewInferOnTopology = async function() {
    const r = window._lastInferResult;
    if (!r) return;
    // 拓扑监控主页渲染的是完整物理图（TOPO_DATA），不是折叠简化树，预加载要用完整视图的接口
    if (!window.TOPO_DATA[r.topoId] && typeof window.apiGetCustomTopologyDetail === 'function') {
      const detail = await window.apiGetCustomTopologyDetail(r.topoId);
      if (detail) window.TOPO_DATA[r.topoId] = window.normalizeCustomTopoFullAsTopoData(detail);
    }
    const frontierIds = [...new Set(r.fl.candidate_sections.map(s => s.from_id))];
    const sectionPairs = r.fl.candidate_sections.map(s => [s.from_id, s.to_id || null]);
    navTo('topology');
    window.setFaultSection(r.topoId, r.fl.alarmed_node_ids || [], frontierIds, sectionPairs);
    showToast('已在拓扑图中高亮显示', 'success');
  };

  // ======================== 监测点勾选操作 ========================
  window.ctToggleAllNodes = function(checked) {
    document.querySelectorAll('.ct-node-cb').forEach(cb => cb.checked = checked);
  };

  window.ctSaveMonitorPoints = async function() {
    const checked = [], unchecked = [];
    document.querySelectorAll('.ct-node-cb').forEach(cb => {
      (cb.checked ? checked : unchecked).push(cb.dataset.id);
    });
    if (checked.length) await window.apiSetCustomMonitorPoints(currentTopoId, checked, true);
    if (unchecked.length) await window.apiSetCustomMonitorPoints(currentTopoId, unchecked, false);
    showToast('监测点设置已保存', 'success');
    window.ctSelectTopology(currentTopoId);
  };

  // ======================== 边参数批量设置 ========================
  window.ctToggleAllEdges = function(checked) {
    document.querySelectorAll('.ct-edge-cb').forEach(cb => cb.checked = checked);
  };

  window.ctApplyEdgeBatch = async function() {
    const edges = [...document.querySelectorAll('.ct-edge-cb')]
      .filter(cb => cb.checked)
      .map(cb => [cb.dataset.from, cb.dataset.to]);
    if (!edges.length) { showToast('请先勾选要设置的边', 'warning'); return; }

    const lengthVal = document.getElementById('ct-batch-length').value;
    const rVal = document.getElementById('ct-batch-r').value;
    const xVal = document.getElementById('ct-batch-x').value;
    const params = {};
    if (lengthVal !== '') params.length_km = parseFloat(lengthVal);
    if (rVal !== '') params.resistance_ohm_per_km = parseFloat(rVal);
    if (xVal !== '') params.reactance_ohm_per_km = parseFloat(xVal);
    if (Object.keys(params).length === 0) { showToast('至少填一个要设置的参数', 'warning'); return; }

    const result = await window.apiSetCustomEdgeParams(currentTopoId, edges, params);
    if (!result.ok) { showToast(result.error || '设置失败', 'error'); return; }
    showToast(`已更新 ${result.updated} 条边`, 'success');
    window.ctSelectTopology(currentTopoId);
  };

  // ======================== 用于故障定位 ========================
  window.ctUseForFaultLocate = async function(id) {
    navTo('fault');
    await fillFaultLineOptions();
    const sel = document.getElementById('fault-line-select');
    sel.value = id;
    await onFaultLineChange();
    showToast('已切换到该自定义拓扑，可以开始定位了', 'success');
  };

  // ======================== 简易树形预览（独立于 topology.js，逻辑更简单） ========================
  function renderPreviewSvg(detail) {
    const svgEl = document.getElementById('ct-preview-svg');
    if (!svgEl || typeof d3 === 'undefined') return;
    const svg = d3.select(svgEl);
    svg.selectAll('*').remove();

    const nodeById = Object.fromEntries(detail.nodes.map(n => [n.node_id, n]));
    const children = {};
    detail.nodes.forEach(n => children[n.node_id] = []);
    detail.nodes.forEach(n => { if (n.parent_id && children[n.parent_id]) children[n.parent_id].push(n.node_id); });

    const leafCount = {};
    function calcLeaf(id) {
      const ch = children[id] || [];
      if (!ch.length) { leafCount[id] = 1; return 1; }
      leafCount[id] = ch.reduce((s, c) => s + calcLeaf(c), 0);
      return leafCount[id];
    }
    const roots = detail.nodes.filter(n => !n.parent_id);
    if (!roots.length) return;
    roots.forEach(r => calcLeaf(r.node_id));

    const X_STEP = 70, Y_STEP = 26;
    const pos = {};
    let nextLeaf = 0;
    function assignPos(id, x) {
      const ch = (children[id] || []).slice().sort((a, b) => leafCount[a] - leafCount[b]);
      if (!ch.length) { pos[id] = { x, y: nextLeaf * Y_STEP }; nextLeaf++; return; }
      ch.slice(0, -1).forEach(c => assignPos(c, x + X_STEP));
      const main = ch[ch.length - 1];
      assignPos(main, x + X_STEP);
      pos[id] = { x, y: pos[main].y };
    }
    roots.forEach(r => assignPos(r.node_id, 30));

    const W = svgEl.clientWidth || 600, H = 220;
    const allY = Object.values(pos).map(p => p.y);
    const minY = Math.min(...allY), maxY = Math.max(...allY);
    const centerY = (H - (maxY - minY)) / 2 - minY;
    const maxX = Math.max(...Object.values(pos).map(p => p.x));
    const scale = Math.min((W - 60) / Math.max(maxX, 1), 1);

    const g = svg.append('g').attr('transform', `translate(10,${centerY}) scale(${scale})`);

    detail.nodes.forEach(n => {
      if (!n.parent_id || !pos[n.parent_id] || !pos[n.node_id]) return;
      const from = pos[n.parent_id], to = pos[n.node_id];
      const path = Math.abs(from.y - to.y) < 1
        ? `M${from.x},${from.y} L${to.x},${to.y}`
        : `M${from.x},${from.y} L${from.x},${to.y} L${to.x},${to.y}`;
      g.append('path').attr('d', path).attr('fill', 'none')
        .attr('stroke', 'rgba(255,255,255,0.15)').attr('stroke-width', 1.5);
    });

    detail.nodes.forEach(n => {
      const p = pos[n.node_id];
      if (!p) return;
      const color = n.is_monitor_point ? '#00d4ff' : '#64748b';
      const grp = g.append('g').attr('transform', `translate(${p.x},${p.y})`);
      grp.append('circle').attr('r', n.is_monitor_point ? 6 : 4).attr('fill', color)
        .attr('stroke', d3.color(color).brighter(0.5)).attr('stroke-width', 1);
      grp.append('text').attr('y', -9).attr('text-anchor', 'middle')
        .attr('fill', 'rgba(255,255,255,0.6)').attr('font-size', 9)
        .attr('font-family', 'JetBrains Mono, monospace')
        .text(n.label);
    });
  }

})();
