"""配置文件和启动契约，重点验证路径、敏感信息及未就绪状态。"""

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from dokkan_agent.bootstrap.application import create_app
from dokkan_agent.bootstrap.settings import ConfigurationError, load_settings
from dokkan_agent.main import main


def write_configuration(root: Path, configuration: dict[str, Any]) -> Path:
    path = root / "settings.json"
    path.write_text(json.dumps(configuration), encoding="utf-8")
    return path


def test_paths_are_rooted_at_project_not_cwd(
    tmp_path: Path, configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    configuration.pop("runtime")
    path = write_configuration(tmp_path, configuration)
    child = tmp_path / "unrelated"
    child.mkdir()
    monkeypatch.chdir(child)
    loaded = load_settings(tmp_path, path)
    assert loaded.database_path == tmp_path / "backend/data/development.sqlite"
    assert loaded.skills_directory == tmp_path / "backend/examples/skills"
    assert loaded.settings.runtime.max_model_calls == 12
    assert loaded.settings.agents.profiles[0].history_limit == 12
    assert not loaded.database_path.exists()


@pytest.mark.parametrize("invalid_value", [0, True, "3001", 65536])
def test_invalid_port_is_rejected_without_leaking_key(
    tmp_path: Path, configuration: dict[str, Any], invalid_value: object
) -> None:
    configuration["provider"]["apiKey"] = "test-secret-not-for-output"
    configuration["server"]["port"] = invalid_value
    path = write_configuration(tmp_path, configuration)
    with pytest.raises(ConfigurationError) as captured:
        load_settings(tmp_path, path)
    assert "server.port" in str(captured.value)
    assert "test-secret-not-for-output" not in str(captured.value)


@pytest.mark.parametrize("problem", ["duplicate", "unknown_default", "skill_binding", "budget"])
def test_cross_field_and_runtime_rules(
    tmp_path: Path, configuration: dict[str, Any], problem: str
) -> None:
    if problem == "duplicate":
        configuration["agents"]["profiles"] *= 2
    elif problem == "unknown_default":
        configuration["agents"]["defaultProfileId"] = "missing"
    elif problem == "skill_binding":
        configuration["agents"]["profiles"][0]["skillIds"] = ["business"]
    else:
        configuration["runtime"]["maxToolExecutions"] = 0
    path = write_configuration(tmp_path, configuration)
    with pytest.raises(ConfigurationError):
        load_settings(tmp_path, path)


async def test_startup_migrates_only_explicit_temp_database_without_model_request(
    tmp_path: Path, configuration: dict[str, Any]
) -> None:
    configuration.pop("skillsDirectory")
    path = write_configuration(tmp_path, configuration)
    app = create_app(path, tmp_path)
    assert not (tmp_path / "backend/data").exists()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/health/live")
            assert response.json() == {"alive": True}
            response = await client.get("/health/ready")
            assert response.status_code == 200
            assert response.json()["ready"] is True
            assert (await client.get("/api/status")).json()["conversationStorage"] == "sqlite"
            assert "apiKey" not in (await client.get("/openapi.json")).text
    assert app.state.started is False
    assert (tmp_path / "backend/data/development.sqlite").is_file()


def test_malformed_or_missing_configuration_is_sanitized(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"apiKey":"secret-value", broken}', encoding="utf-8")
    with pytest.raises(ConfigurationError, match="有效 JSON") as captured:
        load_settings(tmp_path, path)
    assert "secret-value" not in str(captured.value)
    path.unlink()
    with pytest.raises(ConfigurationError, match="无法读取"):
        load_settings(tmp_path, path)


def test_omitted_history_limit_preserves_legacy_unlimited_semantics(
    tmp_path: Path, configuration: dict[str, Any]
) -> None:
    configuration["agents"]["profiles"][0].pop("historyLimit")
    path = write_configuration(tmp_path, configuration)
    loaded = load_settings(tmp_path, path)
    assert loaded.settings.agents.profiles[0].history_limit is None
    assert "replace-with-local-key" not in repr(loaded)
    configuration["agents"]["profiles"][0]["historyLimit"] = None
    path = write_configuration(tmp_path, configuration)
    with pytest.raises(ConfigurationError):
        load_settings(tmp_path, path)


def test_cli_explicit_project_root_uses_file_host_and_port(
    tmp_path: Path, configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    write_configuration(tmp_path, configuration)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dokkan-agent",
            "--project-root",
            str(tmp_path),
            "--config",
            "settings.json",
        ],
    )
    with patch("dokkan_agent.main.uvicorn.run", autospec=True) as server:
        main()
    server.assert_called_once()
    assert server.call_args.kwargs == {"host": "127.0.0.1", "port": 3001, "workers": 1}
    assert server.call_args.args[0].state.configuration.project_root == tmp_path
