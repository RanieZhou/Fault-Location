# -*- coding: utf-8 -*-
"""
web/routers/auth.py — 登录认证

单账号、内存态session，不用JWT/数据库：token是32字节的高强度随机数
（secrets.token_urlsafe(32)，约256位熵，不可猜测/伪造），服务端维护一个
"当前有效token -> 过期时间"的字典即可判断合法性，不需要额外的签名密钥。
进程重启会清空所有session（和 settings.py 里 _llm_config 的持久化策略一致），
重新登录一次即可，符合demo/内网单机部署场景。
"""
from __future__ import annotations
import secrets
import time
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.config import settings

router = APIRouter()

_sessions: dict[str, float] = {}   # token -> 过期时间（unix秒）
SESSION_TTL_SECONDS = 24 * 3600    # 24小时


class LoginRequest(BaseModel):
    username: str
    password: str


def is_valid_session(token: str | None) -> bool:
    if not token or token not in _sessions:
        return False
    if _sessions[token] < time.time():
        del _sessions[token]
        return False
    return True


@router.post("/login")
async def login(req: LoginRequest, response: Response):
    if req.username == settings.admin_username and req.password == settings.admin_password:
        token = secrets.token_urlsafe(32)
        _sessions[token] = time.time() + SESSION_TTL_SECONDS
        response.set_cookie(
            "session", token,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            samesite="lax",
        )
        return {"ok": True}
    return JSONResponse({"ok": False, "message": "用户名或密码错误"}, status_code=401)


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session")
    if token in _sessions:
        del _sessions[token]
    response.delete_cookie("session")
    return {"ok": True}


@router.get("/status")
async def status(request: Request):
    return {"logged_in": is_valid_session(request.cookies.get("session"))}
