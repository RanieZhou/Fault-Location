# -*- coding: utf-8 -*-
"""
web/app.py — FastAPI 主应用入口
负责：静态文件服务、API路由挂载、启动检查
"""
import os, sys
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

# 确保项目根目录在 sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

app = FastAPI(
    title="配网故障定位系统 API",
    description="10kV配电网智能故障定位Agent系统",
    version="1.0.0",
)

# CORS（开发时允许所有来源，生产时收紧）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================== 路由注册 ========================
from web.routers import fault, settings, agent as agent_router, auth as auth_router, custom_topology

app.include_router(fault.router,    prefix="/api/fault",    tags=["故障定位"])
app.include_router(settings.router, prefix="/api/settings", tags=["系统设置"])
app.include_router(agent_router.router, prefix="/api/agent", tags=["Agent"])
app.include_router(auth_router.router,  prefix="/api/auth",  tags=["认证"])
app.include_router(custom_topology.router, prefix="/api/custom-topology", tags=["自定义拓扑"])

# ======================== 登录鉴权 ========================
# 除了登录本身、健康检查、静态资源，其余所有页面和API都要求已登录。
# /static/ 整体放行：这些是纯前端源码文件（不含业务数据），登录页本身也需要
# 加载 style.css 才能正常显示，业务数据都走受保护的 /api/ 接口，不受影响。
_PUBLIC_PATHS = {"/login", "/api/auth/login", "/api/health", "/favicon.ico"}

@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if path in _PUBLIC_PATHS or path.startswith("/static/"):
        return await call_next(request)

    if not auth_router.is_valid_session(request.cookies.get("session")):
        if path.startswith("/api/"):
            return JSONResponse({"error": "未登录", "code": "unauthorized"}, status_code=401)
        return RedirectResponse("/login")

    return await call_next(request)

# ======================== 启动初始化 ========================
@app.on_event("startup")
async def _init_db():
    from core.db import init_db
    init_db()

# ======================== 健康检查 ========================
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}

# ======================== 静态文件 ========================
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))

@app.get("/login")
async def login_page():
    return FileResponse(str(STATIC_DIR / "login.html"))

@app.get("/{full_path:path}")
async def catch_all(full_path: str):
    """SPA路由回退：非/api/和/static/的路径都返回index.html"""
    if full_path.startswith("api/") or full_path.startswith("static/"):
        return JSONResponse({"error": "Not found"}, status_code=404)
    return FileResponse(str(STATIC_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    uvicorn.run(
        "web.app:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=True,
        reload_dirs=[str(ROOT)],
    )
