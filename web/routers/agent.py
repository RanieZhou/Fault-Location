# -*- coding: utf-8 -*-
"""web/routers/agent.py — LLM Agent对话API（SSE流式，支持工具调用）"""
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional

from core.models import AgentChatRequest
from agent.llm_client import KNOWN_PROVIDERS

router = APIRouter()
# 输入模型用 core.models.AgentChatRequest（messages: list[AgentMessage]），
# 不再在这里重复定义一个宽松的 list[dict] 版本。


async def _sse_generator(messages: list[dict], provider: str, line: Optional[str] = None):
    """将 graph.run_agent 的事件转换为 SSE 格式"""
    from agent.graph import run_agent
    async for event in run_agent(messages, provider=provider, line=line):
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/chat")
async def agent_chat(req: AgentChatRequest):
    """
    Agent 对话（SSE 流式输出）。
    事件类型：
      - {type: "delta", delta: "..."} 文本增量
      - {type: "tool_start", tool_name: "...", tool_args: {...}} 工具调用开始
      - {type: "tool_end", tool_name: "...", success: true, result_preview: "..."} 工具调用结束
      - {type: "done"} 完成
      - {type: "error", content: "..."} 错误
    """
    if req.provider.lower() not in KNOWN_PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail=f"未知的 provider: {req.provider}，支持：{sorted(KNOWN_PROVIDERS)}",
        )
    messages = [m.model_dump() for m in req.messages]
    return StreamingResponse(
        _sse_generator(messages, req.provider, req.line),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/tools")
async def list_tools():
    """返回 Agent 支持的工具列表"""
    from agent.tools import TOOL_SCHEMAS
    return {
        "tools": [
            {
                "name": t["function"]["name"],
                "description": t["function"]["description"],
            }
            for t in TOOL_SCHEMAS
        ]
    }
