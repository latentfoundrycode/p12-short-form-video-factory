"""Shared ModelArk-style `content` array builder (BytePlus / MiniMax video submit)."""

from __future__ import annotations

from typing import Any


def build_media_content(
    prompt: str,
    first_frame_url: str | None,
    last_frame_url: str | None,
    ref_urls: list[str],
    *,
    ref_role: str | None = None,
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if first_frame_url:
        content.append(
            {"type": "image_url", "image_url": {"url": first_frame_url}, "role": "first_frame"}
        )
    if last_frame_url:
        content.append(
            {"type": "image_url", "image_url": {"url": last_frame_url}, "role": "last_frame"}
        )
    for url in ref_urls:
        item: dict[str, Any] = {"type": "image_url", "image_url": {"url": url}}
        if ref_role is not None:
            item["role"] = ref_role
        content.append(item)
    return content
