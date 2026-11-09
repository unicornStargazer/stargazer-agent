"""FastAPI 工厂；当前只暴露工程存活检查，聊天路由在运行内核完成后接入。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse


@asynccontextmanager
async def application_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """显式标记进程生命周期；本阶段不打开数据库、不发起模型请求。"""
    app.state.started = True
    try:
        yield
    finally:
        app.state.started = False


def create_http_app() -> FastAPI:
    """创建可测试的独立 HTTP 应用；就绪状态不得冒充完整 Agent 已可用。"""
    app = FastAPI(title="Dokkan Agent", version="0.1.0", lifespan=application_lifespan)

    @app.get("/health/live")
    async def liveness() -> dict[str, bool]:
        return {"alive": bool(app.state.started)}

    @app.get("/health/ready")
    async def readiness() -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"ready": False, "stage": "bootstrap", "reason": "Agent 运行内核尚未接入。"},
        )

    return app
