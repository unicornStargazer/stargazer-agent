"""只提供构建产物；真实路径检查阻止符号链接和编码路径逃逸，不回退 API 到页面。"""

from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse


def register_static_files(app: FastAPI, directory: Path) -> None:
    root = directory.resolve()

    @app.get("/{asset_path:path}", include_in_schema=False)
    async def static_file(request: Request, asset_path: str) -> FileResponse:
        scope = request.scope
        raw_path = scope.get("raw_path", b"")
        decoded_path = raw_path.decode("ascii", errors="replace")
        raw = unquote(decoded_path)
        normalized = raw.replace("\\", "/")
        parts = normalized.split("/")
        if ".." in parts or "\x00" in normalized:
            raise HTTPException(404)
        if asset_path == "api":
            raise HTTPException(404)
        is_api_path = asset_path.startswith("api/")
        if is_api_path or "\\" in asset_path:
            raise HTTPException(404)
        try:
            relative = root / (asset_path or "index.html")
            target = relative.resolve()
            is_relative = target.is_relative_to(root)
            if not is_relative:
                raise HTTPException(404)
            is_file = target.is_file()
            if not is_file:
                raise HTTPException(404)
        except (OSError, ValueError, RuntimeError):
            raise HTTPException(404) from None
        is_asset = asset_path.startswith("assets/")
        cache = "public, max-age=31536000, immutable" if is_asset else "no-cache"
        response = FileResponse(target, headers={"Cache-Control": cache})
        return response
