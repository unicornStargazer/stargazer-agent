"""现有 Web 的 JSON DTO；camelCase 只停留在协议层，不传入领域模型。"""

from typing import Annotated, Literal, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

from dokkan_agent.domain.conversation.models import AssistantReply, ConversationCommand

# 与现有 JavaScript trim 一致，保留 UTF-16 长度限制，避免迁移后 emoji 边界变化。
JS_WHITESPACE = (
    "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)
type Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
]
type TokenCount = Annotated[int, Field(ge=0, le=9_007_199_254_740_991)]


class HttpModel(BaseModel):
    """字段使用既有别名；忽略额外输入与 TS 行为一致，已知字段保持严格类型。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, strict=True, frozen=True, hide_input_in_errors=True)


class SessionQuery(HttpModel):
    session_id: Identifier

    @field_validator("session_id", mode="before")
    @classmethod
    def trim_identifier(cls, value: object) -> object:
        is_text = isinstance(value, str)
        if is_text:
            text = cast(str, value)
            stripped = text.strip(JS_WHITESPACE)
            return stripped
        return value


class ChatRequest(SessionQuery):
    """最大正文长度为裁剪后的 16000 UTF-16 单元；requestId 是必填去重标识。"""

    request_id: Identifier
    message: str
    profile_id: Identifier | None = None

    @model_validator(mode="after")
    def reject_explicit_null_profile(self) -> Self:
        if "profile_id" in self.model_fields_set and self.profile_id is None:
            raise ValueError("profileId 必须省略或提供合法 ID，不能为 null")
        return self

    @field_validator("request_id", "profile_id", mode="before")
    @classmethod
    def trim_optional_identifier(cls, value: object) -> object:
        is_text = isinstance(value, str)
        if is_text:
            text = cast(str, value)
            stripped = text.strip(JS_WHITESPACE)
            return stripped
        return value

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        content = value.strip(JS_WHITESPACE)
        if not content:
            raise ValueError("message 不能为空")
        encoded = content.encode("utf-16-le", errors="surrogatepass")
        length = len(encoded)
        if length // 2 > 16_000:
            raise ValueError("message 超出长度限制")
        return content

    def to_command(self) -> ConversationCommand:
        """转换后领域层不需要知道 Pydantic 和 camelCase。"""
        command = ConversationCommand(self.session_id, self.request_id, self.message, self.profile_id)
        return command


class TokenUsageResponse(HttpModel):
    """未知计数序列化时省略；reasoningTokens 不能再次加到 totalTokens 中。"""

    input_tokens: TokenCount | None = None
    output_tokens: TokenCount | None = None
    reasoning_tokens: TokenCount | None = None
    total_tokens: TokenCount | None = None


class MessageResponse(HttpModel):
    """历史只返回用户/助手；reasoning 与 usage 只允许由服务端附加给助手。"""

    role: Literal["user", "assistant"]
    content: str
    reasoning: str | None = None
    usage: TokenUsageResponse | None = None

    @model_validator(mode="after")
    def restrict_assistant_metadata(self) -> Self:
        if self.role == "user" and (self.reasoning is not None or self.usage is not None):
            raise ValueError("用户消息不能携带模型元数据")
        return self

    @classmethod
    def from_reply(cls, reply: AssistantReply) -> Self:
        """显式转码领域结果；未知字段保持 None，输出时统一排除。"""
        usage = reply.usage
        usage_response = None
        if usage:
            usage_response = TokenUsageResponse(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, reasoning_tokens=usage.reasoning_tokens, total_tokens=usage.total_tokens)
        response = cls(role="assistant", content=reply.content, reasoning=reply.reasoning, usage=usage_response)
        return response


class ChatResponse(HttpModel):
    message: MessageResponse


class HistoryResponse(HttpModel):
    messages: list[MessageResponse]


class DeleteHistoryResponse(HttpModel):
    deleted: Literal[True] = True


class ProfileResponse(HttpModel):
    """只公开模型 ID、显示名称和模型名；无密钥、系统提示或 Skill 绑定。"""

    id: str
    name: str
    model: str


class ProfilesResponse(HttpModel):
    profiles: list[ProfileResponse]


class StatusResponse(HttpModel):
    ready: bool
    model: str
    conversation_storage: Literal["sqlite", "memory"]
    default_profile: ProfileResponse | None = None
