"""
agent/graph.py — Tool-calling 工作流
使用原生 OpenAI function calling（兼容 DeepSeek/Qwen）
支持多轮工具调用，SSE 流式输出
"""
from __future__ import annotations
import json
import asyncio
from typing import AsyncGenerator

from .llm_client import get_client
from .prompts import SYSTEM_PROMPT
from .tools import TOOL_SCHEMAS, execute_tool


# ── SSE 事件类型 ──────────────────────────────────────────────
# delta      : 文本增量（流式输出每个字符）
# tool_start : 工具调用开始（含工具名、参数）
# tool_end   : 工具调用结束（含工具结果摘要）
# done       : 完成
# error      : 错误


async def run_agent(
    messages: list[dict],
    provider: str = "deepseek",
    max_tool_rounds: int = 5,
) -> AsyncGenerator[dict, None]:
    """
    主 Agent 工作流，返回 SSE 事件的异步生成器。
    
    流程：
    1. 调用 LLM（带工具定义）
    2. 若 LLM 返回 tool_calls → 执行工具 → 将结果追加到消息 → 继续循环
    3. 若 LLM 返回纯文本 → 流式输出 → 结束
    """
    try:
        client, model, _ = get_client(provider)
    except ValueError as e:
        yield {"type": "error", "content": str(e)}
        return

    # 构建完整消息列表（含系统提示）
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(messages)

    for round_idx in range(max_tool_rounds):
        try:
            # ── 第一步：调用LLM ──────────────────────────────
            # 如果是最后一轮（工具次数用完），强制不使用工具
            tools = TOOL_SCHEMAS if round_idx < max_tool_rounds - 1 else []

            response = await client.chat.completions.create(
                model=model,
                messages=full_messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
                stream=False,        # 第一步不流式（需要完整响应来判断是否有tool_calls）
                temperature=0.3,
                max_tokens=3000,
            )

            choice = response.choices[0]
            msg = choice.message

            # ── 第二步：检查是否有工具调用 ──────────────────
            if msg.tool_calls:
                # 先把 assistant 消息加入历史
                full_messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                })

                # 执行每个工具调用
                for tc in msg.tool_calls:
                    tool_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}

                    # 通知前端：工具开始调用
                    yield {
                        "type": "tool_start",
                        "tool_name": tool_name,
                        "tool_args": args,
                        "call_id": tc.id,
                    }

                    # 执行工具（同步，在线程池中运行）
                    try:
                        result = await asyncio.get_event_loop().run_in_executor(
                            None, execute_tool, tool_name, args
                        )
                        result_str = json.dumps(result, ensure_ascii=False)
                        success = True
                    except Exception as e:
                        result = {"error": str(e)}
                        result_str = json.dumps(result, ensure_ascii=False)
                        success = False

                    # 通知前端：工具结束
                    yield {
                        "type": "tool_end",
                        "tool_name": tool_name,
                        "call_id": tc.id,
                        "success": success,
                        "result_preview": _preview(result),
                    }

                    # 将工具结果加入消息历史
                    full_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                    })

                # 继续下一轮（让 LLM 消化工具结果）
                continue

            # ── 第三步：纯文本回复，流式输出 ────────────────
            else:
                content = msg.content or ""
                if not content:
                    yield {"type": "error", "content": "LLM 返回了空响应"}
                    return

                # 模拟流式输出（将完整内容分块发送）
                chunk_size = 8
                for i in range(0, len(content), chunk_size):
                    yield {"type": "delta", "delta": content[i:i + chunk_size]}
                    await asyncio.sleep(0.01)  # 小延迟模拟流式

                yield {"type": "done"}
                return

        except Exception as e:
            yield {"type": "error", "content": f"LLM 请求失败：{str(e)[:300]}"}
            return

    # 超过最大工具轮次
    yield {"type": "error", "content": "超过最大工具调用轮次，请重试或简化问题。"}


def _preview(result: dict | list, max_len: int = 120) -> str:
    """生成工具结果的简短预览文本，用于前端展示"""
    if isinstance(result, dict):
        if "error" in result:
            return f"❌ {result['error']}"
        if "candidate_sections" in result:
            sections = result.get("candidate_sections", [])
            if sections:
                return f"✅ 候选区段：{', '.join(sections[:2])}"
        if "similar_events" in result:
            n = len(result.get("similar_events", []))
            return f"✅ 找到 {n} 条相似历史记录"
        if "suggestion" in result:
            return f"✅ 派工建议已生成"
        if "node_count" in result:
            return f"✅ {result.get('line', '')} 共 {result['node_count']} 个监测点"
        if "pole" in result:
            return f"✅ {result['pole']}号杆，深度{result.get('depth', '?')}，{'末端节点' if result.get('is_leaf') else '分支节点' if result.get('is_branch_point') else '中间节点'}"
        if "events" in result:
            return f"✅ 共 {result.get('total', 0)} 条历史事件"
    s = json.dumps(result, ensure_ascii=False)
    return s[:max_len] + ("..." if len(s) > max_len else "")
