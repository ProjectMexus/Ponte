# Ponte Frontend Conversation Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the Ponte conversation panel reachable on desktop while the long workspace and conversation content scroll inside their own panels, without changing the chat or middleware behavior.

**Architecture:** Use CSS-only viewport-bound panels above the existing 900px responsive breakpoint. Both desktop panels become sticky and height-bounded; the conversation list and workspace panel own their vertical overflow. At or below 900px, reset sticky, fixed height, and overflow restrictions so the existing single-column document flow remains natural.

**Tech Stack:** Plain CSS, semantic HTML already present in `frontend/index.html`, Python `unittest` static contract checks.

## Global Constraints

- Frontend remains zero build dependency and uses the existing native HTML/CSS/JavaScript stack.
- Do not change the middleware HTTP contract, conversation rendering, action handling, or speech behavior.
- Keep desktop controls readable and usable; the conversation input form must remain visible while only the message list scrolls.
- At widths at or below 900px, preserve the existing one-column page and restore normal document scrolling.
- Preserve existing uncommitted user changes and do not modify unrelated backend files.

---

### Task 1: Add a failing layout contract test

**Files:**
- Modify: `tests/test_frontend_static.py` after `test_styles_define_large_controls_and_focus`

**Interfaces:**
- Consumes: the stylesheet text from `frontend/styles.css`.
- Produces: a regression test that requires viewport-bound desktop panels, independent overflow, and a mobile reset.

- [x] **Step 1: Write the failing test**

Add this test method to `FrontendStaticTests`:

```python
    def test_styles_keep_desktop_conversation_reachable(self):
        css = Path("frontend/styles.css").read_text(encoding="utf-8")
        self.assertRegex(
            css,
            r"\.conversation-panel\s*\{[^}]*position:\s*sticky;[^}]*height:\s*calc\(100dvh - 40px\);",
        )
        self.assertRegex(
            css,
            r"\.workspace-panel\s*\{[^}]*height:\s*calc\(100dvh - 40px\);[^}]*overflow-y:\s*auto;",
        )
        self.assertRegex(
            css,
            r"\.conversation-list\s*\{[^}]*min-height:\s*0;[^}]*overflow-y:\s*auto;",
        )
        self.assertRegex(
            css,
            r"@media\s*\(max-width:\s*900px\)[\s\S]*?\.conversation-panel,\s*\.workspace-panel\s*\{[^}]*position:\s*static;[^}]*height:\s*auto;[^}]*overflow:\s*visible;",
        )
```

- [x] **Step 2: Run the focused test to verify it fails**

Run:

```bash
python3 -m unittest tests.test_frontend_static.FrontendStaticTests.test_styles_keep_desktop_conversation_reachable -v
```

Expected: FAIL because the current stylesheet does not give the conversation panel a sticky viewport-bound block, does not bound the workspace panel, and does not reset both panels at the mobile breakpoint.

### Task 2: Implement the CSS-only viewport-bound layout

**Files:**
- Modify: `frontend/styles.css` in the `.conversation-panel`, `.workspace-panel`, `.conversation-list`, and `@media (max-width: 900px)` rules

**Interfaces:**
- Consumes: existing `app-shell`, panel, message list, workspace, and mobile breakpoint selectors.
- Produces: desktop panels that remain visible and internally scroll, plus a mobile reset that preserves the current page flow.

- [x] **Step 1: Add the desktop conversation panel boundary**

Extend the standalone `.conversation-panel` rule with:

```css
  position: sticky;
  top: 20px;
  height: calc(100dvh - 40px);
  min-height: 0;
  overflow: hidden;
```

This keeps the input controls in the panel while allowing the flex child message list to consume the remaining space.

- [x] **Step 2: Bound the desktop workspace panel**

Extend the standalone `.workspace-panel` rule with:

```css
  height: calc(100dvh - 40px);
  max-height: calc(100dvh - 40px);
  overflow-y: auto;
  overscroll-behavior: contain;
```

The existing `position: sticky` and `top: 20px` remain unchanged. Long task data and action lists now scroll inside the right panel instead of extending the page height.

- [x] **Step 3: Make the conversation list the left panel's scroll region**

Add `min-height: 0` and `overscroll-behavior: contain` to `.conversation-list` while retaining its existing `flex: 1` and `overflow-y: auto` declarations:

```css
  min-height: 0;
  overscroll-behavior: contain;
```

- [x] **Step 4: Reset bounded behavior on the mobile breakpoint**

Add this rule inside `@media (max-width: 900px)`:

```css
  .conversation-panel,
  .workspace-panel {
    position: static;
    height: auto;
    max-height: none;
    overflow: visible;
  }

  .conversation-list {
    flex: 0 0 auto;
    min-height: 310px;
    overflow-y: visible;
  }
```

This removes the desktop-only scroll containers when the layout is stacked.

- [x] **Step 5: Run the focused test to verify it passes**

Run:

```bash
python3 -m unittest tests.test_frontend_static.FrontendStaticTests.test_styles_keep_desktop_conversation_reachable -v
```

Expected: PASS.

### Task 3: Run regression verification and review the diff

**Files:**
- Verify: `frontend/styles.css`
- Verify: `tests/test_frontend_static.py`

**Interfaces:**
- Consumes: the passing layout contract and existing frontend/backend test suite.
- Produces: verified CSS behavior with no JavaScript or API regressions.

- [x] **Step 1: Run all frontend static tests**

```bash
python3 -m unittest tests.test_frontend_static -v
```

Expected: all frontend static tests pass.

- [x] **Step 2: Run JavaScript syntax checks**

```bash
node --check frontend/app.js
node --check frontend/mcp-client.js
node --check frontend/interaction-view.js
node --check frontend/speech.js
```

Expected: all commands exit with status 0.

- [x] **Step 3: Run the full Python regression suite**

```bash
python3 -m unittest discover -v
```

Expected: no failures or errors.

- [x] **Step 4: Inspect the final diff and whitespace**

```bash
git diff --check
git diff -- frontend/styles.css tests/test_frontend_static.py
```

Confirm only the intended CSS and static test changes are present, with no edits to JavaScript, HTML, backend, or middleware files.

- [x] **Step 5: Commit the implementation**

```bash
git add frontend/styles.css tests/test_frontend_static.py
git commit -m "fix: keep Ponte conversation panel reachable"
```
