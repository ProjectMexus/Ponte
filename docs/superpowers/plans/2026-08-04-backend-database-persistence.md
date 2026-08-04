# Backend Database Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with verification checkpoints.

**Goal:** Make Ponte mock backend state persist by default under the repository-root `database/` directory and make generated IDs survive backend restarts without collisions.

**Architecture:** Keep domain services dependent only on `RecordRepository`, `IdempotencyStore`, and `IdGenerator` protocols. Add a core `TextFileIdGenerator` backed by a JSON-Lines `.txt` repository, inject it from `create_application`, and make both the standalone backend CLI and full-stack runner default to the same repository-root `database/` path.

**Tech Stack:** Python 3.13 standard library, `unittest`, JSON-Lines `.txt` repositories, `pathlib`, and existing `ThreadingHTTPServer` wiring.

## Global Constraints

- Keep all domain services storage-agnostic; only application factories select concrete repositories and paths.
- Preserve explicit `--data-dir` overrides and temporary directories in tests.
- Do not commit runtime mock state; commit only `database/.gitkeep` and `database/.gitignore`.
- Preserve unrelated existing modifications in `middleware/intent.py` and `middleware/tests/test_intent.py`.
- Every completed plan step must be marked with `[x]`.

### Task 1: Add restart-safe text-backed ID generation

**Files:**
- Create: `tests/core/test_ids.py`
- Modify: `mock_backends/core/ids.py`

**Interfaces:**
- Consumes: `RecordRepository` from `mock_backends.core.contracts` and `JsonLinesTextRepository` from `mock_backends.core.persistence`.
- Produces: `TextFileIdGenerator(repository: RecordRepository).next(prefix: str) -> str`.

- [x] **Step 1: Write the failing persistence test**

Add a test using a temporary `sequences.txt`:

```python
def test_text_file_generator_continues_after_reopen(self):
    path = Path(self.temp_dir.name) / "sequences.txt"
    first = TextFileIdGenerator(JsonLinesTextRepository(path))

    self.assertEqual(first.next("APT"), "APT-0001")
    self.assertEqual(first.next("APT"), "APT-0002")

    reopened = TextFileIdGenerator(JsonLinesTextRepository(path))
    self.assertEqual(reopened.next("APT"), "APT-0003")
    self.assertEqual(reopened.next("TASK"), "TASK-0001")
```

Also assert the file contains one sequence record per prefix and that separate prefixes do not share counters.

- [x] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python3 -m unittest tests.core.test_ids -v
```

Expected: FAIL because `TextFileIdGenerator` does not exist.

- [x] **Step 3: Implement the minimal generator**

Add `TextFileIdGenerator` to `mock_backends/core/ids.py`. Under a `threading.Lock`, use record ID `SEQ-{prefix}` and a numeric `value` field:

```python
record_id = f"SEQ-{prefix}"
record = self.repository.get(record_id)
value = 0 if record is None else int(record["value"])
value += 1
updated = {"id": record_id, "prefix": prefix, "value": value}
if record is None:
    self.repository.insert(updated)
else:
    self.repository.replace(record_id, updated)
return f"{prefix}-{value:04d}"
```

Keep `SequentialIdGenerator` unchanged for deterministic in-memory domain tests.

- [x] **Step 4: Run the focused tests and core regression tests**

Run:

```bash
python3 -m unittest tests.core.test_ids tests.core.test_persistence tests.core.test_idempotency -v
```

Expected: PASS.

- [x] **Step 5: Commit the core change**

```bash
git add mock_backends/core/ids.py tests/core/test_ids.py
git commit -m "feat: persist mock backend id sequences"
```

### Task 2: Wire the repository-root database into production startup

**Files:**
- Modify: `mock_backends/server.py`
- Modify: `scripts/run_stack.py`
- Modify: `tests/test_run_stack.py`
- Create: `database/.gitkeep`
- Create: `database/.gitignore`

**Interfaces:**
- Consumes: `TextFileIdGenerator` from Task 1 and existing `JsonLinesTextRepository`.
- Produces: `create_application(data_dir, clock=None)` using `data_dir/id_sequences.txt`; default CLI and runner data root equal to `Path(__file__).resolve().parents[1] / "database"`.

- [x] **Step 1: Write the failing default-path tests**

Extend `tests/test_run_stack.py` to import `DEFAULT_DATA_DIR` and assert:

```python
def test_default_data_directory_is_repository_root_database(self):
    self.assertEqual(DEFAULT_DATA_DIR, Path(__file__).resolve().parents[1] / "database")
```

Add a test for `mock_backends.server.DEFAULT_DATA_DIR` with the same expected path. Keep the existing explicit `build_commands(..., data_dir=...)` assertion unchanged.

- [x] **Step 2: Run the focused runner tests and verify the default-path assertion fails**

Run:

```bash
python3 -m unittest tests.test_run_stack -v
```

Expected: FAIL because the two modules currently use `data/mock` or an ephemeral temporary directory and do not expose the repository-root default constant.

- [x] **Step 3: Implement production wiring and default paths**

In `mock_backends/server.py`:

- Define `PROJECT_ROOT = Path(__file__).resolve().parents[1]` and `DEFAULT_DATA_DIR = PROJECT_ROOT / "database"`.
- Replace `SequentialIdGenerator()` in `create_application` with `TextFileIdGenerator(JsonLinesTextRepository(root / "id_sequences.txt"))`.
- Change the CLI `--data-dir` default to `str(DEFAULT_DATA_DIR)`.

In `scripts/run_stack.py`:

- Define `DEFAULT_DATA_DIR = PROJECT_ROOT / "database"`.
- When `data_dir is None`, use `DEFAULT_DATA_DIR`; when it is provided, preserve the current resolved explicit path behavior.
- Always create the selected data directory before spawning the backend.
- Remove only the temporary-data cleanup path; do not alter process shutdown behavior.

Create `database/.gitkeep` and a `database/.gitignore` containing:

```gitignore
*.txt
!/.gitkeep
```

- [x] **Step 4: Run the runner and core integration tests**

Run:

```bash
python3 -m unittest tests.test_run_stack tests.core.test_ids tests.test_persistence_restart -v
```

Expected: PASS after Task 3 adds the medical restart coverage; before Task 3, the existing referral restart test must still pass.

- [x] **Step 5: Commit the startup wiring**

```bash
git add mock_backends/server.py scripts/run_stack.py tests/test_run_stack.py database/.gitkeep database/.gitignore
git commit -m "feat: use repository database as default backend storage"
```

### Task 3: Prove medical `.txt` persistence across restart and update documentation

**Files:**
- Modify: `tests/test_persistence_restart.py`
- Modify: `README.md`
- Modify: `mock_backends/README.md`
- Modify: `docs/api/jinghu-medical-mock-api.md`
- Modify: `docs/superpowers/specs/2026-08-03-mock-backends-design.md`
- Modify: `mock_backends/social_welfare/README.md`

**Interfaces:**
- Consumes: production `create_application` and the existing Medical HTTP-shaped request contracts.
- Produces: regression coverage that observes `database/medical/*.txt`, reads appointments after a new application instance, and creates a new appointment with unique IDs.

- [ ] **Step 1: Add the failing medical restart regression test**

In `tests/test_persistence_restart.py`, add a test that:

1. Creates a temporary root and first application.
2. POSTs `/mock/medical/v1/registrations` for `SLOT-REG-20260812-CARDIO-1030`.
3. Asserts status `201`, and asserts `medical/appointments.txt`, `medical/tasks.txt`, and `medical/idempotency.txt` exist under the temporary root.
4. Creates a second application with the same root.
5. GETs `/mock/medical/v1/appointments` and confirms the first appointment is present.
6. POSTs `/mock/medical/v1/appointments` for `SERVICE-US-001` and `SLOT-US-20260812-1400`.
7. Asserts status `201`, and asserts the second appointment and task IDs differ from the first ones.
8. Asserts the appointment and task files now contain two JSON-Lines records.

The test must use `FixedClock(datetime(2026, 8, 3, 9, 0, tzinfo=MACAU_TZ))`, patient `P-10001`, valid consent, and an `Idempotency-Key` on each POST.

- [ ] **Step 2: Run the medical restart test and verify the existing implementation fails**

Run:

```bash
python3 -m unittest tests.test_persistence_restart.PersistenceRestartTests.test_medical_booking_survives_restart_and_writes_txt -v
```

Expected: FAIL with the restarted medical application returning `500 MOCK_SERVICE_ERROR` because the process-local ID generator reuses `APT-0001` or `TASK-0001`.

- [ ] **Step 3: Update documentation to describe the actual persistence contract**

Update all listed documents so they consistently state:

- default storage is repository-root `database/`, sibling to `mock_backends/`;
- `medical/appointments.txt`, `medical/tasks.txt`, and `medical/idempotency.txt` are JSON-Lines state files;
- `id_sequences.txt` stores durable readable ID counters;
- `--data-dir` can override the root;
- runtime `.txt` state is local mock data and is not committed.

Remove statements that claim the full-stack runner defaults to temporary storage or that `data/mock` is the default. Keep temporary directories documented for tests and explicit `/tmp` examples.

- [ ] **Step 4: Run medical, persistence, and documentation checks**

Run:

```bash
python3 -m unittest tests.medical.test_medical_backend tests.test_persistence_restart -v
rg -n "database/|id_sequences\.txt|appointments\.txt|tasks\.txt|--data-dir" README.md mock_backends/README.md docs/api/jinghu-medical-mock-api.md docs/superpowers/specs/2026-08-03-mock-backends-design.md mock_backends/social_welfare/README.md
```

Expected: all tests PASS, and documentation references the same default path without stale `data/mock` default claims.

- [ ] **Step 5: Commit medical persistence and docs**

```bash
git add tests/test_persistence_restart.py README.md mock_backends/README.md docs/api/jinghu-medical-mock-api.md docs/superpowers/specs/2026-08-03-mock-backends-design.md mock_backends/social_welfare/README.md
git commit -m "test: verify medical text persistence across restart"
```

### Task 4: Run final verification and inspect scope

**Files:**
- Verify only; no intended source changes.

**Interfaces:**
- Consumes: completed Tasks 1–3.
- Produces: evidence that all relevant tests pass, Python modules compile, whitespace is clean, and unrelated user changes remain untouched.

- [ ] **Step 1: Run the non-socket full suite**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all tests pass except none; if socket binding is denied by the sandbox, rerun only the socket suites with the approved elevated test command and record that result.

- [ ] **Step 2: Run compilation and diff checks**

Run:

```bash
python3 -m compileall -q mock_backends scripts tests
git diff --check HEAD~3..HEAD
git status --short
```

Expected: compile succeeds, diff check emits no output, and status shows only the intended persistence commits plus the pre-existing `middleware/intent.py` and `middleware/tests/test_intent.py` changes.

- [ ] **Step 3: Confirm runtime files are ignored and visible**

Run a temporary application smoke check that creates one medical registration under a temporary data root and prints the relative `*.txt` paths. Confirm the paths include `medical/appointments.txt`, `medical/tasks.txt`, `medical/idempotency.txt`, and `id_sequences.txt`; do not create runtime state in the repository-root `database/` during tests.

- [ ] **Step 4: Report verification evidence**

Summarize the default path, medical restart behavior, test commands and results, changed files, and the preserved unrelated middleware modifications. Do not claim completion until the verification output confirms these points.
