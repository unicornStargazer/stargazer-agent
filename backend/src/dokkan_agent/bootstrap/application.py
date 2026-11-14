"""Python 后端组合根；供命令行和调试器共用，不在模块导入时读取配置。"""

from pathlib import Path

import httpx
from fastapi import FastAPI

from dokkan_agent.bootstrap.lifespan import create_lifespan
from dokkan_agent.bootstrap.settings import load_settings
from dokkan_agent.interfaces.http.app import create_http_app

MODULE_PATH = Path(__file__)
RESOLVED_MODULE_PATH = MODULE_PATH.resolve()
PROJECT_ROOT = RESOLVED_MODULE_PATH.parents[4]


def create_app(configuration_path: Path | None = None, project_root: Path = PROJECT_ROOT, *, model_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """校验文件并装配应用；工厂本身无存储/网络副作用，生命周期才迁移指定库。"""
    loaded = load_settings(project_root, configuration_path)
    lifespan = create_lifespan(loaded, model_transport)
    app = create_http_app(lifespan, loaded.project_root / "web/dist")
    app.state.configuration = loaded
    return app
