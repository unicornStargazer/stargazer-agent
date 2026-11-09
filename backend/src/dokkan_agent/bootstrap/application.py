"""Python 后端组合根；供命令行和调试器共用，不在模块导入时读取配置。"""

from pathlib import Path

from fastapi import FastAPI

from dokkan_agent.bootstrap.settings import load_settings
from dokkan_agent.interfaces.http.app import create_http_app

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def create_app(
    configuration_path: Path | None = None, project_root: Path = PROJECT_ROOT
) -> FastAPI:
    """校验指定文件并装配应用；不连接模型、领域数据服务或真实会话库。"""
    loaded = load_settings(project_root, configuration_path)
    app = create_http_app()
    app.state.configuration = loaded
    return app
