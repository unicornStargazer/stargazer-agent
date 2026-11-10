"""模型配置快照；不参与 Skill 的选择，也不按模型拆分会话历史。"""

from dokkan_agent.application.runtime.models import RunProfile
from dokkan_agent.domain.conversation.errors import UnknownProfileError


class ProfileCatalog:
    def __init__(self, profiles: tuple[RunProfile, ...], default_id: str) -> None:
        self.profiles = profiles
        self._by_id = {profile.id: profile for profile in profiles}
        self.default = self.select(default_id)

    def select(self, profile_id: str | None) -> RunProfile:
        profile = self._by_id.get(profile_id) if profile_id else self.default
        if profile is None:
            raise UnknownProfileError("模型配置不存在，请重新选择。")
        return profile
