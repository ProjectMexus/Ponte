"""Helpers for creating user-facing Cantonese speech text."""

from __future__ import annotations


_SPOKEN_REPLACEMENTS = (
    ("我已查到", "我幫你查到"),
    ("我已取得", "我已經攞到"),
    ("目前的", "而家嘅"),
    ("請選擇", "麻煩你揀"),
    ("暫時無法", "而家未能"),
    ("你的", "你嘅"),
    ("目前", "而家"),
    ("選擇", "揀"),
    ("時段", "時間"),
    ("沒有", "冇"),
    ("無法", "未能"),
    ("這次", "今次"),
    ("這個", "呢個"),
)


def to_cantonese_spoken(text: str) -> str:
    """Convert common written-Chinese phrases into a spoken Cantonese script."""

    if not isinstance(text, str):
        return ""

    spoken = text
    for written, colloquial in _SPOKEN_REPLACEMENTS:
        spoken = spoken.replace(written, colloquial)
    return spoken
