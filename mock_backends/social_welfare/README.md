# Mock Social Welfare Backend

這個 domain backend 是根據 `docs/PonteArch.md` 第 8.3 節的 Arch-derived demo contract 建立，並不是澳門政府或任何社福機構的正式 API。

支援：

- `GET /mock/social-welfare/services`
- `POST /mock/social-welfare/referrals`
- `GET /mock/social-welfare/referrals/{referralId}`
- `POST /mock/social-welfare/referrals/{referralId}/assign`

它只模擬服務目錄、資料共享同意、轉介建立、社工接手及狀態查詢。所有資料都是 mock；不會發送真實通知，也不會聯絡真實社工。建立轉介要求 `X-Mock-User-Id`、`Idempotency-Key`、`consents.data_sharing=true` 和 Workflow confirmation。

日後的 MCP adapter 應調用 `SocialWelfareService` 的方法，不應直接讀寫 `data/mock/social_welfare/*.txt`。
