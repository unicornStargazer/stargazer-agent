"""进程入口：解析配置路径、装配应用、启动单 worker Uvicorn。"""

import argparse
from pathlib import Path

import uvicorn

from dokkan_agent.bootstrap.application import PROJECT_ROOT, create_app
from dokkan_agent.bootstrap.settings import ConfigurationError, LoadedSettings


def main() -> None:
    """支持 python -m dokkan_agent.main；实际监听参数只来自 JSON 文件。"""
    parser = argparse.ArgumentParser(description="Dokkan Agent Python 后端")
    parser.add_argument("--config", type=Path, help="配置文件；相对路径以项目根为基准")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT, help="默认定位源码所在仓库；独立安装 wheel 时显式指定配置和数据的根目录")
    arguments = parser.parse_args()
    try:
        app = create_app(arguments.config, arguments.project_root)
    except ConfigurationError as error:
        parser.exit(status=2, message=f"{error}\n")
    loaded: LoadedSettings = app.state.configuration
    uvicorn.run(app, host=loaded.settings.server.host, port=loaded.settings.server.port, workers=1)


if __name__ == "__main__":
    main()
