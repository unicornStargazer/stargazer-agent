"""把文件配置转成应用依赖；模型配置不向 Skill 目录或 HTTP 请求泄漏。"""

from dokkan_agent.application.conversation.profiles import ProfileCatalog
from dokkan_agent.application.conversation.service import ConversationService
from dokkan_agent.application.runtime.models import RunProfile
from dokkan_agent.application.runtime.runner import AgentRunner
from dokkan_agent.bootstrap.runtime import create_run_limits
from dokkan_agent.bootstrap.settings import ProfileSettings, Settings
from dokkan_agent.domain.conversation.ports import ConversationRepository
from dokkan_agent.interfaces.http.schemas import ProfileResponse
from dokkan_agent.interfaces.http.services import HttpServices


def create_http_services(
    settings: Settings, repository: ConversationRepository, runner: AgentRunner
) -> HttpServices:
    profiles = ProfileCatalog(
        tuple(_run_profile(profile) for profile in settings.agents.profiles),
        settings.agents.default_profile_id,
    )
    public = tuple(
        ProfileResponse(id=profile.id, name=profile.name, model=profile.model)
        for profile in settings.agents.profiles
    )
    return HttpServices(
        ConversationService(repository, runner, profiles, create_run_limits(settings.runtime)),
        public,
        next(profile for profile in public if profile.id == profiles.default.id),
    )


def _run_profile(profile: ProfileSettings) -> RunProfile:
    return RunProfile(
        profile.id,
        profile.model,
        profile.system_prompt,
        profile.history_limit,
        profile.supports_tools,
    )
