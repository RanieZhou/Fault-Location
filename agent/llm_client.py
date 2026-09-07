"""
agent/llm_client.py — 多厂商统一LLM客户端
支持：DeepSeek、通义千问（Qwen）、OpenAI
所有厂商均兼容 OpenAI Chat Completions 接口
"""
from __future__ import annotations
import os
from typing import Optional
import openai

from core.config import settings


# ── 运行时配置存储（由 settings 路由写入，优先级高于 .env）────────
_runtime_cfg: dict[str, dict] = {}


def set_provider_config(provider: str, api_key: str, base_url: str, model: str):
    """由 /api/settings/llm 路由调用，动态更新配置"""
    _runtime_cfg[provider] = {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }


# ── 提供商默认值 ──────────────────────────────────────────────

_DEFAULTS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-max",
        "env_key": "QWEN_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "env_key": "OPENAI_API_KEY",
    },
    "custom": {
        "base_url": "",
        "model": "",
        "env_key": "CUSTOM_API_KEY",
    },
}

KNOWN_PROVIDERS: frozenset[str] = frozenset(_DEFAULTS.keys())


def resolve_config(provider: str) -> tuple[str, str, str]:
    """
    解析 (api_key, base_url, model)，优先级：
    runtime_cfg（本次进程内"测试连接"等场景显式传入的临时值）
    > SQLite 已保存配置（用户在网页"系统设置"里保存过的，权威、跨重启持久化）
    > .env / 环境变量（部署时的初始引导值，仅当SQLite里还没有这个provider的记录时生效）
    > 硬编码默认值
    """
    prov = provider.lower()
    defaults = _DEFAULTS.get(prov, _DEFAULTS["deepseek"])

    # 运行时配置（前端配置页写入）
    rt = _runtime_cfg.get(prov, {})

    # SQLite 已保存配置
    from core import db
    saved = db.get_llm_provider_config(prov) or {}

    # pydantic-settings 配置（.env 文件）——仅作初始引导，SQLite有记录时不会用到
    if prov == "deepseek":
        env_key = settings.deepseek_api_key
        env_url = settings.deepseek_base_url
        env_model = settings.deepseek_model
    elif prov == "qwen":
        env_key = settings.qwen_api_key
        env_url = settings.qwen_base_url
        env_model = settings.qwen_model
    elif prov == "openai":
        env_key = settings.openai_api_key
        env_url = settings.openai_base_url
        env_model = settings.openai_model
    elif prov == "custom":
        env_key = settings.custom_api_key
        env_url = settings.custom_base_url
        env_model = settings.custom_model
    else:
        env_key = env_url = env_model = ""

    api_key  = rt.get("api_key")  or saved.get("api_key")  or env_key  or os.getenv(defaults["env_key"], "")
    base_url = rt.get("base_url") or saved.get("base_url") or env_url  or defaults["base_url"]
    model    = rt.get("model")    or saved.get("model")    or env_model or defaults["model"]

    return api_key, base_url, model


def get_client(provider: str) -> tuple[openai.AsyncOpenAI, str, str]:
    """
    获取 AsyncOpenAI 客户端实例、model、provider名称。
    返回 (client, model, provider)
    """
    api_key, base_url, model = resolve_config(provider)
    if not api_key:
        raise ValueError(f"未配置 {provider} 的 API Key。请在系统设置中填写或在 .env 文件中配置。")

    client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=60.0)
    return client, model, provider


async def list_models(api_key: str, base_url: str) -> dict:
    """
    直接用给定的 api_key/base_url 拉取模型列表（不经过 resolve_config）——
    这个操作通常发生在用户填完表单、还没点"保存配置"的时候，此时应该用
    输入框里当前的值去试探，而不是已保存的运行时/环境变量配置。
    几乎所有 OpenAI 兼容服务都实现了标准的 GET /models 端点，openai SDK
    的 client.models.list() 就是对它的封装，不需要自己拼 HTTP 请求。
    """
    if not api_key or not base_url:
        return {"ok": False, "message": "请先填写 API Key 和 Base URL", "models": []}
    try:
        client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=15.0)
        resp = await client.models.list()
        model_ids = sorted(m.id for m in resp.data)
        if not model_ids:
            return {"ok": False, "message": "该服务返回了空的模型列表", "models": []}
        return {"ok": True, "models": model_ids}
    except Exception as e:
        return {"ok": False, "message": f"获取失败：{str(e)[:200]}", "models": []}


async def test_connection(provider: str) -> dict:
    """测试LLM连接是否正常"""
    try:
        client, model, _ = get_client(provider)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "你好，请回复'连接正常'"}],
            max_tokens=20,
            temperature=0,
        )
        content = resp.choices[0].message.content or ""
        return {"ok": True, "message": f"连接成功，模型响应：{content[:50]}", "provider": provider, "model": model}
    except ValueError as e:
        return {"ok": False, "message": str(e), "provider": provider, "model": ""}
    except Exception as e:
        return {"ok": False, "message": f"连接失败：{str(e)[:200]}", "provider": provider, "model": ""}
