"""Read-only One Account demo catalogues."""

from __future__ import annotations

from copy import deepcopy


SERVICE_CENTERS = {
    "GSC-MAIN": {
        "service_center_name": "政府綜合服務中心（Mock）",
        "service_category": "government_service_center",
    },
    "IDB-MAIN": {
        "service_center_name": "身份證明局（Mock）",
        "service_category": "identification_services_bureau",
    },
}


CASH_SHARING_PLANS = {
    2026: {
        "plan_id": "CSP-2026",
        "plan_name": "現金分享計劃",
        "year": 2026,
        "status": "OPEN",
        "eligibility": {
            "eligible": True,
            "status": "ELIGIBLE",
            "reason": "符合本 Demo 測試用的基本資格資料。",
        },
        "payout": {
            "amount": 10000,
            "currency": "MOP",
            "payment_status": "SCHEDULED",
            "scheduled_date": "2026-09-30",
        },
        "history": [],
    }
}


def cash_sharing_plan(year: int) -> dict | None:
    plan = CASH_SHARING_PLANS.get(year)
    return deepcopy(plan) if plan is not None else None
