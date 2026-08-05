# 粵語口語自動朗讀 Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task-by-task. Completed steps are marked with `x`.

**Goal:** Keep written assistant replies in the conversation while automatically reading a separate Cantonese-spoken response that users can enable or disable.

**Architecture:** `middleware/speech.py` provides a pure, ordered phrase converter. `middleware.session.build_response()` adds its result as `assistant_speech_message` for every existing controller response. The frontend continues displaying `assistant_message`, reads the new field with a fallback, and uses the existing speech control as a default-on `aria-pressed` toggle.

**Constraints:** Preserve the existing endpoint and `assistant_message`; use browser `zh-HK`; keep text usable when speech is unavailable; do not add external TTS/LLM dependencies or redesign speech input.

## Task 1: Middleware failing tests

**Files:** Create `middleware/tests/test_speech.py`.

- [x] Write tests for common phrase conversion, preservation of identifiers, and both response fields.
- [x] Run `python -m unittest middleware.tests.test_speech -v` and confirm the expected import failure before implementation.

## Task 2: Middleware speech response

**Files:** Create `middleware/speech.py`; modify `middleware/session.py`.

- [x] Implement `to_cantonese_spoken(text: str) -> str` with ordered replacements: `我已查到`→`我幫你查到`, `目前的`→`而家嘅`, `請選擇`→`麻煩你揀`, `暫時無法`→`而家未能`, `你的`→`你嘅`, `目前`→`而家`, `時段`→`時間`, `沒有`→`冇`, `這個`→`呢個`, and related safe phrases.
- [x] Add `assistant_speech_message: to_cantonese_spoken(assistant_message)` in `build_response()` without changing controller call sites.
- [x] Run `python -m unittest middleware.tests.test_speech -v` (3 passing).
- [x] Run `python -m unittest middleware.tests.test_task_manager middleware.tests.test_controller -v` (23 passing).

## Task 3: Frontend failing checks

**Files:** Modify `tests/test_frontend_static.py`.

- [x] Add static checks for `aria-pressed="true"`, `自動朗讀：開`, `autoSpeakEnabled`, the response fallback, and `speech.stopSpeaking()`.
- [x] Require the speech synthesis implementation to contain `try` and `catch`.
- [x] Run the focused test and confirm it fails against the old button and wiring.

## Task 4: Frontend auto-read implementation

**Files:** Modify `frontend/index.html`, `frontend/app.js`, `frontend/speech.js`.

- [x] Keep `speak-stop-button` but make it `aria-pressed="true"` with label `自動朗讀：開`.
- [x] Add default-on `autoSpeakEnabled`, render `自動朗讀：開／關`, read `response.assistant_speech_message || response.assistant_message` after message and action responses, and cancel speech when toggled off.
- [x] Wrap speech synthesis creation/cancel/speak in `try/catch`, preserving `zh-HK`, rate `0.92`, and pitch `1`.
- [x] Run bundled Node syntax checks for `frontend/app.js` and `frontend/speech.js`.
- [x] Run `python -m unittest tests.test_frontend_static -v` (21 passing).

## Task 5: Documentation and full verification

**Files:** Modify `frontend/README.md`; keep this plan updated.

- [x] Document the written-versus-spoken response fields, default-on toggle, immediate cancellation, and text fallback.
- [x] Run `python -m unittest discover -v` and record the result: 219 tests ran, 217 passed; the 2 failures are pre-existing appointment-branch failures (`tests.core.test_core_helpers` timezone expectation and `tests.test_middleware_integration` expanded-service expectation).
- [x] Run bundled Node syntax checks for all four frontend modules and `git diff --check`.
- [x] Review the final diff for contract preservation and unrelated changes; appointment-related staged/unstaged files remain excluded from this feature.
- [x] Commit only this feature's implementation files; preserve unrelated staged appointment changes.
