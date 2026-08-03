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


ACTIVITIES = [
    {
        "activity_id": "ACT-ORG-A-20260808-001",
        "status": "published",
        "organization": {
            "organization_id": "ORG-A",
            "name": "A機構長者文化中心",
            "short_name": "A機構",
            "contact_phone": "+853-6200-1001",
            "service_hours": "星期一至五 09:00-12:00、14:00-17:30",
        },
        "title": "樂齡粵曲欣賞與唱腔體驗",
        "summary": "欣賞粵曲並以簡單方式體驗唱腔，適合長者輕鬆參加。",
        "description": "導師會介紹粵曲基本唱腔，參加者可以按興趣即場試唱。",
        "activity_type": "workshop",
        "category": "arts",
        "tags": ["粵曲", "唱歌", "音樂"],
        "schedule": {
            "start_at": "2026-08-08T14:15:00+08:00",
            "end_at": "2026-08-08T16:00:00+08:00",
            "timezone": "Asia/Macau",
        },
        "venue": {
            "name": "A機構文化活動室",
            "address": "澳門半島文化街 10 號",
            "district": "澳門半島",
            "transport_note": "近巴士站，場地設升降機。",
        },
        "audience": {"age_min": 55, "age_max": None, "description": "55歲或以上長者", "quota": 20},
        "fee": {"amount": 0, "currency": "MOP", "display": "全免"},
        "availability": {"status": "open", "quota": 20, "registered": 8, "remaining": 12},
        "participation": {"languages": ["粵語"], "accessibility": ["seated_activity"], "what_to_bring": "可自備飲用水。"},
        "registration": {
            "method": "form",
            "status": "open",
            "opens_at": "2026-07-20T09:00:00+08:00",
            "closes_at": "2026-08-06T17:30:00+08:00",
            "deadline": "2026-08-06",
            "phone": "+853-6200-1001",
            "phone_hours": "星期一至五 09:00-12:00、14:00-17:30",
            "required_information": ["姓名", "聯絡電話", "年齡"],
            "requires_confirmation": True,
            "instructions": ["填妥資料後，由 Ponte Workflow 顯示摘要並要求確認。"],
        },
        "form": {
            "form_id": "FORM-ORG-A-001",
            "title": "樂齡粵曲欣賞與唱腔體驗報名表",
            "fields": [
                {"name": "full_name", "label": "姓名", "type": "string", "required": True, "sensitive": False},
                {"name": "phone", "label": "聯絡電話", "type": "phone", "required": True, "sensitive": True},
                {"name": "age", "label": "年齡", "type": "integer", "required": True, "minimum": 55, "sensitive": True},
                {"name": "accessibility_needs", "label": "需要的場地支援", "type": "enum[]", "required": False, "options": ["seated_activity", "none"], "sensitive": False},
            ],
        },
        "last_updated_at": "2026-08-01T15:30:00+08:00",
    },
    {
        "activity_id": "ACT-ORG-A-20260815-002",
        "status": "published",
        "organization": {
            "organization_id": "ORG-A",
            "name": "A機構長者文化中心",
            "short_name": "A機構",
            "contact_phone": "+853-6200-1001",
            "service_hours": "星期一至五 09:00-12:00、14:00-17:30",
        },
        "title": "手機攝影與生活記錄工作坊",
        "summary": "學習用手機拍攝日常照片及簡單整理相簿。",
        "description": "導師會用簡單步驟示範構圖、拍攝及相簿分類。",
        "activity_type": "workshop",
        "category": "learning",
        "tags": ["手機", "攝影", "數碼技能"],
        "schedule": {"start_at": "2026-08-15T10:00:00+08:00", "end_at": "2026-08-15T12:00:00+08:00", "timezone": "Asia/Macau"},
        "venue": {"name": "A機構氹仔活動室", "address": "氹仔海濱大馬路 20 號", "district": "氹仔", "transport_note": "近氹仔市中心巴士站，場地設升降機。"},
        "audience": {"age_min": 60, "age_max": None, "description": "60歲或以上長者", "quota": 16},
        "fee": {"amount": 20, "currency": "MOP", "display": "澳門元20元"},
        "availability": {"status": "open", "quota": 16, "registered": 8, "remaining": 8},
        "participation": {"languages": ["粵語", "普通話"], "accessibility": ["wheelchair_accessible", "large_print_handout"], "what_to_bring": "請攜帶已充電的智能手機。"},
        "registration": {
            "method": "phone",
            "status": "open",
            "opens_at": "2026-07-20T09:00:00+08:00",
            "closes_at": "2026-08-12T17:30:00+08:00",
            "deadline": "2026-08-12",
            "phone": "+853-6200-1001",
            "phone_hours": "星期一至五 09:00-12:00、14:00-17:30",
            "required_information": ["姓名", "聯絡電話", "年齡", "是否需要輪椅位置"],
            "requires_confirmation": True,
            "instructions": ["於服務時間致電 A機構。", "說明活動名稱及日期。"],
        },
        "last_updated_at": "2026-08-01T15:30:00+08:00",
    },
    {
        "activity_id": "ACT-ORG-A-20260808-003",
        "status": "published",
        "organization": {"organization_id": "ORG-A", "name": "A機構長者文化中心", "short_name": "A機構", "contact_phone": "+853-6200-1001", "service_hours": "星期一至五 09:00-17:30"},
        "title": "滿額示範活動",
        "summary": "供 Demo 展示名額已滿的錯誤分支。",
        "description": "此活動專門展示名額耗盡時的受控錯誤。",
        "activity_type": "lecture",
        "category": "learning",
        "tags": ["Demo"],
        "schedule": {"start_at": "2026-08-08T09:00:00+08:00", "end_at": "2026-08-08T10:00:00+08:00", "timezone": "Asia/Macau"},
        "venue": {"name": "A機構會議室", "address": "澳門半島測試街 2 號", "district": "澳門半島"},
        "audience": {"age_min": 55, "age_max": None, "description": "55歲或以上長者", "quota": 10},
        "fee": {"amount": 0, "currency": "MOP", "display": "全免"},
        "availability": {"status": "full", "quota": 10, "registered": 10, "remaining": 0},
        "participation": {"languages": ["粵語"], "accessibility": [], "what_to_bring": "不需要。"},
        "registration": {"method": "form", "status": "closed", "opens_at": "2026-07-01T09:00:00+08:00", "closes_at": "2026-08-07T17:30:00+08:00", "deadline": "2026-08-07", "phone": "+853-6200-1001", "phone_hours": "星期一至五 09:00-17:30", "required_information": ["姓名", "聯絡電話", "年齡"], "requires_confirmation": True, "instructions": []},
        "form": {"form_id": "FORM-ORG-A-FULL", "title": "滿額示範活動報名表", "fields": []},
        "last_updated_at": "2026-08-01T15:30:00+08:00",
    },
    {
        "activity_id": "ACT-ORG-B-20260809-001",
        "status": "published",
        "organization": {"organization_id": "ORG-B", "name": "B機構社區圖書館", "short_name": "B機構", "contact_phone": "+853-6200-2001", "service_hours": "星期一至日 10:00-19:00，公眾假期除外"},
        "title": "樂齡閱讀小組：澳門故事",
        "summary": "以澳門人物和社區故事為主題的輕鬆閱讀及分享活動。",
        "description": "參加者一起閱讀短篇文章並分享生活故事。",
        "activity_type": "reading_group",
        "category": "reading",
        "tags": ["閱讀", "分享", "社區"],
        "schedule": {"start_at": "2026-08-09T10:30:00+08:00", "end_at": "2026-08-09T12:00:00+08:00", "timezone": "Asia/Macau"},
        "venue": {"name": "B機構中央圖書館多功能室", "address": "澳門半島閱讀街 8 號", "district": "澳門半島"},
        "audience": {"age_min": 55, "age_max": None, "description": "55歲或以上長者及對閱讀有興趣人士", "quota": 20},
        "fee": {"amount": 0, "currency": "MOP", "display": "全免"},
        "availability": {"status": "open", "quota": 20, "registered": 12, "remaining": 8},
        "participation": {"languages": ["粵語"], "accessibility": ["wheelchair_accessible"], "what_to_bring": "可自備眼鏡。"},
        "registration": {"method": "form", "status": "open", "opens_at": "2026-07-20T09:00:00+08:00", "closes_at": "2026-08-07T19:00:00+08:00", "deadline": "2026-08-07", "phone": "+853-6200-2001", "phone_hours": "星期一至日 10:00-19:00，公眾假期除外", "required_information": ["姓名", "聯絡電話", "年齡"], "requires_confirmation": True, "instructions": ["向圖書館職員確認名額。"]},
        "form": {"form_id": "FORM-ORG-B-READING-001", "title": "樂齡閱讀小組報名表", "fields": [{"name": "full_name", "label": "姓名", "type": "string", "required": True, "sensitive": False}, {"name": "phone", "label": "聯絡電話", "type": "phone", "required": True, "sensitive": True}, {"name": "age", "label": "年齡", "type": "integer", "required": True, "minimum": 55, "sensitive": True}]},
        "last_updated_at": "2026-08-01T15:30:00+08:00",
    },
    {
        "activity_id": "ACT-ORG-B-20260816-002",
        "status": "published",
        "organization": {"organization_id": "ORG-B", "name": "B機構社區圖書館", "short_name": "B機構", "contact_phone": "+853-6200-2001", "service_hours": "星期一至日 10:00-19:00，公眾假期除外"},
        "title": "公共圖書館 e 學堂：手機應用入門",
        "summary": "用簡單步驟學習手機常用功能和公共服務應用。",
        "description": "導師會以慢速示範手機設定、搜尋和圖書館服務。",
        "activity_type": "course",
        "category": "learning",
        "tags": ["手機", "數碼", "圖書館"],
        "schedule": {"start_at": "2026-08-16T14:00:00+08:00", "end_at": "2026-08-16T16:00:00+08:00", "timezone": "Asia/Macau"},
        "venue": {"name": "B機構數碼學習室", "address": "氹仔圖書館路 3 號", "district": "氹仔"},
        "audience": {"age_min": 60, "age_max": None, "description": "60歲或以上長者，需持有圖書館讀者證", "quota": 12},
        "fee": {"amount": 0, "currency": "MOP", "display": "全免"},
        "availability": {"status": "open", "quota": 12, "registered": 5, "remaining": 7},
        "participation": {"languages": ["粵語", "普通話"], "accessibility": ["large_print_handout"], "what_to_bring": "請帶圖書館讀者證和手機。"},
        "registration": {"method": "phone", "status": "open", "opens_at": "2026-07-20T10:00:00+08:00", "closes_at": "2026-08-13T19:00:00+08:00", "deadline": "2026-08-13", "phone": "+853-6200-2001", "phone_hours": "星期一至日 10:00-19:00，公眾假期除外", "required_information": ["姓名", "聯絡電話", "年齡", "是否持有圖書館讀者證"], "requires_confirmation": True, "instructions": ["於服務時間致電 B機構。", "向職員確認是否成功留位。"]},
        "last_updated_at": "2026-08-01T15:30:00+08:00",
    },
    {
        "activity_id": "ACT-ORG-B-20260820-003",
        "status": "published",
        "organization": {"organization_id": "ORG-B", "name": "B機構社區圖書館", "short_name": "B機構", "contact_phone": "+853-6200-2001", "service_hours": "星期一至日 10:00-19:00，公眾假期除外"},
        "title": "社區音樂欣賞會",
        "summary": "以粵語介紹不同年代的本地音樂。",
        "description": "主持人會播放音樂並邀請參加者分享回憶。",
        "activity_type": "performance",
        "category": "arts",
        "tags": ["音樂", "唱歌", "分享"],
        "schedule": {"start_at": "2026-08-20T15:00:00+08:00", "end_at": "2026-08-20T16:30:00+08:00", "timezone": "Asia/Macau"},
        "venue": {"name": "B機構社區禮堂", "address": "氹仔社區路 5 號", "district": "氹仔"},
        "audience": {"age_min": 55, "age_max": None, "description": "長者優先", "quota": 30},
        "fee": {"amount": 0, "currency": "MOP", "display": "全免"},
        "availability": {"status": "open", "quota": 30, "registered": 10, "remaining": 20},
        "participation": {"languages": ["粵語"], "accessibility": ["wheelchair_accessible"], "what_to_bring": "不需要。"},
        "registration": {"method": "form", "status": "open", "opens_at": "2026-07-20T10:00:00+08:00", "closes_at": "2026-08-18T19:00:00+08:00", "deadline": "2026-08-18", "phone": "+853-6200-2001", "phone_hours": "星期一至日 10:00-19:00，公眾假期除外", "required_information": ["姓名", "聯絡電話", "年齡"], "requires_confirmation": True, "instructions": []},
        "form": {"form_id": "FORM-ORG-B-MUSIC-003", "title": "社區音樂欣賞會報名表", "fields": [{"name": "full_name", "label": "姓名", "type": "string", "required": True, "sensitive": False}, {"name": "phone", "label": "聯絡電話", "type": "phone", "required": True, "sensitive": True}, {"name": "age", "label": "年齡", "type": "integer", "required": True, "minimum": 55, "sensitive": True}]},
        "last_updated_at": "2026-08-01T15:30:00+08:00",
    },
]


def activities() -> list[dict]:
    return deepcopy(ACTIVITIES)


def activity(activity_id: str) -> dict | None:
    for item in ACTIVITIES:
        if item["activity_id"] == activity_id:
            return deepcopy(item)
    return None
