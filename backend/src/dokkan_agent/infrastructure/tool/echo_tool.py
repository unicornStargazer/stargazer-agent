"""无副作用的工具示例；仅在调试装配中显式加入，正式能力集合默认不含它。"""

from typing import Annotated

from pydantic import BaseModel, Field

from dokkan_agent.application.runtime.context import RunContext
from dokkan_agent.application.tool.function_tool import ExecutableTool, FunctionTool, ToolParameters


class EchoParameters(ToolParameters):
    text: Annotated[str, Field(min_length=1, max_length=4000)]


class EchoOutput(BaseModel):
    text: str


def create_echo_tool() -> ExecutableTool:
    """返回有输入/输出校验的示例；不发网络请求，不读写任何文件。"""

    async def echo(parameters: EchoParameters, context: RunContext) -> EchoOutput:
        return EchoOutput(text=parameters.text)

    return FunctionTool(
        name="echo_text",
        description="调试示例：原样返回有界文本。",
        parameters=EchoParameters,
        output=EchoOutput,
        handler=echo,
    )
