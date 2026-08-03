"""Mock cultural activity catalogue for the social welfare domain."""

from __future__ import annotations

from copy import deepcopy


def _activity(
    activity_id: str,
    organization_id: str,
    organization_name: str,
    organization_phone: str,
    title: str,
    summary: str,
    activity_type: str,
    category: str,
    tags: list[str],
    start_at: str,
    end_at: str,
    venue_name: str,
    district: str,
    age_min: int,
    quota: int,
    registered: int,
    method: str,
    deadline: str,
    form_id: str | None = None,
    full: bool = False,
    accessibility: list[str] | None = None,
) -> dict:
    organization = {
        "organization_id": organization_id,
        "name": organization_name,
        "short_name": organization_id,
        "contact_phone": organization_phone,
        "service_hours": "星期一至五 09:00-12:00、14:00-17:30",
    }
    registration = {
        "method": method,
        "status": "closed" if full else "open",
        "opens_at": "2026-07-20T09:00:00+08:00",
        "closes_at": f"{deadline}T17:30:00+08:00",
        "deadline": deadline,
        "phone": organization_phone,
        "phone_hours": organization["service_hours"],
        "required_information": ["姓名", "聯絡電話", "年齡"],
        "requires_confirmation": True,
        "instructions": ["由 Ponte Workflow 顯示活動摘要並取得長者確認。"],
    }
    result = {
        "activity_id": activity_id,
        "status": "published",
        "organization": organization,
        "title": title,
        "summary": summary,
        "description": summary,
        "activity_type": activity_type,
        "category": category,
        "tags": tags,
        "schedule": {"start_at": start_at, "end_at": end_at, "timezone": "Asia/Macau"},
        "venue": {"name": venue_name, "address": f"{district} Mock 活動地址", "district": district, "transport_note": "場地設升降機。"},
        "audience": {"age_min": age_min, "age_max": None, "description": f"{age_min}歲或以上長者", "quota": quota},
        "fee": {"amount": 0, "currency": "MOP", "display": "全免"},
        "availability": {"status": "full" if full else "open", "quota": quota, "registered": registered, "remaining": max(0, quota - registered)},
        "participation": {"languages": ["粵語", "普通話"], "accessibility": accessibility or [], "what_to_bring": "可自備飲用水。"},
        "registration": registration,
        "last_updated_at": "2026-08-01T15:30:00+08:00",
    }
    if form_id is not None:
        result["form"] = {
            "form_id": form_id,
            "title": f"{title}報名表",
            "fields": [
                {"name": "full_name", "label": "姓名", "type": "string", "required": True, "sensitive": False},
                {"name": "phone", "label": "聯絡電話", "type": "phone", "required": True, "sensitive": True},
                {"name": "age", "label": "年齡", "type": "integer", "required": True, "minimum": age_min, "sensitive": True},
            ],
        }
    return result


ACTIVITIES = [
    _activity("ACT-ORG-A-20260808-001", "ORG-A", "A機構長者文化中心", "+853-6200-1001", "樂齡粵曲欣賞與唱腔體驗", "欣賞粵曲並以簡單方式體驗唱腔。", "workshop", "arts", ["粵曲", "唱歌", "音樂"], "2026-08-08T14:15:00+08:00", "2026-08-08T16:00:00+08:00", "A機構文化活動室", "澳門半島", 55, 20, 8, "form", "2026-08-06", "FORM-ORG-A-001", accessibility=["seated_activity"]),
    _activity("ACT-ORG-A-20260815-002", "ORG-A", "A機構長者文化中心", "+853-6200-1001", "手機攝影與生活記錄工作坊", "學習用手機拍攝日常照片及整理相簿。", "workshop", "learning", ["手機", "攝影", "數碼技能"], "2026-08-15T10:00:00+08:00", "2026-08-15T12:00:00+08:00", "A機構氹仔活動室", "氹仔", 60, 16, 8, "phone", "2026-08-12", accessibility=["wheelchair_accessible", "large_print_handout"]),
    _activity("ACT-ORG-A-20260808-003", "ORG-A", "A機構長者文化中心", "+853-6200-1001", "滿額示範活動", "供 Demo 展示名額已滿的錯誤分支。", "lecture", "learning", ["Demo"], "2026-08-08T09:00:00+08:00", "2026-08-08T10:00:00+08:00", "A機構會議室", "澳門半島", 55, 10, 10, "form", "2026-08-07", "FORM-ORG-A-FULL", full=True),
    _activity("ACT-ORG-B-20260809-001", "ORG-B", "B機構社區圖書館", "+853-6200-2001", "樂齡閱讀小組：澳門故事", "以澳門故事為主題的輕鬆閱讀及分享活動。", "reading_group", "reading", ["閱讀", "分享", "社區"], "2026-08-09T10:30:00+08:00", "2026-08-09T12:00:00+08:00", "B機構中央圖書館多功能室", "澳門半島", 55, 20, 12, "form", "2026-08-07", "FORM-ORG-B-READING-001", accessibility=["wheelchair_accessible"]),
    _activity("ACT-ORG-B-20260816-002", "ORG-B", "B機構社區圖書館", "+853-6200-2001", "公共圖書館 e 學堂：手機應用入門", "用簡單步驟學習手機常用功能和公共服務應用。", "course", "learning", ["手機", "數碼", "圖書館"], "2026-08-16T14:00:00+08:00", "2026-08-16T16:00:00+08:00", "B機構數碼學習室", "氹仔", 60, 12, 5, "phone", "2026-08-13", accessibility=["large_print_handout"]),
    _activity("ACT-ORG-B-20260820-003", "ORG-B", "B機構社區圖書館", "+853-6200-2001", "社區音樂欣賞會", "以粵語介紹不同年代的本地音樂。", "performance", "arts", ["音樂", "唱歌", "分享"], "2026-08-20T15:00:00+08:00", "2026-08-20T16:30:00+08:00", "B機構社區禮堂", "氹仔", 55, 30, 10, "form", "2026-08-18", "FORM-ORG-B-MUSIC-003", accessibility=["wheelchair_accessible"]),
]


def activities() -> list[dict]:
    return deepcopy(ACTIVITIES)


def activity(activity_id: str) -> dict | None:
    for item in ACTIVITIES:
        if item["activity_id"] == activity_id:
            return deepcopy(item)
    return None
