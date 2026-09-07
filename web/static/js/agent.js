/**
 * agent.js — LLM Agent对话界面逻辑（支持工具调用展示）
 */

(function() {
  let conversationHistory = [];   // { role, content }[]
  let isThinking = false;

  // ======================== 发送消息 ========================
  window.sendAgentMessage = async function() {
    const textarea = document.getElementById('agent-textarea');
    const text = textarea.value.trim();
    if (!text || isThinking) return;

    textarea.value = '';
    autoResize(textarea);

    appendUserMsg(text);
    conversationHistory.push({ role: 'user', content: text });

    const provider = document.getElementById('agent-provider-select').value;
    await runAgent(provider);
  };

  window.sendQuickPrompt = function(text) {
    document.getElementById('agent-textarea').value = text;
    sendAgentMessage();
  };

  window.handleAgentKey = function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendAgentMessage();
    }
  };

  window.autoResize = function(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  };

  window.clearAgentHistory = function() {
    conversationHistory = [];
    document.getElementById('agent-messages').innerHTML = `
      <div class="msg agent">
        <div class="msg-avatar"><i class="bi bi-robot" style="font-size:15px;color:#a78bfa"></i></div>
        <div class="msg-bubble">
          <p>对话已清空。请描述新的故障情况，或选择下方快捷问题。</p>
        </div>
      </div>`;
    document.getElementById('tool-log').innerHTML = `
      <div style="text-align:center;padding:24px 0;color:var(--text-muted)">
        <i class="bi bi-tools" style="font-size:28px;display:block;margin-bottom:8px;opacity:0.4"></i>
        <div>对话开始后，<br>工具调用记录显示在这里</div>
      </div>`;
  };

  // ======================== Agent运行 ========================
  async function runAgent(provider) {
    isThinking = true;
    document.getElementById('agent-send-btn').disabled = true;

    // 显示思考中气泡
    const thinkId = 'think-' + Date.now();
    appendThinking(thinkId);

    let assistantContent = '';
    let msgEl = null;
    let firstTextChunk = true;
    let activeToolEl = null;   // 当前正在进行的工具调用气泡

    try {
      const stream = window.apiAgentChat(conversationHistory, provider);

      for await (const chunk of stream) {

        // ── 错误 ──────────────────────────────────────────
        if (chunk.type === 'error') {
          removeElement(thinkId);
          if (activeToolEl) { finalizeToolEl(activeToolEl, false, chunk.content); activeToolEl = null; }
          appendAgentMsg(`❌ ${chunk.content}`);
          break;
        }

        // ── 工具调用开始 ────────────────────────────────
        if (chunk.type === 'tool_start') {
          removeElement(thinkId);  // 移除思考气泡，换成工具气泡

          // 如果还没有消息气泡，先创建一个
          if (!msgEl) {
            msgEl = appendAgentMsgEl('');
            firstTextChunk = false;
          }

          // 在消息气泡里追加工具调用块（进行中状态）
          activeToolEl = appendToolCallBlock(msgEl, chunk.tool_name, chunk.tool_args, 'running');

          // 在右侧工具日志面板也记录
          logToolCallStart(chunk.tool_name, chunk.tool_args, chunk.call_id);
          continue;
        }

        // ── 工具调用结束 ────────────────────────────────
        if (chunk.type === 'tool_end') {
          if (activeToolEl) {
            finalizeToolEl(activeToolEl, chunk.success, chunk.result_preview);
            activeToolEl = null;
          }
          logToolCallEnd(chunk.call_id, chunk.success, chunk.result_preview);

          // 工具结束后显示新的"思考中"等待LLM总结
          appendThinking(thinkId);
          continue;
        }

        // ── 文本增量 ────────────────────────────────────
        if (chunk.type === 'delta') {
          const text = chunk.delta || '';
          if (!text) continue;

          removeElement(thinkId);

          if (firstTextChunk) {
            if (!msgEl) msgEl = appendAgentMsgEl('');
            firstTextChunk = false;
          }
          assistantContent += text;
          if (msgEl) updateMsgEl(msgEl, assistantContent);
        }

        if (chunk.type === 'done') break;
      }

      if (firstTextChunk) removeElement(thinkId);
      if (assistantContent) conversationHistory.push({ role: 'assistant', content: assistantContent });

    } catch (e) {
      removeElement(thinkId);
      appendAgentMsg(`❌ 请求失败：${e.message}`);
    } finally {
      isThinking = false;
      document.getElementById('agent-send-btn').disabled = false;
      scrollMsgs();
    }
  }

  // ======================== DOM：消息气泡 ========================
  function appendUserMsg(text) {
    const container = document.getElementById('agent-messages');
    const el = document.createElement('div');
    el.className = 'msg user';
    el.innerHTML = `
      <div class="msg-avatar" style="background:var(--cyan-dim);border:1px solid var(--border-bright);font-size:12px;font-weight:700;color:var(--cyan)">我</div>
      <div class="msg-bubble"><p>${escapeHtml(text)}</p></div>`;
    container.appendChild(el);
    scrollMsgs();
  }

  function appendAgentMsgEl(html) {
    const container = document.getElementById('agent-messages');
    const el = document.createElement('div');
    el.className = 'msg agent';
    el.innerHTML = `
      <div class="msg-avatar" style="background:var(--purple-dim);border:1px solid rgba(124,58,237,0.3)">
        <i class="bi bi-robot" style="font-size:14px;color:#a78bfa"></i>
      </div>
      <div class="msg-bubble msg-content">${html || '<p></p>'}</div>`;
    container.appendChild(el);
    scrollMsgs();
    return el.querySelector('.msg-content');
  }

  function appendAgentMsg(text) {
    appendAgentMsgEl(`<p>${escapeHtml(text)}</p>`);
  }

  function updateMsgEl(el, markdown) {
    el.innerHTML = markdownToHtml(markdown);
    scrollMsgs();
  }

  function appendThinking(id) {
    removeElement(id);  // 先移除旧的（防重复）
    const container = document.getElementById('agent-messages');
    const el = document.createElement('div');
    el.className = 'msg agent';
    el.id = id;
    el.innerHTML = `
      <div class="msg-avatar" style="background:var(--purple-dim);border:1px solid rgba(124,58,237,0.3)">
        <i class="bi bi-robot" style="font-size:14px;color:#a78bfa"></i>
      </div>
      <div class="msg-bubble">
        <div class="typing-indicator">
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
        </div>
      </div>`;
    container.appendChild(el);
    scrollMsgs();
  }

  // ======================== DOM：工具调用块 ========================
  function appendToolCallBlock(msgEl, toolName, toolArgs, status) {
    const block = document.createElement('div');
    block.className = 'tool-call-block';
    block.setAttribute('data-status', status);
    const argsPreview = toolArgs ? JSON.stringify(toolArgs).slice(0, 80) : '';
    block.innerHTML = `
      <div class="tool-call-header">
        <i class="bi bi-tools" style="color:var(--text-muted)"></i>
        <span class="tool-name">${escapeHtml(toolName)}</span>
        <span class="tool-status" style="margin-left:auto;font-size:10px">
          <span class="tool-spinner"></span> 执行中...
        </span>
      </div>
      <div class="tool-call-body" style="color:var(--text-muted);font-size:11px">${escapeHtml(argsPreview)}</div>`;
    msgEl.appendChild(block);
    scrollMsgs();
    return block;
  }

  function finalizeToolEl(block, success, resultPreview) {
    const statusEl = block.querySelector('.tool-status');
    if (statusEl) {
      statusEl.innerHTML = success
        ? `<span style="color:var(--green)">✓ 完成</span>`
        : `<span style="color:var(--red)">✗ 失败</span>`;
    }
    const bodyEl = block.querySelector('.tool-call-body');
    if (bodyEl && resultPreview) {
      bodyEl.textContent = resultPreview;
      bodyEl.style.color = success ? 'var(--text-secondary)' : 'var(--red)';
    }
    block.setAttribute('data-status', success ? 'done' : 'error');
  }

  // ======================== DOM：右侧工具日志 ========================
  const _toolLogItems = {};  // call_id → DOM element

  function logToolCallStart(toolName, toolArgs, callId) {
    const log = document.getElementById('tool-log');
    // 清除占位
    const placeholder = log.querySelector('div[style*="text-align:center"]');
    if (placeholder) log.innerHTML = '';

    const el = document.createElement('div');
    el.className = 'tool-call-block';
    const argsStr = toolArgs ? JSON.stringify(toolArgs, null, 2) : '';
    el.innerHTML = `
      <div class="tool-call-header" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'">
        <i class="bi bi-tools" style="color:var(--text-muted)"></i>
        <span class="tool-name">${escapeHtml(toolName)}</span>
        <span style="margin-left:auto;font-size:10px;color:var(--text-muted)">
          <span class="tool-spinner"></span>
        </span>
      </div>
      <div class="tool-call-body" style="display:none">${escapeHtml(argsStr)}</div>`;
    log.prepend(el);
    if (callId) _toolLogItems[callId] = el;
  }

  function logToolCallEnd(callId, success, resultPreview) {
    const el = _toolLogItems[callId];
    if (!el) return;
    const statusEl = el.querySelector('.tool-call-header span:last-child');
    if (statusEl) {
      statusEl.innerHTML = success
        ? `<span style="color:var(--green)">✓</span>`
        : `<span style="color:var(--red)">✗</span>`;
    }
    const bodyEl = el.querySelector('.tool-call-body');
    if (bodyEl && resultPreview) {
      bodyEl.textContent = (bodyEl.textContent ? bodyEl.textContent + '\n→ ' : '') + resultPreview;
    }
  }

  function removeElement(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  function scrollMsgs() {
    const c = document.getElementById('agent-messages');
    c.scrollTop = c.scrollHeight;
  }

  // ======================== Markdown渲染（marked + DOMPurify） ========================
  // 之前是手写正则拼HTML，不支持表格/有序列表/嵌套列表，标题这些遇到LLM输出的
  // 表格就直接显示成一堆裸的 "| a | b |"。改用真正的Markdown解析库；LLM输出不算
  // 完全可信内容（可能被工具结果里的异常文本影响、或偶尔生成奇怪的HTML），渲染前
  // 用 DOMPurify 净化一遍，不直接信任 marked 输出的原始HTML。
  if (window.marked) {
    marked.setOptions({ breaks: true, gfm: true });
  }

  function markdownToHtml(md) {
    if (!window.marked || !window.DOMPurify) {
      // CDN 加载失败时的兜底：至少不要把内容吞掉，退化成纯文本
      return `<p>${escapeHtml(md).replace(/\n/g, '<br>')}</p>`;
    }
    const rawHtml = marked.parse(md || '');
    return DOMPurify.sanitize(rawHtml);
  }

  function escapeHtml(str) {
    if (typeof str !== 'string') return String(str || '');
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ======================== 从故障定位跳转到Agent ========================
  window.askAgentForFault = function() {
    const line = document.getElementById('fault-line-select').value;
    const lineName = window.TOPO_DATA[line]?.name || line;
    const tags = [...document.querySelectorAll('#alarm-tags .alarm-tag span:first-child')].map(s => s.textContent);
    if (tags.length === 0) { showToast('请先完成故障定位', 'warning'); return; }
    const faultType = document.getElementById('fault-type-select').value;
    const typeStr = faultType ? `，故障类型为${faultType}` : '';
    const prompt = `请详细分析${lineName}的这次故障：报警监测点为 ${tags.join('、')}${typeStr}。请给出：1) 精确故障区段；2) 可能原因；3) 具体巡线建议和派工说明。`;
    document.getElementById('agent-textarea').value = prompt;
    navTo('agent');
    setTimeout(() => sendAgentMessage(), 100);
  };

  window.onProviderChange = function() {
    // 可在此处添加提供商切换时的处理逻辑
  };

  // ======================== 加载真实工具列表（替换静态占位） ========================
  async function loadAvailableTools() {
    try {
      const r = await fetch('/api/agent/tools', { signal: AbortSignal.timeout(3000) });
      if (!r.ok) return;
      const data = await r.json();
      if (!data.tools || !data.tools.length) return;
      const container = document.getElementById('available-tools-list');
      if (!container) return;
      container.innerHTML = data.tools.map(t => `
        <div class="tool-call-block" style="cursor:default" title="${escapeHtml(t.description || '')}">
          <div class="tool-call-header" style="cursor:default">
            <i class="bi bi-tools" style="color:var(--text-muted)"></i>
            <span class="tool-name">${escapeHtml(t.name)}</span>
          </div>
        </div>`).join('');
    } catch {
      // 保留静态兜底列表
    }
  }
  setTimeout(loadAvailableTools, 1200);

})();
