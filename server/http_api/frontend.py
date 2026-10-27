"""Frontend endpoints."""

from aiohttp import web


async def index(request):
    settings = request.app["settings"]
    page = settings.web_dist / "index.html"
    if not page.is_file():
        return web.Response(text="frontend not deployed", status=503)
    # Read per request so a frontend-only deploy shows up without a restart.
    return web.Response(
        text=page.read_text(),
        content_type="text/html",
        headers={"Cache-Control": "no-cache"},
    )


async def frontend(request):
    """Built frontend files, falling back to index.html for client-side routes."""
    settings = request.app["settings"]
    path = request.match_info["path"]
    if path:
        target = (settings.web_dist / path).resolve()
        if target.is_relative_to(settings.web_dist) and target.is_file():
            return web.FileResponse(
                target,
                headers={"Cache-Control": "public, max-age=31536000, immutable"}
                if path.startswith("assets/")
                else None,
            )
    return await index(request)
