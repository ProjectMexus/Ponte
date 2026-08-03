"""Arch-derived social welfare demo catalogues."""

from __future__ import annotations

from copy import deepcopy


WELFARE_SERVICES = [
    {
        "service_id": "WELFARE-ESCORT-001",
        "name": "陪診及交通協助",
        "category": "elderly_support",
        "summary": "協助長者往返覆診地點，並可安排陪同到診。",
        "districts": ["澳門半島", "氹仔"],
        "accessibility": ["wheelchair_accessible", "cantonese"],
        "contact": {"phone": "+853-6300-1001", "service_hours": "星期一至五 09:00-17:30"},
        "active": True,
    },
    {
        "service_id": "WELFARE-COMPANION-002",
        "name": "社區生活陪伴服務",
        "category": "community_care",
        "summary": "提供社區活動、購物及生活安排的短時陪伴。",
        "districts": ["澳門半島", "氹仔", "路環"],
        "accessibility": ["cantonese", "seated_activity"],
        "contact": {"phone": "+853-6300-1002", "service_hours": "星期一至五 10:00-18:00"},
        "active": True,
    },
    {
        "service_id": "WELFARE-CALL-003",
        "name": "長者電話關懷",
        "category": "emotional_support",
        "summary": "由社工或受訓義工按約定時間致電關懷。",
        "districts": ["澳門半島", "氹仔", "路環"],
        "accessibility": ["cantonese", "phone_support"],
        "contact": {"phone": "+853-6300-1003", "service_hours": "星期一至日 09:00-20:00"},
        "active": True,
    },
]

CASE_WORKERS = [
    {"case_worker_id": "CW-001", "name": "黃社工", "team": "長者支援隊", "contact_method": "phone"},
    {"case_worker_id": "CW-002", "name": "何社工", "team": "社區照顧隊", "contact_method": "phone"},
]


def services() -> list[dict]:
    return deepcopy(WELFARE_SERVICES)


def case_workers() -> list[dict]:
    return deepcopy(CASE_WORKERS)
