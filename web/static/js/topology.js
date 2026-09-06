/**
 * topology.js — D3.js 配电网拓扑可视化
 * 支持：缩放/平移、节点点击、状态高亮（正常/告警/故障）
 */

(function() {
  let currentLine = null;
  let svg, g, zoom;
  let nodeStatus = {};       // id -> 'normal' | 'alarm' | 'fault'（只会落在监测点身上）
  let faultSectionPairs = []; // [[frontierId, candidateId|null], ...]——折叠视图里的"虚拟边"两端，
                               // 渲染时才在完整物理图里展开成中间实际跳过的每一段真实边（见 computeFaultEdges）
  let selectedNode = null;

  const COLOR = {
    source:  '#7c3aed',
    normal:  '#10b981',
    alarm:   '#f59e0b',
    fault:   '#ef4444',
    structural: '#64748b',
    edge:    'rgba(255,255,255,0.12)',
    edgeFault: '#ef4444',
    edgeSect:  '#f59e0b',
    text:    'rgba(255,255,255,0.65)',
  };

  // ======================== 初始化 ========================
  window.initTopology = function() {
    svg = d3.select('#topo-svg');
    const rect = document.getElementById('topo-svg').getBoundingClientRect();

    zoom = d3.zoom()
      .scaleExtent([0.2, 4])
      .on('zoom', e => g.attr('transform', e.transform));

    svg.call(zoom);
    g = svg.append('g').attr('class', 'topo-root');

    renderLine(currentLine);
  };

  // ======================== 切换线路 ========================
  // lineCode 是自定义拓扑的 topology_id。window.TOPO_DATA[lineCode] 存的是"完整物理图"
  // （含未装监测设备的结构杆塔，is_monitor_point区分），这是拓扑监控页要展示的真实拓扑；
  // 算法实际用的"监测点折叠简化树"是另一份数据（window.TOPO_DATA_MONITOR，见 app.js），
  // 两者服务不同目的，不能混用同一个缓存——之前就是因为共用了一份数据，导致主监控页
  // 显示的是算法内部的折叠视图（只剩几个孤零零的点连成一条直线），而不是真实拓扑。
  window.switchLine = function(lineCode) {
    currentLine = lineCode;
    nodeStatus = {};
    faultSectionPairs = [];
    selectedNode = null;

    const sel = document.getElementById('topo-line-select');
    if (sel && sel.value !== lineCode) sel.value = lineCode;

    updateLineStats(lineCode);
    renderLine(lineCode);
    renderNodeDetail(null);
    buildQuickNodeList(lineCode);
    loadTopoFromAPI(lineCode);
  };

  function updateLineStats(lineCode) {
    const data = window.TOPO_DATA[lineCode];
    if (!data) return;  // 自定义拓扑首次选中时还没异步加载完，loadTopoFromAPI拿到数据后会重新调用
    document.getElementById('ls-name').textContent = data.name;
    const nodeLabel = data.totalNodeCount != null ? `${data.nodeCount}个（共${data.totalNodeCount}个节点）` : `${data.nodeCount}个`;
    document.getElementById('ls-nodes').textContent = nodeLabel;
    document.getElementById('ls-branches').textContent = data.branchCount + '条';
    document.getElementById('ls-faults').textContent = data.faultCount + '次';
  }

  // ======================== 从后端加载拓扑数据 ========================
  const _apiLoaded = {};  // lineCode(topology_id) -> true 一旦已从后端加载成功

  async function loadTopoFromAPI(lineCode) {
    if (_apiLoaded[lineCode] || typeof window.apiGetCustomTopologyDetail !== 'function') return;
    try {
      const detail = await window.apiGetCustomTopologyDetail(lineCode);
      const data = detail ? window.normalizeCustomTopoFullAsTopoData(detail) : null;
      if (data && data.__fromApi && data.nodes && data.nodes.length > 1) {
        window.TOPO_DATA[lineCode] = data;
        _apiLoaded[lineCode] = true;
        if (lineCode === currentLine) {
          updateLineStats(lineCode);
          renderLine(lineCode);
          renderNodeDetail(selectedNode);
          buildQuickNodeList(lineCode);
        }
      }
    } catch {
      // 保持静态兜底数据（若有），不影响已渲染的视图
    }
  }

  // ======================== 布局计算 ========================
  function computeLayout(nodes) {
    // 构建 children map
    const children = {};
    const nodeMap = {};
    nodes.forEach(n => {
      nodeMap[n.id] = n;
      children[n.id] = [];
    });
    nodes.forEach(n => {
      if (n.parent && nodeMap[n.parent]) {
        children[n.parent].push(n.id);
      }
    });

    // 计算每个子树的叶子数（用于Y轴分配）
    const leafCount = {};
    function calcLeaf(id) {
      const ch = children[id] || [];
      if (ch.length === 0) { leafCount[id] = 1; return 1; }
      let s = 0;
      ch.forEach(c => s += calcLeaf(c));
      leafCount[id] = s;
      return s;
    }

    // 找根
    const roots = nodes.filter(n => !n.parent || n.parent === null);
    roots.forEach(r => calcLeaf(r.id));

    const X_STEP = 110;
    const Y_STEP = 38;
    const pos = {};
    let nextLeaf = 0;

    function assignPos(id, x) {
      const ch = (children[id] || []).slice().sort((a, b) => {
        // 主干（单数字杆号）优先排最后（占住主线行），其余分支往上
        const aIsMain = !nodeMap[a].pole.includes('.');
        const bIsMain = !nodeMap[b].pole.includes('.');
        if (aIsMain && !bIsMain) return 1;
        if (!aIsMain && bIsMain) return -1;
        return 0;
      });

      if (ch.length === 0) {
        pos[id] = { x, y: nextLeaf * Y_STEP };
        nextLeaf++;
        return;
      }

      // 先放非主干分支
      ch.slice(0, -1).forEach(c => assignPos(c, x + X_STEP));
      // 主干放在最后（继承父节点的行）
      const main = ch[ch.length - 1];
      assignPos(main, x + X_STEP);
      // 父节点Y = 主干Y
      pos[id] = { x, y: pos[main].y };
    }

    roots.forEach(r => assignPos(r.id, 0));
    return pos;
  }

  // 把"折叠视图虚拟边"两端(frontierId, candidateId)展开成完整物理图里中间跳过的
  // 每一段真实边——不然图上只会高亮最后一跳，看起来像漏了一大截线路。
  // 在渲染时（而不是setFaultSection调用时）才计算，是因为调用setFaultSection时
  // 完整拓扑数据可能还没异步加载完；等loadTopoFromAPI拿到数据后重新renderLine，
  // 这里会用上当时最新的nodeById重新算一遍，不会因为数据晚到而漏画。
  function computeFaultEdges(nodeById) {
    const edges = [];
    faultSectionPairs.forEach(([fromId, toId]) => {
      if (!toId) return;
      let cur = nodeById[toId];
      let guard = 0;
      while (cur && cur.id !== fromId && cur.parent && guard++ < 500) {
        edges.push([cur.parent, cur.id]);
        cur = nodeById[cur.parent];
      }
    });
    return edges;
  }

  // ======================== 渲染 ========================
  function renderLine(lineCode) {
    g.selectAll('*').remove();

    const data = window.TOPO_DATA[lineCode];
    if (!data) return;  // 自定义拓扑首次选中时还没异步加载完，loadTopoFromAPI拿到数据后会重新调用
    const nodes = data.nodes;
    const nodeById = Object.fromEntries(nodes.map(n => [n.id, n]));
    const faultSection = computeFaultEdges(nodeById);
    const pos = computeLayout(nodes);

    // 偏移使SOURCE在左边
    const svgEl = document.getElementById('topo-svg');
    const W = svgEl.clientWidth || 800;
    const H = svgEl.clientHeight || 500;
    const allY = Object.values(pos).map(p => p.y);
    const minY = Math.min(...allY), maxY = Math.max(...allY);
    const centerY = (H - (maxY - minY)) / 2;

    // SOURCE 特殊位置
    const sourceX = pos['SOURCE'] ? pos['SOURCE'].x - 80 : -80;
    const srcPos = { x: sourceX, y: pos['SOURCE'] ? pos['SOURCE'].y + centerY : centerY };

    function getPos(id) {
      if (id === 'SOURCE') return srcPos;
      const p = pos[id];
      return p ? { x: p.x, y: p.y + centerY } : { x: 0, y: 0 };
    }

    // 画边
    const edgeLayer = g.append('g').attr('class', 'edges');
    nodes.forEach(n => {
      if (!n.parent) return;
      const from = getPos(n.parent);
      const to = getPos(n.id);

      // 判断是否是故障区段边
      const isFaultEdge = faultSection.some(([f,t]) => f === n.parent && t === n.id);
      // 判断折线还是直线（同行 = 直线，不同行 = L形）
      const edgeColor = isFaultEdge ? COLOR.edgeFault : COLOR.edge;
      const strokeW = isFaultEdge ? 3 : 1.5;

      if (Math.abs(from.y - to.y) < 1) {
        // 同行：直线
        edgeLayer.append('line')
          .attr('x1', from.x).attr('y1', from.y)
          .attr('x2', to.x).attr('y2', to.y)
          .attr('stroke', edgeColor)
          .attr('stroke-width', strokeW)
          .attr('stroke-dasharray', isFaultEdge ? '6,3' : 'none');
      } else {
        // 分支：L形折线（先竖后横）
        const path = `M${from.x},${from.y} L${from.x},${to.y} L${to.x},${to.y}`;
        edgeLayer.append('path')
          .attr('d', path)
          .attr('fill', 'none')
          .attr('stroke', edgeColor)
          .attr('stroke-width', strokeW)
          .attr('stroke-dasharray', isFaultEdge ? '6,3' : 'none');
      }
    });

    // 电源母线竖线
    const srcPosVal = srcPos;
    g.append('line')
      .attr('x1', srcPosVal.x - 20).attr('y1', minY + centerY - 30)
      .attr('x2', srcPosVal.x - 20).attr('y2', maxY + centerY + 30)
      .attr('stroke', COLOR.source)
      .attr('stroke-width', 6)
      .attr('stroke-linecap', 'round')
      .attr('opacity', 0.8);

    // 画节点
    const nodeLayer = g.append('g').attr('class', 'nodes');
    nodes.forEach(n => {
      const p = getPos(n.id);
      const status = nodeStatus[n.id] || 'normal';
      const isSource = n.id === 'SOURCE';

      const grp = nodeLayer.append('g')
        .attr('class', 'node-g')
        .attr('transform', `translate(${p.x},${p.y})`)
        .attr('cursor', isSource ? 'default' : 'pointer')
        .on('click', () => { if (!isSource) onNodeClick(n); });

      if (isSource) {
        // 电源节点：菱形
        grp.append('polygon')
          .attr('points', '0,-14 10,0 0,14 -10,0')
          .attr('fill', COLOR.source)
          .attr('stroke', '#a78bfa')
          .attr('stroke-width', 1.5);
        grp.append('text')
          .attr('y', -20).attr('text-anchor', 'middle')
          .attr('fill', 'rgba(167,139,250,0.9)')
          .attr('font-size', 10)
          .text('变电站');
        return;
      }

      // 普通节点：结构杆塔（未装监测设备）统一显示成小灰点，不参与告警/故障状态着色
      const isMonitor = n.isMonitorPoint !== false;
      const color = !isMonitor ? COLOR.structural :
                    status === 'fault'  ? COLOR.fault  :
                    status === 'alarm'  ? COLOR.alarm  : COLOR.normal;
      const r = !isMonitor ? 4 : (status !== 'normal' ? 9 : 7);

      // 告警/故障光晕
      if (status !== 'normal') {
        grp.append('circle').attr('r', r + 8)
          .attr('fill', 'none')
          .attr('stroke', color)
          .attr('stroke-width', 1)
          .attr('opacity', 0.3);
      }

      grp.append('circle')
        .attr('r', r)
        .attr('fill', color)
        .attr('stroke', d3.color(color).brighter(0.5))
        .attr('stroke-width', 1.5)
        .attr('filter', status !== 'normal' ? `drop-shadow(0 0 6px ${color})` : 'none');

      // 选中圆环
      if (selectedNode && selectedNode.id === n.id) {
        grp.append('circle').attr('r', r + 5)
          .attr('fill', 'none')
          .attr('stroke', '#00d4ff')
          .attr('stroke-width', 2)
          .attr('stroke-dasharray', '4,3');
      }

      // 节点标签：结构杆塔字号小一些、更淡，避免和监测点抢视觉焦点
      grp.append('text')
        .attr('y', isMonitor ? -14 : -9).attr('text-anchor', 'middle')
        .attr('fill', isMonitor ? COLOR.text : 'rgba(255,255,255,0.35)')
        .attr('font-size', isMonitor ? 10 : 8)
        .attr('font-family', 'JetBrains Mono, monospace')
        .text(n.label);
    });

    // 初始居中
    const allPosVals = Object.values(pos);
    if (allPosVals.length > 0) {
      const maxX = Math.max(...allPosVals.map(p => p.x));
      const contentW = maxX - sourceX + 60;
      const contentH = maxY - minY + 80;
      const scale = Math.min(W / contentW, H / contentH, 1.2) * 0.85;
      const tx = (W - contentW * scale) / 2 - (sourceX * scale) + 30;
      const ty = (H - contentH * scale) / 2 + 30;
      svg.call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
    }
  }

  // ======================== 节点点击 ========================
  function onNodeClick(node) {
    selectedNode = node;
    renderLine(currentLine);  // 重绘以显示选中圆环
    renderNodeDetail(node);
    window._lastSelectedNode = node;
  }

  function renderNodeDetail(node) {
    const body = document.getElementById('node-detail-body');
    if (!node) {
      body.innerHTML = `<div class="node-info-placeholder"><div class="ph-icon">👆</div><div>点击拓扑图中的<br>节点查看详情</div></div>`;
      return;
    }
    const lineCode = currentLine;
    const load = window.TOPO_DATA[lineCode]?.loads?.[node.id];
    const isMonitor = node.isMonitorPoint !== false;
    const status = nodeStatus[node.id] || 'normal';
    const statusLabel = { normal: '正常', alarm: '告警', fault: '故障' }[status];
    const statusClass = { normal: 'badge-green', alarm: 'badge-amber', fault: 'badge-red' }[status];
    body.innerHTML = `
      <div style="padding:14px 18px">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
          <div style="font-size:16px;font-weight:700;color:var(--text-primary);font-family:'JetBrains Mono',monospace">${node.label}</div>
          ${isMonitor ? `<span class="badge ${statusClass}">${statusLabel}</span>` : `<span class="badge badge-grey">结构杆塔</span>`}
        </div>
        <div style="font-size:12px;display:flex;flex-direction:column;gap:7px;color:var(--text-secondary)">
          <div style="display:flex;justify-content:space-between">
            <span style="color:var(--text-muted)">节点编号</span>
            <span style="font-family:'JetBrains Mono',monospace;color:var(--cyan)">${node.id}</span>
          </div>
          <div style="display:flex;justify-content:space-between">
            <span style="color:var(--text-muted)">距电源深度</span>
            <span>${node.depth + 1}跳</span>
          </div>
          <div style="display:flex;justify-content:space-between">
            <span style="color:var(--text-muted)">父节点</span>
            <span style="font-family:'JetBrains Mono',monospace">${node.parent || 'SOURCE'}</span>
          </div>
          ${load ? `<div style="display:flex;justify-content:space-between">
            <span style="color:var(--text-muted)">本地负荷</span>
            <span style="color:var(--amber)">${load.S_kva.toFixed(0)} kVA</span>
          </div>` : ''}
        </div>
        ${isMonitor ? `
        <div style="margin-top:12px;display:flex;gap:6px">
          <button class="btn btn-danger btn-sm" style="flex:1" onclick="setNodeStatus('${node.id}','alarm')">设为告警</button>
          <button class="btn btn-ghost btn-sm" onclick="setNodeStatus('${node.id}','normal')">清除</button>
        </div>` : `
        <div style="margin-top:12px;font-size:11px;color:var(--text-muted)">
          <i class="bi bi-info-circle"></i> 该节点未装监测设备，不能设为报警点
        </div>`}
      </div>`;
  }

  // ======================== 状态控制 ========================
  window.setNodeStatus = function(id, status) {
    nodeStatus[id] = status;
    renderLine(currentLine);
    const node = window.TOPO_DATA[currentLine].nodes.find(n => n.id === id);
    if (node) renderNodeDetail(node);
  };

  // sectionPairs: [[frontierId, candidateId|null], ...]——candidateId为null表示该前沿
  // 已是分支末端（无法进一步缩小），只标红前沿节点本身，没有边可高亮。
  window.setFaultSection = function(lineCode, alarmIds, frontierIds, sectionPairs) {
    if (lineCode !== currentLine) switchLine(lineCode);
    nodeStatus = {};
    alarmIds.forEach(id => nodeStatus[id] = 'alarm');
    frontierIds.forEach(id => nodeStatus[id] = 'fault');
    faultSectionPairs = sectionPairs || [];
    renderLine(lineCode);
  };

  // 从拓扑图选中后添加为报警点
  window.addSelectedAsAlarm = function() {
    if (!window._lastSelectedNode) { showToast('请先在拓扑图中点击一个监测点', 'warning'); return; }
    if (window._lastSelectedNode.isMonitorPoint === false) {
      showToast('该节点未装监测设备，不能设为报警点', 'warning');
      return;
    }
    const pole = window._lastSelectedNode.pole;
    addAlarmTag(pole);
    navTo('fault');
    showToast(`已将 ${pole} 添加为报警点`, 'success');
  };

  // ======================== 缩放控制 ========================
  window.topoZoomIn  = () => svg.transition().call(zoom.scaleBy, 1.4);
  window.topoZoomOut = () => svg.transition().call(zoom.scaleBy, 0.7);
  window.topoReset   = () => { nodeStatus = {}; faultSectionPairs = []; renderLine(currentLine); };

  // ======================== 快捷节点列表 ========================
  // 只列监测点——非监测点没有传感器，选它作为"报警点"没有物理意义。
  window.buildQuickNodeList = function(lineCode) {
    const el = document.getElementById('quick-node-list');
    const nameEl = document.getElementById('quick-line-name');
    if (!el) return;
    const data = window.TOPO_DATA_MONITOR[lineCode];
    if (!data) { nameEl.textContent = lineCode; el.innerHTML = ''; return; }
    nameEl.textContent = data.name;
    el.innerHTML = data.nodes.filter(n => n.id !== 'SOURCE').map(n =>
      `<button class="quick-prompt" onclick="addAlarmTag('${n.pole}')">${n.label}</button>`
    ).join('');
  };

  // ======================== 故障区段小拓扑图 ========================
  window.renderFaultMiniTopo = function(lineCode, alarmPoles, frontierPole, candidatePoles) {
    const svg = d3.select('#fault-topo-svg');
    svg.selectAll('*').remove();

    const data = window.TOPO_DATA_MONITOR[lineCode];
    if (!data) return;  // 自定义拓扑的预览数据可能还没异步加载完，静默跳过这张迷你图，不影响主结果展示
    const nodes = data.nodes.filter(n => n.id !== 'SOURCE');
    const relevantPoles = new Set([...alarmPoles, frontierPole, ...candidatePoles]);

    // 找相关节点链路（从电源到候选区段末端）
    const involvedIds = new Set();
    const nodeMap = Object.fromEntries(nodes.map(n => [n.pole, n]));

    // 将报警点、前沿点、候选点都加入
    relevantPoles.forEach(p => {
      const n = nodes.find(nd => nd.pole === p);
      if (n) {
        let cur = n;
        while (cur) {
          involvedIds.add(cur.id);
          cur = nodes.find(nd => nd.id === cur.parent);
        }
      }
    });
    // 候选区段的节点也加入
    candidatePoles.forEach(p => {
      const n = nodes.find(nd => nd.pole === p);
      if (n) involvedIds.add(n.id);
    });

    const involved = nodes.filter(n => involvedIds.has(n.id));
    if (involved.length === 0) return;

    const W = document.getElementById('fault-topo-svg').clientWidth || 400;
    const H = 160;
    const xStep = Math.min(90, (W - 60) / Math.max(involved.length, 1));

    // 简单线性布局
    const sorted = involved.sort((a, b) => a.depth - b.depth);
    const posMap = {};
    let x = 30;
    sorted.forEach(n => {
      posMap[n.id] = { x, y: H / 2 };
      x += xStep;
    });

    // 画边
    involved.forEach(n => {
      if (!n.parent || !posMap[n.parent] || !posMap[n.id]) return;
      const from = posMap[n.parent], to = posMap[n.id];
      const isAlarm = alarmPoles.includes(n.pole) || alarmPoles.includes(nodes.find(nd => nd.id === n.parent)?.pole);
      const isCand = candidatePoles.includes(n.pole);
      svg.append('line')
        .attr('x1', from.x).attr('y1', from.y)
        .attr('x2', to.x).attr('y2', to.y)
        .attr('stroke', isCand ? '#f59e0b' : (isAlarm ? '#ef4444' : 'rgba(255,255,255,0.15)'))
        .attr('stroke-width', isCand || isAlarm ? 3 : 1.5)
        .attr('stroke-dasharray', isCand ? '8,4' : 'none');
    });

    // 画节点
    involved.forEach(n => {
      const p = posMap[n.id];
      if (!p) return;
      const isAlarm = alarmPoles.includes(n.pole);
      const isFrontier = n.pole === frontierPole;
      const isCand = candidatePoles.includes(n.pole);
      const color = isFrontier ? '#ef4444' : (isCand ? '#f59e0b' : (isAlarm ? '#ef4444' : '#10b981'));

      svg.append('circle').attr('cx', p.x).attr('cy', p.y).attr('r', isFrontier ? 10 : 7)
        .attr('fill', color).attr('stroke', d3.color(color).brighter(0.5)).attr('stroke-width', 1.5)
        .attr('filter', `drop-shadow(0 0 5px ${color})`);

      svg.append('text').attr('x', p.x).attr('y', p.y - 16)
        .attr('text-anchor', 'middle').attr('fill', 'rgba(255,255,255,0.7)')
        .attr('font-size', 10).attr('font-family', 'JetBrains Mono, monospace')
        .text(n.label);

      if (isFrontier) {
        svg.append('text').attr('x', p.x).attr('y', p.y + 24)
          .attr('text-anchor', 'middle').attr('fill', '#ef4444')
          .attr('font-size', 9).text('前沿');
      } else if (isCand) {
        svg.append('text').attr('x', p.x).attr('y', p.y + 24)
          .attr('text-anchor', 'middle').attr('fill', '#f59e0b')
          .attr('font-size', 9).text('候选');
      }
    });

    // 电流方向箭头
    svg.append('defs').append('marker')
      .attr('id', 'arrow-red').attr('viewBox', '0 0 10 10')
      .attr('refX', 5).attr('refY', 5).attr('markerWidth', 6).attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path').attr('d', 'M 0 0 L 10 5 L 0 10 z').attr('fill', '#ef4444');
  };

  function showTopoEmptyState(show) {
    const empty = document.getElementById('topo-empty-state');
    const svgEl = document.getElementById('topo-svg');
    if (empty) empty.style.display = show ? 'flex' : 'none';
    if (svgEl) svgEl.style.display = show ? 'none' : 'block';
  }

  // 系统没有任何硬编码的固定线路，拓扑监控页默认展示"已上传拓扑里的第一个"；
  // 一个都没有时展示空状态，引导去"自定义拓扑"页上传。
  async function initFromUploadedTopologies() {
    if (typeof window.apiListCustomTopologies !== 'function') return;
    const topos = await window.apiListCustomTopologies();
    if (typeof window.fillCustomTopoOptions === 'function') await window.fillCustomTopoOptions('topo-line-select');
    if (!topos.length) {
      showTopoEmptyState(true);
      return;
    }
    showTopoEmptyState(false);
    switchLine(topos[0].id);
  }

  // 初始化
  document.addEventListener('DOMContentLoaded', () => {
    initTopology();
    showTopoEmptyState(true);
    // 延迟等api.js的checkBackend(500ms)完成，避免_backendAvailable还没就绪就查询
    setTimeout(initFromUploadedTopologies, 800);
  });

})();
