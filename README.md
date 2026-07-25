# Grade Tracking API

A FastAPI + SQLAlchemy backend for tracking student enrollments and computing
credit-weighted GPA. Built to be defensible in a technical interview — every
schema decision below was made deliberately, not defaulted to.

---

## Stack

- **FastAPI** — HTTP framework, request validation, auto-generated `/docs`
- **SQLAlchemy (ORM)** — models, relationships, query building
- **SQLite** — storage (file: `grades.db`), swappable for Postgres later by
  changing `DATABASE_URL` in `database.py`
- **Uvicorn** — ASGI server that actually runs the app

---

## Project structure

```
sql-backend/
├── database.py     # engine, session factory, Base, get_db() dependency — nothing else
├── models.py       # SQLAlchemy models: Student, Course, Enrollment
├── schemas.py      # Pydantic request/response models — see "Request/response validation" below
├── main.py         # FastAPI app + all route handlers
├── conftest.py     # pytest fixtures: isolated test DB, TestClient, dependency override
├── test_students.py
├── test_enrollments.py
├── test_transcript.py
├── requirements.txt
├── .gitignore      # excludes venv/, grades.db, test.db, __pycache__/ from version control
└── grades.db        # SQLite file, created automatically on first run (not committed)
```

**Why split `database.py` from `main.py`?** Single responsibility. `database.py`
only knows how to connect to the DB — it has no side effects and can be
imported anywhere (including a future test suite) without doing anything.
`main.py` owns HTTP routing and is the natural place to trigger schema
creation on startup.

---

## Running it

```bash
python -m venv venv
venv\Scripts\Activate.ps1        # Windows PowerShell
# source venv/bin/activate       # Mac/Linux

pip install -r requirements.txt
uvicorn main:app --reload
```

Then open `http://127.0.0.1:8000/docs` for the interactive Swagger UI —
every endpoint can be tested from there without writing a separate client.

---

## Schema

### `Student`
| Column | Type | Notes |
|---|---|---|
| id | int, PK | auto-increment |
| name | string | |
| email | string | unique |

### `Course`
| Column | Type | Notes |
|---|---|---|
| id | int, PK | auto-increment |
| code | string | unique, e.g. `"CS304"` |
| title | string | |
| credits | int | drives GPA weighting |

### `Enrollment` (join table between Student and Course)
| Column | Type | Notes |
|---|---|---|
| id | int, PK | auto-increment |
| student_id | int, FK → students.id | `ondelete="CASCADE"` |
| course_id | int, FK → courses.id | |
| grade | float, nullable | null until graded |

`UniqueConstraint(student_id, course_id)` — a student can only have **one**
enrollment row per course.

**Design choice: one grade per course**, not per-assignment. Assignment-level
grades would need a fourth table (`Assignment`, FK to `Enrollment` or
`Course`) and a rollup rule (weighted by assignment weight?) — deliberately
out of scope for this version. If asked "how would you extend this," that's
the answer.

---

## Design decisions (the part that matters in an interview)

### 1. Why a unique constraint on `(student_id, course_id)` instead of allowing duplicates?

An enrollment represents "this student is taking this course." A student
enrolling in the same course twice isn't a new fact, it's either a duplicate
request (double-submit) or a bug on the client side. The constraint makes
the *database* — not application code — the source of truth for that rule,
so it holds even if some other part of the codebase forgets to check.

**Alternative considered: upsert instead of reject.** Rejected because
silently overwriting an existing enrollment on a duplicate POST would hide
a double-submit bug instead of surfacing it. Reject-with-409 is standard
REST practice for this exact situation.

**How it's implemented:** SQLite raises `IntegrityError` when the constraint
is violated. The endpoint catches it, rolls back the session (see below for
why that's required), and returns `409 Conflict` with a message — not a
500, which would look like a server bug rather than an expected outcome.

```python
try:
    db.commit()
except IntegrityError:
    db.rollback()
    raise HTTPException(status_code=409, detail="Student already enrolled in this course")
```

**Why `db.rollback()` before raising the exception:** after a failed
`commit()`, the SQLAlchemy session is left in a broken/pending state — it
can't be reused for further queries until it's rolled back. Skipping the
rollback would leave the session unusable for the rest of the request (or
corrupt the next request if the session were reused).

**Why catch `IntegrityError` specifically, not a bare `except:`:** a bare
except would silently swallow *any* error — a real bug, a connection
failure, anything — and misreport it as "already enrolled." Catching the
specific exception means only the constraint violation gets this treatment;
everything else still surfaces as a real 500 with a real traceback.

### 2. Why `ondelete="CASCADE"` on `Enrollment.student_id`?

An enrollment has no meaning independent of the student it belongs to — it's
dependent data, not standalone data. If a student is deleted, their
enrollment records become orphaned rows pointing at a student that no longer
exists, which is worse than deleting them.

**Contrast (worth stating in an interview to show you understand the
trade-off, not just the rule):** this is *not* universally correct for every
FK relationship. An `Order` referencing a `Customer`, for example, might
deliberately **not** cascade-delete, because a business may need to keep
financial/order history even after a customer account is removed. The
correct choice depends on whether the child record is meaningful without
the parent — here, it isn't, so cascade is right.

### 3. Why credit-weighted GPA instead of a flat average?

A flat average of grades treats a 1-credit seminar the same as a 4-credit
core course, which doesn't match how real transcripts compute GPA. Formula:

```
GPA = Σ(grade_i × credits_i) / Σ(credits_i)
```

**Implementation** — SQLAlchemy query, mapped directly from the SQL below:

```sql
SELECT SUM(e.grade * c.credits) / SUM(c.credits) AS gpa
FROM enrollments e
JOIN courses c ON e.course_id = c.id
WHERE e.student_id = :student_id;
```

```python
result = (
    db.query(func.sum(Enrollment.grade * Course.credits) / func.sum(Course.credits))
    .select_from(Enrollment)
    .join(Course, Enrollment.course_id == Course.id)
    .filter(Enrollment.student_id == student_id)
    .scalar()
)
```

- `func.sum(...)` maps to SQL's `SUM(...)` — this is how SQLAlchemy calls
  aggregate functions.
- `.select_from(Enrollment)` is required because the `SELECT` clause here
  contains only aggregate expressions (`func.sum(...)`), with no mapped
  entity directly named. Without it, SQLAlchemy can't infer which table the
  query's `FROM` should start at, and `.join()` fails with
  `"Don't know how to join to <Course>"` — hit this exact error while
  building this project; the fix is forcing the starting table explicitly.
- `.scalar()` (not `.first()`) because the query returns exactly one column,
  one row — `.scalar()` unwraps that directly to the raw number instead of
  a tuple-like row object.

**Verified by hand:** queried the raw `enrollments`/`courses` rows for a
test student directly via SQLite, computed the weighted average manually,
and confirmed it matched the endpoint's output before trusting the query.
Later re-verified automatically by `test_gpa_correctness` (see Test suite
below) against an independently computed expected value.

### 4. GPA storage: query-time vs. denormalized column

**Chose:** query-time aggregation (the query above), computed fresh on every
request to `/students/{id}/transcript`.

**Alternative considered:** a denormalized `gpa` column on `Student`,
updated whenever a grade changes.

**Why query-time won out for this project:** a denormalized column is only
worth its complexity if reads are frequent/expensive relative to writes, or
the aggregation itself is costly (large joins, big datasets). For a project
this size, the real cost of denormalization is the sync problem — every
single grade write has to remember to also update the `Student.gpa` column,
or the transcript silently goes stale and reports a wrong GPA with no error
raised anywhere. Query-time aggregation is always correct by construction;
there's no second write to forget. Trade-off is a marginally heavier read,
which is irrelevant at this scale.

**If asked "how would you scale this":** that's exactly when denormalization
becomes worth it — and the answer would be to update the `gpa` column
inside `update_grade()` (the `PATCH /enrollments/{id}` handler) at the same
time the grade itself is written, so the two never drift apart, possibly
backed by a SQLAlchemy event listener so the sync can't be bypassed by
some other code path.

### 5. Why grade is stored as `float`, not letter grade

Storing grade points directly (e.g. `3.7`) avoids needing a
letter-grade-to-points mapping table or conversion logic at query time — the
GPA formula can use the stored value directly.

**Scale: 0.0–10.0**, matching SASTRA's CGPA system (not the 4.0 scale used
by US institutions — a real domain assumption, worth stating explicitly if
asked "why 10 and not 4").

**Range validation added after catching a live bug, not proactively:**
initially shipped with no bounds check, and manually testing the API
surfaced grades of `8.99`, `7.67`, and `9.7` being accepted with no
constraint originally intended to be ≤ 10 either way — good enough by luck,
but nothing was stopping an out-of-range value like `12` from being stored.
Fixed with a Pydantic validator on `EnrollmentUpdate`:

```python
from pydantic import BaseModel, field_validator

class EnrollmentUpdate(BaseModel):
    grade: float

    @field_validator("grade")
    @classmethod
    def grade_in_range(cls, v):
        if not (0.0 <= v <= 10.0):
            raise ValueError("grade must be between 0.0 and 10.0")
        return v
```

Verified both directions: `grade: 12` → `422` with a clear message,
`grade: 9.7` → `200`, confirmed via `/docs`.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/students` | create a student — JSON body (`StudentCreate`), validated (e.g. `email` must be a real email format), returns `201` |
| POST | `/courses` | create a course — JSON body (`CourseCreate`), returns `201` |
| POST | `/enrollments` | enroll a student in a course — JSON body (`EnrollmentCreate`), `404` if the student or course doesn't exist, `409` on duplicate, `201` on success |
| PATCH | `/enrollments/{id}` | set/update a grade — JSON body (`EnrollmentUpdate`), 404 if enrollment doesn't exist |
| GET | `/students` | list all students |
| GET | `/students/{id}` | get one student — 404 if missing |
| GET | `/students/{id}/enrollments` | that student's enrollments, joined with course info — 404 only if the student itself doesn't exist, **200 with `[]` if they exist but have no enrollments** |
| GET | `/students/{id}/transcript` | credit-weighted GPA for a student — 404 if no grades |
| GET | `/courses` | list all courses |
| DELETE | `/students/{id}` | delete a student — cascades to their enrollments |

---

## Request/response validation with Pydantic (`schemas.py`)

Every endpoint that takes writeable input or returns a plain ORM object goes
through a Pydantic schema, not raw query params or raw SQLAlchemy objects.
This was added after the endpoints were already working end-to-end with
plain `str`/`int`/`float` function parameters — worth noting *why* it's a
real change, not just a formality:

**Before:** `def create_student(name: str, email: str, ...)` — FastAPI reads
these as URL **query parameters** (`POST /students?name=...&email=...`).
Functional, but wrong shape for a POST — no structured body, no validation
beyond "is it a string."

**After:** `def create_student(student_in: StudentCreate, ...)` — because the
parameter's type is a Pydantic `BaseModel`, FastAPI switches to reading a
**JSON request body** instead, and runs full validation against the schema
before the endpoint function ever executes.

### Two schema classes per entity

- `XCreate` — what the client sends (no `id`, the DB assigns that)
- `XOut` — what's sent back (`response_model=XOut` on the route), including
  `id`. Uses `class Config: from_attributes = True` so Pydantic can build
  the response by reading `.attribute` access on a SQLAlchemy object
  (`student.name`) instead of expecting a plain dict.

`Enrollment` needed a third, `EnrollmentUpdate` (`grade: float` only), for
`PATCH /enrollments/{id}` — separate from `EnrollmentCreate` since a client
creating an enrollment never sends a grade (that's PATCH-only, set after the
fact), and separate from `EnrollmentOut` since update input and full-record
output aren't the same shape.

### A mistake worth keeping: `EnrollmentOut` originally included `title` and
`credits`

Those fields don't exist on `Enrollment` — they live on `Course`. Since
`from_attributes = True` reads via attribute access, and a raw `Enrollment`
object has no `.title`, this would crash with `AttributeError` the moment
FastAPI tried to build the response. Fixed by keeping `EnrollmentOut` to
only the fields `Enrollment` actually has (`id`, `student_id`, `course_id`,
`grade`) — course details, when needed (e.g.
`GET /students/{id}/enrollments`), are built as a plain dict in the endpoint
instead, not forced through a schema that doesn't match the underlying
object.

### Dependency note

`EmailStr` (used in `StudentCreate`) requires the optional `email-validator`
package, not installed by default with Pydantic:

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

### Why an empty enrollment list returns `200 []`, not `404`

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

## Not done yet / possible next steps

- Migrate Pydantic schemas off the v1-style `class Config` to
  `model_config = ConfigDict(...)` before Pydantic V3 removes the old style
  entirely
- `.env` / config separation for `DATABASE_URL`, mainly relevant if/when
  this gets deployed rather than run locally
- Optional: live deployment (Render/Railway)
