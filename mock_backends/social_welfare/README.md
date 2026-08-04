# Mock Social Welfare Backend

這個 domain backend 是根據 `docs/PonteArch.md` 第 8.3 節的 Arch-derived demo contract，以及長者文娛活動 API 文件建立，並不是澳門政府或任何社福機構的正式 API。

支援：

- `GET /mock/social-welfare/services`
- `POST /mock/social-welfare/referrals`
- `GET /mock/social-welfare/referrals/{referralId}`
- `POST /mock/social-welfare/referrals/{referralId}/assign`
- `GET /mock/elderly-activities/v1/activities`
- `POST /mock/elderly-activities/v1/registrations`
- `POST /mock/elderly-activities/v1/phone-registration-assists`

它只模擬服務目錄、資料共享同意、轉介建立、社工接手及狀態查詢。所有資料都是 mock；不會發送真實通知，也不會聯絡真實社工。建立轉介要求 `X-Mock-User-Id`、`Idempotency-Key`、`consents.data_sharing=true` 和 Workflow confirmation。

長者活動由同一 domain 下獨立的 `ElderlyActivitiesService` 處理；日後的 MCP adapter 應調用對應 service 的方法，不應直接讀寫 `database/social_welfare/*.txt`。
