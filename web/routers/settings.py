# -*- coding: utf-8 -*-
"""
web/routers/settings.py — 系统设置API（LLM配置、算法参数）

LLM配置持久化在 SQLite（core.db.llm_provider_config 表），不再写 .env——
.env 是纯文本KV，用字符串拼接读写，遇到含特殊字符的值容易出问题；SQLite更
规范，也和历史事件持久化用同一套风格（见 core/db.py）。
"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class LLMConfig(BaseModel):
    provider: str     # deepseek | qwen | openai | custom
    api_key: str
    base_url: str
    model: str


class ModelsQuery(BaseModel):
    api_key: str
    base_url: str


@router.post("/llm")
async def save_llm_config(config: LLMConfig):
    from core import db

    db.save_llm_provider_config(config.provider, config.api_key, config.base_url, config.model)
    db.set_app_setting("active_llm_provider", config.provider)

    # 同步到 agent.llm_client 运行时缓存（当前进程立即生效，不用等下次 resolve_config 读库）
    try:
        from agent.llm_client import set_provider_config
        set_provider_config(config.provider, config.api_key, config.base_url, config.model)
    except ImportError:
        pass

    return {"ok": True, "message": f"{config.provider} 配置已保存"}


@router.post("/llm/test")
async def test_llm_connection(config: LLMConfig):
    """测试LLM连接是否正常"""
    try:
        from agent.llm_client import set_provider_config, test_connection
        set_provider_config(config.provider, config.api_key, config.base_url, config.model)
        result = await test_connection(config.provider)
        return result
    except Exception as e:
        return {"ok": False, "message": str(e), "provider": config.provider, "model": ""}


@router.post("/llm/models")
async def get_available_models(q: ModelsQuery):
    """
    拉取指定 api_key/base_url 下可用的模型列表，用于各 provider 面板的
    "获取模型列表"按钮。几乎所有 OpenAI 兼容服务都实现了标准的 GET /models
    端点，直接用当前表单里的值去试探，不依赖已保存的配置。
    """
    from agent.llm_client import list_models
    return await list_models(q.api_key, q.base_url)


@router.get("/llm")
async def get_llm_config():
    """
    返回当前激活的LLM配置（隐藏API key），用于顶部/侧边栏的连接状态显示。
    "是否已配置"复用 agent.llm_client.resolve_config()——它内部会读 SQLite +
    .env + 环境变量做完整fallback，这里不重复这套逻辑，只是取同一个答案，
    才能如实反映"Agent 现在能不能用"。
    """
    from core import db
    from agent.llm_client import resolve_config

    provider = db.get_app_setting("active_llm_provider", "deepseek")
    api_key, base_url, model = resolve_config(provider)

    return {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key": "***" if api_key else "",
        "configured": bool(api_key),
    }


@router.get("/llm/all")
async def get_all_llm_configs():
    """
    返回所有 provider 已保存的完整配置（含明文 api_key），供"系统设置"页面
    加载时把表单回填成上次保存的样子——这个接口本身受登录中间件保护，
    明文返回可以接受（同一用户自己保存的东西，给自己看）。
    """
    from core import db
    return {
        "active_provider": db.get_app_setting("active_llm_provider", "deepseek"),
        "configs": db.get_all_llm_provider_configs(),
    }
