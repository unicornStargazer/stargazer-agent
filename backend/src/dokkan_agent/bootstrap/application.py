"""Python 后端组合根；供命令行和调试器共用，不在模块导入时读取配置。"""

from pathlib import Path

import httpx
from fastapi import FastAPI

from dokkan_agent.bootstrap.lifespan import create_lifespan
from dokkan_agent.bootstrap.settings import load_settings
from dokkan_agent.interfaces.http.app import create_http_app

MODULE_PATH = Path(__file__)
RESOLVED_MODULE_PATH = MODULE_PATH.resolve()
BACKEND_ROOT = RESOLVED_MODULE_PATH.parents[3]


def create_app(configuration_path: Path | None = None, backend_root: Path = BACKEND_ROOT, *, model_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """以后端根解析配置与数据；前端构建目录独立定位，工厂不产生 IO 写入。"""
    loaded = load_settings(backend_root, configuration_path)
    lifespan = create_lifespan(loaded, model_transport)
    app = create_http_app(lifespan, loaded.static_directory)
    app.state.configuration = loaded
    return app
