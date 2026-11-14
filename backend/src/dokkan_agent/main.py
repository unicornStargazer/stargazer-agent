"""进程入口：解析配置路径、装配应用、启动单 worker Uvicorn。"""

import argparse
from pathlib import Path

import uvicorn

from dokkan_agent.bootstrap.application import BACKEND_ROOT, create_app
from dokkan_agent.bootstrap.settings import ConfigurationError, LoadedSettings


def main() -> None:
    """支持 python -m dokkan_agent.main；实际监听参数只来自 JSON 文件。"""
    parser = argparse.ArgumentParser(description="Dokkan Agent Python 后端")
    parser.add_argument("--config", type=Path, help="配置文件；默认 config/stargazer-agent.json，相对路径以后端根为基准")
    parser.add_argument("--backend-root", "--project-root", dest="backend_root", type=Path, default=BACKEND_ROOT, help="后端根目录；配置与数据相对该目录解析，旧 --project-root 为同义参数")
    arguments = parser.parse_args()
    try:
        app = create_app(arguments.config, arguments.backend_root)
    except ConfigurationError as error:
        parser.exit(status=2, message=f"{error}\n")
    loaded: LoadedSettings = app.state.configuration
    uvicorn.run(app, host=loaded.settings.server.host, port=loaded.settings.server.port, workers=1)


if __name__ == "__main__":
    main()
