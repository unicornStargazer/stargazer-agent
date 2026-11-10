"""Python HTTP 全链路兼容测试：临时配置/SQLite，HTTPX 模拟上游，不接真实服务。"""

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from starlette.types import Message

from dokkan_agent.bootstrap.application import create_app


def frame(payload: object) -> bytes:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return f"data: {text}\n\n".encode()


def completion(content: str = "回答", finish: str = "stop") -> bytes:
    return b"".join(
        [
            frame(
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"reasoning_content": "公开摘要"},
                            "finish_reason": None,
                        }
                    ]
                }
            ),
            frame(
                {"choices": [{"index": 0, "delta": {"content": content}, "finish_reason": finish}]}
            ),
            frame(
                {
                    "choices": [],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
                }
            ),
            frame("[DONE]"),
        ]
    )


def make_app(
    tmp_path: Path,
    configuration: dict[str, Any],
    handler: Callable[[httpx.Request], httpx.Response],
) -> FastAPI:
    configuration.pop("skillsDirectory", None)
    configuration["storage"]["databasePath"] = "test.sqlite"
    configuration["agents"]["profiles"] = [
        {"id": "a", "name": "模型 A", "model": "model-a", "historyLimit": 12},
        {"id": "b", "name": "模型 B", "model": "model-b", "historyLimit": 12},
    ]
    configuration["agents"]["defaultProfileId"] = "a"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(configuration), encoding="utf-8")
    return create_app(path, tmp_path, model_transport=httpx.MockTransport(handler))


async def test_stream_persists_metadata_replays_after_restart_and_switches_model(
    tmp_path: Path, configuration: dict[str, Any]
) -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=completion()
        )

    body = {"sessionId": "same", "requestId": "r1", "message": "你好", "profileId": "a"}
    for restart in (False, True):
        app = make_app(tmp_path, configuration, handler)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/api/chat/stream", json=body)
                assert response.status_code == 200
                assert response.headers["cache-control"] == "no-store"
                assert response.headers["x-content-type-options"] == "nosniff"
                assert response.text.count("event: done") == 1
                assert "event: error" not in response.text
                assert '"totalTokens":5' in response.text
                assert "公开摘要" in response.text
                assert len(requests) == 1
                history = (await client.get("/api/history?sessionId=same")).json()["messages"]
                assert history == [
                    {"role": "user", "content": "你好"},
                    {
                        "role": "assistant",
                        "content": "回答",
                        "reasoning": "公开摘要",
                        "usage": {"inputTokens": 2, "outputTokens": 3, "totalTokens": 5},
                    },
                ]
                if restart:
                    switched = await client.post(
                        "/api/chat", json={**body, "requestId": "r2", "profileId": "b"}
                    )
                    assert switched.status_code == 200
                    continued = await client.post(
                        "/api/chat",
                        json={"sessionId": "same", "requestId": "r3", "message": "继续"},
                    )
                    assert continued.status_code == 200
                    assert [request["model"] for request in requests] == [
                        "model-a",
                        "model-b",
                        "model-b",
                    ]
                    assert (
                        len((await client.get("/api/history?sessionId=same")).json()["messages"])
                        == 6
                    )
                    assert [message["role"] for message in requests[1]["messages"]][-3:] == [
                        "user",
                        "assistant",
                        "user",
                    ]
                    assert (await client.delete("/api/history?sessionId=same")).json() == {
                        "deleted": True
                    }


@pytest.mark.parametrize(
    ("payload", "headers", "status", "code"),
    [
        (b"{}", {"content-type": "text/plain"}, 415, "UNSUPPORTED_MEDIA_TYPE"),
        (b"{", {"content-type": "application/json"}, 400, "INVALID_REQUEST"),
        (b"[]", {"content-type": "application/json"}, 400, "INVALID_REQUEST"),
        (b"x" * 32769, {"content-type": "application/json"}, 413, "REQUEST_TOO_LARGE"),
        (
            b'{"sessionId":"s","requestId":"r","message":"hello","profileId":null}',
            {"content-type": "application/json"},
            400,
            "INVALID_REQUEST",
        ),
        (
            b'{"sessionId":"s","requestId":"r","message":"hello","profileId":"unknown"}',
            {"content-type": "application/json"},
            400,
            "UNKNOWN_PROFILE",
        ),
    ],
)
async def test_preflight_errors_are_http_and_sanitized(
    tmp_path: Path,
    configuration: dict[str, Any],
    payload: bytes,
    headers: dict[str, str],
    status: int,
    code: str,
) -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError("参数失败不能连接模型")

    app = make_app(tmp_path, configuration, forbidden)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/chat/stream", content=payload, headers=headers)
            assert response.status_code == status
            assert response.json()["error"]["code"] == code
            assert "apiKey" not in response.text
            assert "event:" not in response.text


async def test_commit_failure_after_content_emits_error_without_done_or_history(
    tmp_path: Path, configuration: dict[str, Any]
) -> None:
    app = make_app(
        tmp_path,
        configuration,
        lambda _: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=completion()
        ),
    )
    async with app.router.lifespan_context(app):
        with sqlite3.connect(tmp_path / "test.sqlite") as connection:
            connection.execute(
                "CREATE TRIGGER fail_commit BEFORE INSERT ON conversation_messages "
                "WHEN NEW.role='assistant' BEGIN SELECT RAISE(ABORT, 'test'); END"
            )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/chat/stream", json={"sessionId": "s", "requestId": "r", "message": "你好"}
            )
            assert "event: chunk" in response.text
            assert "CONVERSATION_STORAGE_UNAVAILABLE" in response.text
            assert "event: done" not in response.text
            assert response.text.count("event: error") == 1
            assert (await client.get("/api/history?sessionId=s")).json() == {"messages": []}


async def test_tool_loop_keeps_reasoning_usage_and_all_visible_content(
    tmp_path: Path, configuration: dict[str, Any], skill_directory: Path
) -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            result = completion("先分析", "tool_calls")
            tool = frame(
                {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-a",
                                        "type": "function",
                                        "function": {
                                            "name": "activate_skill",
                                            "arguments": '{"name":"analysis-test"}',
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ]
                }
            )
            result = tool + result
        else:
            assert payload["messages"][-1]["role"] == "tool"
            assert payload["messages"][-1]["tool_call_id"] == "call-a"
            assert "ANALYSIS_BODY" in payload["messages"][-1]["content"]
            result = completion("最终回答")
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=result)

    app = make_app(tmp_path, configuration, handler)
    # make_app 默认不加载 Skill；本用例显式指定测试目录后重建组合根。
    path = tmp_path / "config.json"
    settings = json.loads(path.read_text(encoding="utf-8"))
    settings["skillsDirectory"] = str(skill_directory)
    path.write_text(json.dumps(settings), encoding="utf-8")
    app = create_app(path, tmp_path, model_transport=httpx.MockTransport(handler))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/chat/stream", json={"sessionId": "s", "requestId": "r", "message": "分析"}
            )
            assert "event: done" in response.text, response.text
            assert len(requests) == 2
            saved = (await client.get("/api/history?sessionId=s")).json()["messages"][-1]
            assert saved["content"] == "先分析最终回答"
            assert saved["reasoning"] == "公开摘要公开摘要"
            assert saved["usage"] == {"inputTokens": 4, "outputTokens": 6, "totalTokens": 10}
            assert "ANALYSIS_BODY" not in json.dumps(requests[0], ensure_ascii=False)


async def test_static_files_cannot_escape_and_api_never_returns_html(
    tmp_path: Path, configuration: dict[str, Any]
) -> None:
    public = tmp_path / "web/dist"
    (public / "assets").mkdir(parents=True)
    (public / "index.html").write_text("<html>test</html>", encoding="utf-8")
    (public / "assets/app.js").write_text("export {};", encoding="utf-8")
    app = make_app(tmp_path, configuration, lambda _: httpx.Response(500))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/")).status_code == 200
            assert "immutable" in (await client.get("/assets/app.js")).headers["cache-control"]
            for path in (
                "/api/missing",
                "/%2e%2e/config.json",
                "/C:/Windows/win.ini",
                "/..%5cconfig.json",
            ):
                assert (await client.get(path)).status_code == 404
            assert (await client.get("/api/profiles")).json() == {
                "profiles": [
                    {"id": "a", "name": "模型 A", "model": "model-a"},
                    {"id": "b", "name": "模型 B", "model": "model-b"},
                ]
            }


@pytest.mark.parametrize("route", ["/api/chat/stream", "/api/chat"])
async def test_asgi_disconnect_cancels_upstream_and_releases_session(
    tmp_path: Path,
    configuration: dict[str, Any],
    route: str,
) -> None:
    entered = asyncio.Event()
    closed = asyncio.Event()

    class BlockingStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield frame({"choices": [{"delta": {"content": "partial"}, "finish_reason": None}]})
            entered.set()
            await asyncio.Event().wait()

        async def aclose(self) -> None:
            closed.set()

    app = make_app(
        tmp_path,
        configuration,
        lambda _: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=BlockingStream()
        ),
    )
    body = json.dumps({"sessionId": "s", "requestId": "r", "message": "你好"}).encode()
    sent_body = False
    sent: list[Message] = []

    async def receive() -> Message:
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": body, "more_body": False}
        await entered.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": route,
        "raw_path": route.encode(),
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 3001),
    }
    async with app.router.lifespan_context(app):
        async with asyncio.timeout(5):
            if route == "/api/chat":
                with pytest.raises(asyncio.CancelledError):
                    await app(scope, receive, send)
            else:
                await app(scope, receive, send)
        assert closed.is_set()
        service = app.state.services.conversations
        assert service.locks._entries == {}
        assert await service.history("s") == ()
        with sqlite3.connect(tmp_path / "test.sqlite") as connection:
            assert connection.execute("SELECT status FROM agent_requests").fetchone() == (
                "interrupted",
            )
