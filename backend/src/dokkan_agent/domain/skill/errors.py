"""Skill 部署失败与运行失败；错误描述不包含文件正文。"""

from dokkan_agent.domain.tool.models import ToolErrorCode


class SkillConfigurationError(ValueError):
    """部署格式或目录无效；可在启动时附加本地文件位置便于修正。"""


class SkillAccessError(RuntimeError):
    """可反馈模型的安全错误；路径越界、未激活和版本变化各有稳定代码。"""

    def __init__(self, code: ToolErrorCode, message: str) -> None:
        RuntimeError.__init__(self, message)
        self.code = code
