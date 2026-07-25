5. **`POST` endpoints returning `200` instead of `201`** — all three creation
   endpoints (`/students`, `/courses`, `/enrollments`) were returning the
   FastAPI default status code, `200`, on success. That's the right code for
   a read or an update that doesn't create anything new, but wrong here:
   these endpoints exist specifically to create a new resource, and `201
   Created` is the status code that communicates that. Fixed by setting
   `status_code=status.HTTP_201_CREATED` on each `@app.post(...)` decorator.
   Doesn't touch the error paths — an explicitly raised `HTTPException`
   always overrides the decorator's default, so the existing `404`/`409`
   responses on these same endpoints were unaffected. Verified each
   endpoint individually via curl after the fix, not assumed from the first
   one working.

---

## Test suite (`pytest`)

Added after the endpoints were manually verified via curl/Swagger — the
manual testing caught real bugs (see "Things that broke" above), but none
of it was repeatable. The pytest suite turns those same checks into
something that runs in under half a second and catches regressions instead
of relying on remembering to re-test by hand.

### Test database isolation

Tests do **not** run against `grades.db`. `conftest.py` defines a second
engine pointed at `test.db`, and overrides the `get_db` dependency used
throughout `main.py` (`app.dependency_overrides[get_db] = override_get_db`)
so every request made through `TestClient` during a test resolves to the
test database instead of the real one.

```python
TEST_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
```

`check_same_thread=False` is required here for the same reason it's set on
the main engine in `database.py`: FastAPI dispatches sync route handlers to
a worker thread even under `TestClient`, so the DB connection created in
the test's main thread gets touched from a different thread during the
request. SQLite refuses that by default; this flag tells it the connection
pooling is handled correctly elsewhere (it is, by SQLAlchemy).

### Per-test isolation via a fixture

```python
@pytest.fixture
def client():
    Base.metadata.create_all(bind=engine)
    yield TestClient(app)
    Base.metadata.drop_all(bind=engine)
```

Every test gets a completely fresh schema — tables are built before the
test runs and dropped after. No test can see data left behind by another
test, which matters because several tests below create students/courses
with hardcoded names; without this, a second run of the same test file
would start colliding with leftover rows instead of testing cleanly.

**Note:** `drop_all` removes tables, not the `test.db` file itself — the
file persists (empty) between full test runs. Not a bug, just worth knowing
if you're wondering why `test.db` shows up on disk after running pytest.
It's in `.gitignore` either way.

### What's covered

| Test | File | What it actually verifies |
|---|---|---|
| `test_create_student` | `test_students.py` | `POST /students` returns `201` and echoes back the submitted fields plus a generated `id` |
| `test_create_enrollment_invalid_course_returns_404` | `test_enrollments.py` | a nonexistent `course_id` is rejected with `404`, not silently accepted (this is the regression test for the `AttributeError` bug above) |
| `test_invalid_student_404` | `test_enrollments.py` | same check, mirrored for a nonexistent `student_id` |
| `test_duplicate_enrollment_409` | `test_enrollments.py` | enrolling a real student in a real course twice returns `201` the first time, `409` the second |
| `test_gpa_correctness` | `test_transcript.py` | the credit-weighted GPA formula, checked against an independently computed expected value — not just re-checked by eye like the original manual verification |
| `test_empty_list_200` | `test_transcript.py` | a student with zero enrollments gets `200` + `[]` from `/students/{id}/enrollments`, not `404` — this is the deliberate REST decision from earlier in this README, now enforced by a test instead of just documented |

A couple of these went through a wrong version before landing correctly,
worth noting since it's the same kind of mistake as the isolation problem
above: `test_duplicate_enrollment_409` originally reused a hardcoded
`student_id: 1` instead of the `id` actually returned by the setup POST —
worked by coincidence on a fresh DB where autoincrement starts at 1, but
was testing an assumption, not a fact. Fixed by reading the real `id` out
of the setup response, same pattern as everywhere else in the suite.

`test_gpa_correctness` also went through a version that hardcoded the
expected GPA as a truncated decimal (`8.571428571`) and compared with `==`
— which is fragile against floating point, since the endpoint's computed
value and a hand-typed decimal aren't guaranteed to match bit-for-bit.
Fixed with `pytest.approx()` against a value computed in the test itself
(`60/7`) rather than transcribed by hand.

### Running it

```bash
pytest
```

All 6 tests pass. Deprecation warnings shown on run (`httpx`/`starlette`,
Pydantic v1-style `class Config`) are noted but not fixed yet — neither
affects correctness, both are candidates for cleanup before this goes
further.

---

## Repo

`.gitignore` excludes `venv/`, `grades.db`, `test.db`, and `__pycache__/` —
confirmed via `git status` that none of these show up as untracked before
the first commit.
