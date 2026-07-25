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
pip install pydantic[email]
```

Hit `ImportError: email-validator is not installed` on first run after
adding `EmailStr` — this is why. Captured correctly in `requirements.txt`
since it was installed before that file was regenerated.

### Verified with a real rejected request, not just assumed

Tested `POST /students` with `{"email": "not-an-email"}` and confirmed a
`422 Unprocessable Content` with a specific message
(`"An email address must have an @-sign"`) — rejected by Pydantic before
`create_student`'s body ever ran, never touched the database.

### 7. Why an empty enrollment list returns `200 []`, not `404`

`GET /students/{id}/enrollments` initially raised a 404 when the result list
was empty. That's wrong, and worth stating precisely why: a 404 should mean
"this URL doesn't resolve to a resource" — it's a statement about the
**resource's existence**, not about how much data is in it. A student who
exists but hasn't enrolled in anything yet is a completely normal state
(e.g. a freshman right after registering), not an error condition.

Conflating "empty" with "not found" pushes a burden onto every client of
this API: they'd have to inspect the 404's body to figure out whether it
means "bad student_id, something's actually wrong" or "valid student, just
no data yet" — which defeats the purpose of using status codes to carry
meaning at all.

**Rule applied:** 404 is reserved for cases where the *path itself* doesn't
resolve (student_id doesn't exist). Once the resource is confirmed to
exist, its contents — even zero items — are a normal `200` response.

---

## Things that broke while building this (kept deliberately — this is the
real debugging trail, and it's more interview-relevant than a clean
success story)

1. **`KeyError: 'Enrollement'`** — typo in a `relationship("Enrollment", ...)`
   string argument in `models.py`. SQLAlchemy resolves relationship targets
   by string name against a registry of defined classes (deferred lookup,
   since the target class may not be defined yet at the point the string is
   written) — a misspelled string fails silently until a mapper actually
   tries to configure itself.
2. **`InvalidRequestError: Don't know how to join to <Course>`** — the
   transcript query's `SELECT` contained only aggregate expressions with no
   named entity, so SQLAlchemy had no `FROM` to anchor the join to. Fixed
   with `.select_from(Enrollment)`.
3. **Pylance "cannot assign float to Column[Unknown]"** on
   `enrollment.grade = grade` — a static-analysis false positive, not a
   runtime bug. `Column` objects are the class-level type; SQLAlchemy's
   instrumentation makes instance-level access return the real value, which
   Pylance's type checker doesn't model. Real fix (optional): migrate models
   to SQLAlchemy 2.0's `Mapped[]` / `mapped_column()` syntax, which types
   correctly for static analysis.
4. **`AttributeError: 'NoneType' object has no attribute 'id'`** in
   `get_student_enrollments` — traced back to `POST /enrollments` silently
   accepting a `course_id` that didn't exist in the `courses` table. Root
   cause: **SQLite does not enforce foreign key constraints by default**,
   even though `ForeignKey("courses.id")` is declared in `models.py` — that
   declaration is metadata SQLAlchemy understands, not automatically
   enforced by SQLite unless FK enforcement is turned on per-connection.
   So an enrollment with a nonexistent `course_id` was created with no
   error, and later `enrollment.course` (a lazy-loaded relationship) came
   back `None`, crashing on `.id` access. Found this by manually testing
   `POST /enrollments` with a bad `course_id`, not from a prompted test case.

   **Fix, two layers (both worth having):**
   - **Application-level (primary fix):** `create_enrollment` now checks
     that both `student_id` and `course_id` exist before creating the row,
     returning a clean `404` instead of allowing bad data in:
     ```python
     course = db.query(Course).filter(Course.id == enrollment_in.course_id).first()
     if not course:
         raise HTTPException(status_code=404, detail="Course not found")
     ```
   - **Database-level (defense in depth):** SQLite FK enforcement turned on
     explicitly via a connection event listener in `database.py`:
     ```python
     from sqlalchemy import event

     @event.listens_for(engine, "connect")
     def set_sqlite_pragma(dbapi_connection, connection_record):
         cursor = dbapi_connection.cursor()
         cursor.execute("PRAGMA foreign_keys=ON")
         cursor.close()
     ```
     With this on, SQLite itself would reject the bad insert even if the
     application check were ever removed or bypassed — the same
     `IntegrityError` type as the duplicate-enrollment case, so the
     `except IntegrityError` block in `create_enrollment` now has to be
     understood as covering two distinct causes (duplicate PK vs. bad FK),
     not just one.
