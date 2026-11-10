"""只提供构建产物；真实路径检查阻止符号链接和编码路径逃逸，不回退 API 到页面。"""

from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse


def register_static_files(app: FastAPI, directory: Path) -> None:
    root = directory.resolve()

    @app.get("/{asset_path:path}", include_in_schema=False)
    async def static_file(request: Request, asset_path: str) -> FileResponse:
        raw = unquote(request.scope.get("raw_path", b"").decode("ascii", errors="replace"))
        normalized = raw.replace("\\", "/")
        if ".." in normalized.split("/") or "\x00" in normalized:
            raise HTTPException(404)
        if asset_path == "api" or asset_path.startswith("api/") or "\\" in asset_path:
            raise HTTPException(404)
        try:
            target = (root / (asset_path or "index.html")).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                raise HTTPException(404)
        except (OSError, ValueError, RuntimeError):
            raise HTTPException(404) from None
        cache = (
            "public, max-age=31536000, immutable"
            if asset_path.startswith("assets/")
            else "no-cache"
        )
        return FileResponse(target, headers={"Cache-Control": cache})
