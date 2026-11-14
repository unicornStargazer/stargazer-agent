"""JSON 配置边界；只读取指定文件，路径始终相对项目根，不读取环境变量。"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

type NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
type ProfileId = Annotated[NonEmptyText, StringConstraints(pattern=r"^[a-zA-Z0-9_-]+$")]
type PositiveSafeInt = Annotated[int, Field(gt=0, le=9_007_199_254_740_991)]


class FileSettings(BaseModel):
    """配置使用 camelCase；拒绝拼错字段，避免配置看似生效但实际被忽略。"""

    model_config = ConfigDict(alias_generator=to_camel, extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class ServerSettings(FileSettings):
    """监听配置；开发阶段通过独立文件使用 3001，避免占用旧服务端口。"""

    host: NonEmptyText
    port: Annotated[int, Field(ge=1, le=65_535)]


class StorageSettings(FileSettings):
    """databasePath 为文件路径；只在启动生命周期中打开和迁移。"""

    database_path: NonEmptyText


class ProviderSettings(FileSettings):
    """Provider 凭据仅供服务端使用；SecretStr 防止 repr 意外暴露密钥。"""

    api_key: SecretStr = Field(repr=False)
    base_url: NonEmptyText
    include_stream_usage: bool
    connect_timeout_seconds: Annotated[int, Field(ge=1, le=120)] = 10
    read_timeout_seconds: Annotated[int, Field(ge=1, le=600)] = 60
    max_attempts: Annotated[int, Field(ge=1, le=3)] = 2

    @field_validator("api_key")
    @classmethod
    def require_api_key(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        stripped = secret.strip()
        if not stripped:
            raise ValueError("apiKey 不能为空")
        validated = SecretStr(stripped)
        return validated

    @field_validator("base_url")
    @classmethod
    def require_http_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("baseUrl 必须是 HTTP(S) 地址")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("baseUrl 不能包含凭据、查询参数或片段")
        normalized = value.rstrip("/")
        return normalized


class ProfileSettings(FileSettings):
    """模型选择参数；historyLimit 为消息条数，省略保留旧版无限制语义。"""

    id: ProfileId
    name: NonEmptyText
    model: NonEmptyText
    system_prompt: NonEmptyText | None = None
    history_limit: PositiveSafeInt | None = None
    supports_tools: bool = True

    @field_validator("history_limit", "system_prompt", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        # 默认值可以表示未提供；JSON 明确给 null 与旧 TS 一样视为配置错误。
        if value is None:
            raise ValueError("可选字段应省略，不能为 null")
        return value


class AgentSettings(FileSettings):
    """全局模型清单；默认 ID 必须唯一引用一个已配置模型。"""

    default_profile_id: ProfileId
    profiles: Annotated[list[ProfileSettings], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_profile_references(self) -> Self:
        identifiers = [profile.id for profile in self.profiles]
        unique_identifiers = set(identifiers)
        unique_count = len(unique_identifiers)
        identifier_count = len(identifiers)
        if unique_count != identifier_count:
            raise ValueError("profiles 中的 id 不能重复")
        if self.default_profile_id not in identifiers:
            raise ValueError("defaultProfileId 必须引用 profiles 中的配置")
        return self


class RuntimeSettings(FileSettings):
    """每条用户消息的独立运行上限；字符预算按 Python Unicode 码点计算。"""

    max_model_calls: PositiveSafeInt = 12
    max_tool_executions: PositiveSafeInt = 24
    max_activated_skills: PositiveSafeInt = 4
    max_resource_reads: PositiveSafeInt = 8
    max_resource_characters: PositiveSafeInt = 16_000
    max_disclosure_characters: PositiveSafeInt = 64_000
    max_context_characters: PositiveSafeInt = 128_000


class Settings(FileSettings):
    """兼容既有配置层级；runtime 可省略，并与模型 Profile 独立。"""

    server: ServerSettings
    storage: StorageSettings
    provider: ProviderSettings
    agents: AgentSettings
    skills_directory: NonEmptyText | None = None
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)


@dataclass(frozen=True, slots=True)
class LoadedSettings:
    """带明确路径基准的配置快照；路径解析不创建目录或访问真实数据库。"""

    settings: Settings
    backend_root: Path
    configuration_path: Path

    @property
    def static_directory(self) -> Path:
        """前端与 backend 为同级部署目录；不随配置文件所在目录变化。"""
        path = self.backend_root.parent / "web/dist"
        return path

    def resolve_backend_path(self, value: str) -> Path:
        """绝对路径保持语义，相对路径锚定后端根而非启动目录或配置目录。"""
        path = self.backend_root / value
        resolved = path.resolve()
        return resolved

    @property
    def database_path(self) -> Path:
        path = self.resolve_backend_path(self.settings.storage.database_path)
        return path

    @property
    def skills_directory(self) -> Path | None:
        value = self.settings.skills_directory
        if not value:
            return None
        path = self.resolve_backend_path(value)
        return path


class ConfigurationError(ValueError):
    """启动配置无效；消息只含字段位置和错误类别，不含配置原文或密钥。"""


def load_settings(backend_root: Path, configuration_path: Path | None = None) -> LoadedSettings:
    """以后端根读取配置，不回退旧配置；失败抛脱敏异常，无数据库或网络副作用。"""
    root = backend_root.resolve()
    if configuration_path is None:
        configuration_path = Path("config/stargazer-agent.json")
    requested_path = root / configuration_path
    path = requested_path.resolve()
    try:
        content = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raise ConfigurationError(f"无法读取 UTF-8 配置文件：{path}") from None
    try:
        payload = json.loads(content)
    except (ValueError, RecursionError):
        raise ConfigurationError(f"配置文件不是有效 JSON：{path}") from None
    try:
        settings = Settings.model_validate(payload)
    except ValidationError as error:
        # 不使用 str(error)：跨字段校验错误可能携带整个含密钥的输入对象。
        locations: list[str] = []
        errors = error.errors(include_input=False, include_context=False)
        for item in errors:
            components = map(str, item["loc"])
            location = ".".join(components)
            locations.append(f"{location or '配置根节点'} ({item['type']})")
        description = "; ".join(locations)
        raise ConfigurationError("配置校验失败：" + description) from None
    loaded = LoadedSettings(settings, root, path)
    return loaded
