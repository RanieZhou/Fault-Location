# -*- coding: utf-8 -*-
"""web/routers/agent.py — LLM Agent对话API（SSE流式，支持工具调用）"""
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class ChatRequest(BaseModel):
    messages: list[dict]       # [{role: user|assistant, content: ...}]
    provider: str = "deepseek" # deepseek | qwen | openai
    line: Optional[str] = None # 当前上下文线路（可选）


async def _sse_generator(messages: list[dict], provider: str):
    """将 graph.run_agent 的事件转换为 SSE 格式"""
    from agent.graph import run_agent
    async for event in run_agent(messages, provider=provider):
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/chat")
async def agent_chat(req: ChatRequest):
    """
    Agent 对话（SSE 流式输出）。
    事件类型：
      - {type: "delta", delta: "..."} 文本增量
      - {type: "tool_start", tool_name: "...", tool_args: {...}} 工具调用开始
      - {type: "tool_end", tool_name: "...", success: true, result_preview: "..."} 工具调用结束
      - {type: "done"} 完成
      - {type: "error", content: "..."} 错误
    """
    return StreamingResponse(
        _sse_generator(req.messages, req.provider),
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
