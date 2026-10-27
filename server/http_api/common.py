"""Shared HTTP error responses."""

from aiohttp import web


def bad_request(message):
    return web.json_response({"error": message}, status=400)
