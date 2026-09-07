"""
agent/graph.py — Tool-calling 工作流
使用原生 OpenAI function calling（兼容 DeepSeek/Qwen）
支持多轮工具调用，SSE 流式输出
"""
from __future__ import annotations
import json
import asyncio
from typing import AsyncGenerator, Literal, TypedDict, Union

from .llm_client import get_client
from .prompts import build_system_prompt
from .tools import TOOL_SCHEMAS, execute_tool, tool_error


# ── SSE 事件类型 ──────────────────────────────────────────────
# 纯 TypedDict：运行时就是普通 dict，_sse_generator 的 json.dumps() 不用改，
# 只是给每个 yield 点加上字段名/类型检查。字段名和之前完全一致（前端不用改）。

class DeltaEvent(TypedDict):
    type: Literal["delta"]
    delta: str


class ToolStartEvent(TypedDict):
    type: Literal["tool_start"]
    tool_name: str
    tool_args: dict
    call_id: str


class ToolEndEvent(TypedDict):
    type: Literal["tool_end"]
    tool_name: str
    call_id: str
    success: bool
    result_preview: str


class DoneEvent(TypedDict):
    type: Literal["done"]


class ErrorEvent(TypedDict):
    type: Literal["error"]
    content: str


AgentEvent = Union[DeltaEvent, ToolStartEvent, ToolEndEvent, DoneEvent, ErrorEvent]


async def run_agent(
    messages: list[dict],
    provider: str = "deepseek",
    line: str | None = None,
    max_tool_rounds: int = 5,
) -> AsyncGenerator[AgentEvent, None]:
    """
    主 Agent 工作流，返回 SSE 事件的异步生成器。

    line：当前界面上下文拓扑id（可选）。有值时会附加进系统提示词，减少
    "每轮都要先调用 list_topologies 才知道在聊哪个拓扑"的重复调用；不影响
    Agent 仍然按规则调用工具核实具体数据的要求。

    流程：
    1. 调用 LLM（带工具定义）
    2. 若 LLM 返回 tool_calls → 执行工具 → 将结果追加到消息 → 继续循环
    3. 若 LLM 返回纯文本 → 流式输出 → 结束
    """
    try:
        client, model, _ = get_client(provider)
    except ValueError as e:
        yield ErrorEvent(type="error", content=str(e))
        return

    # 构建完整消息列表（含系统提示）
    full_messages = [{"role": "system", "content": build_system_prompt(line)}] + list(messages)

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
                    yield ToolStartEvent(type="tool_start", tool_name=tool_name, tool_args=args, call_id=tc.id)

                    # 执行工具（同步，在线程池中运行）
                    try:
                        result = await asyncio.get_event_loop().run_in_executor(
                            None, execute_tool, tool_name, args
                        )
                        # execute_tool 现在总是返回标准信封 {ok, error, summary, ...}——
                        # 工具内部判断出的失败（比如"拓扑不存在"）在这里才会被正确标成失败，
                        # 而不是只有 Python 异常才算失败（之前的行为：前者一律显示成功）。
                        success = bool(result.get("ok", True))
                    except Exception as e:
                        result = tool_error(str(e))
                        success = False
                    result_str = json.dumps(result, ensure_ascii=False)

                    # 通知前端：工具结束
                    yield ToolEndEvent(
                        type="tool_end", tool_name=tool_name, call_id=tc.id,
                        success=success, result_preview=_preview(result),
                    )

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
                    yield ErrorEvent(type="error", content="LLM 返回了空响应")
                    return

                # 模拟流式输出（将完整内容分块发送）
                chunk_size = 8
                for i in range(0, len(content), chunk_size):
                    yield DeltaEvent(type="delta", delta=content[i:i + chunk_size])
                    await asyncio.sleep(0.01)  # 小延迟模拟流式

                yield DoneEvent(type="done")
                return

        except Exception as e:
            yield ErrorEvent(type="error", content=f"LLM 请求失败：{str(e)[:300]}")
            return

    # 超过最大工具轮次
    yield ErrorEvent(type="error", content="超过最大工具调用轮次，请重试或简化问题。")


def _preview(result: dict, max_len: int = 120) -> str:
    """
    生成工具结果的简短预览文本，用于前端展示。
    所有工具现在都返回标准信封 {ok, error, summary, ...}（见 agent/tools.py 的
    tool_ok/tool_error），这里只需要读 ok/summary，不用再为每个新工具单独加特判——
    以前那套按 key 猜测的写法有好几个工具的输出对不上任何一条分支，会掉到裸 JSON，
    甚至有一个分支读到了不存在的 key（"共 0 条历史事件"不管实际有几条都是 0）。
    """
    if isinstance(result, dict):
        if not result.get("ok", True):
            return f"❌ {result.get('error') or '执行失败'}"
        if result.get("summary"):
            return f"✅ {result['summary']}"
    s = json.dumps(result, ensure_ascii=False)
    return s[:max_len] + ("..." if len(s) > max_len else "")
