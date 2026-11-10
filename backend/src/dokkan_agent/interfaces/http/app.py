"""FastAPI 工厂；资源生命周期由组合根传入，接口层不连接数据库或模型。"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.types import Lifespan

from dokkan_agent.interfaces.http.error_mapper import ERROR_MAPPINGS, ApiError, handle_error
from dokkan_agent.interfaces.http.routes import router
from dokkan_agent.interfaces.http.security_headers import SecurityHeadersMiddleware
from dokkan_agent.interfaces.http.static_files import register_static_files


def create_http_app(lifespan: Lifespan[FastAPI], static_directory: Path) -> FastAPI:
    app = FastAPI(title="Dokkan Agent", version="0.1.0", lifespan=lifespan)
    app.state.started = False
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_exception_handler(ApiError, handle_error)
    app.add_exception_handler(Exception, handle_error)
    for error_type, _, _, _ in ERROR_MAPPINGS:
        app.add_exception_handler(error_type, handle_error)
    app.include_router(router)

    @app.get("/health/live")
    async def liveness(request: Request) -> dict[str, bool]:
        return {"alive": bool(request.app.state.started)}

    @app.get("/health/ready")
    async def readiness(request: Request) -> JSONResponse:
        # 就绪表示启动校验/迁移完成，不代表远程模型实时可用；不发送付费探测。
        ready = bool(request.app.state.started)
        return JSONResponse(status_code=200 if ready else 503, content={"ready": ready})

    register_static_files(app, static_directory)
    return app
