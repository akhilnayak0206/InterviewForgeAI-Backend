# Database Layer And Alembic Workflow

This project uses SQLModel for Python models, SQLAlchemy for the engine and sessions, PostgreSQL as the database, and Alembic as the only mechanism for schema creation and schema evolution.

## 1. Engine Setup

### Goal
Create one production-style SQLAlchemy engine that the app uses for database connections.

### Concepts Covered
Engine, connection pool, PostgreSQL URL, health checks, sync-now/async-later architecture.

### Architecture
`app/core/database.py` owns the engine. It does not import models and does not create tables.

### Folder Structure
```text
app/
  core/
    config.py
    database.py
```

### Step-by-Step Implementation
1. Read `DATABASE_URL` from settings.
2. Create the SQLAlchemy engine once at import time.
3. Enable `pool_pre_ping=True` so stale pooled connections are checked before use.
4. Keep SQL logging controlled by `DB_ECHO`.

### Code
See [app/core/database.py](/home/akhil/Desktop/code/InterviewForgeAI/interviewforgeai_backend/app/core/database.py).

### Explanation
The engine is the process-level database connectivity object. It manages a connection pool, but it is not a request transaction and it is not a model registry.

### Common Mistakes
Calling `SQLModel.metadata.create_all(engine)` here couples application startup to schema creation. That is convenient in demos and dangerous in production.

### Production Insights
Production services usually start against an already-migrated database. Deployment runs migrations separately, then app instances boot.

### Next Step
Use the engine through request-scoped sessions, not directly in route handlers.

## 2. Session Management

### Goal
Create one database session per request and close it reliably.

### Concepts Covered
Session, transaction boundary, dependency injection, `autoflush`, `expire_on_commit`.

### Architecture
`app/db/session.py` exposes `SessionLocal` and `get_db()`.

### Folder Structure
```text
app/
  db/
    session.py
```

### Step-by-Step Implementation
1. Bind `sessionmaker` to the shared engine.
2. Use SQLModel's `Session` class.
3. Yield the session from a FastAPI dependency.
4. Let the context manager close the session after the request.

### Code
See [app/db/session.py](/home/akhil/Desktop/code/InterviewForgeAI/interviewforgeai_backend/app/db/session.py).

### Explanation
A session is a unit-of-work object. Routes and services use it to query and persist models. The session should be short-lived; the engine should be long-lived.

### Common Mistakes
Using a global session object across requests causes transaction leaks, stale data, and cross-request concurrency bugs.

### Production Insights
Real teams often commit in service functions or route handlers after a complete business operation. Rollbacks are handled on exceptions.

### Next Step
Inject `Session` into routes with `Depends(get_db)`.

## 3. Base Model Setup

### Goal
Keep common model fields reusable without hiding table definitions.

### Concepts Covered
UUID primary keys, timezone-aware timestamps, reusable mixins, enum values stored as strings.

### Architecture
`app/models/base.py` contains reusable model mixins and shared enums. Table models stay in their own modules.

### Folder Structure
```text
app/
  models/
    base.py
    user.py
    session.py
    message.py
```

### Step-by-Step Implementation
1. Use PostgreSQL UUID columns with Python `uuid.UUID`.
2. Use UTC-aware Python timestamps.
3. Use database-side `now()` as the server default.
4. Keep enums in `base.py` to avoid circular imports.

### Code
See [app/models/base.py](/home/akhil/Desktop/code/InterviewForgeAI/interviewforgeai_backend/app/models/base.py).

### Explanation
The mixins reduce duplication for `id`, `created_at`, and `updated_at`. They use SQLModel `Field(...)` metadata so each table gets its own column object.

### Common Mistakes
Putting raw SQLAlchemy `Column(...)` objects directly in reusable SQLModel mixins can accidentally reuse the same column object across multiple tables.

### Production Insights
UUIDs are useful when IDs are exposed externally, generated across services, or created before a database round trip.

### Next Step
Add new shared fields only when at least two real models need them.

## 4. Alembic Initialization

### Goal
Make Alembic the source of truth for database schema changes.

### Concepts Covered
`alembic.ini`, `env.py`, revisions, upgrade, downgrade, autogenerate.

### Architecture
Alembic lives outside the app package and imports app metadata only when generating or running migrations.

### Folder Structure
```text
alembic/
  env.py
  script.py.mako
  versions/
alembic.ini
```

### Step-by-Step Implementation
1. Add Alembic as a project dependency.
2. Configure `alembic.ini` with `script_location = alembic`.
3. Configure `env.py` to read `settings.DATABASE_URL`.
4. Point `target_metadata` at `SQLModel.metadata`.
5. Enable type and server-default comparison.

### Code
See [alembic/env.py](/home/akhil/Desktop/code/InterviewForgeAI/interviewforgeai_backend/alembic/env.py).

### Explanation
Autogenerate works by comparing two things: the database schema and the in-memory SQLModel metadata. If a model is not imported, it is not in metadata, so Alembic cannot see it.

### Common Mistakes
Leaving `target_metadata = None` means Alembic cannot autogenerate model-based migrations.

### Production Insights
Alembic revisions are committed to git and reviewed like application code.

### Next Step
Run `uv run alembic upgrade head` against your PostgreSQL database.

## 5. Model Discovery And Metadata Registration

### Goal
Ensure all table models are visible to Alembic.

### Concepts Covered
Python imports, SQLModel metadata, table registration, import side effects.

### Architecture
`app/models/__init__.py` imports every table model. `app/db/base.py` imports `app.models`.

### Folder Structure
```text
app/
  db/
    base.py
  models/
    __init__.py
```

### Step-by-Step Implementation
1. Define each model class with `table=True`.
2. Export every table model from `app/models/__init__.py`.
3. Import `app.db.base` in Alembic `env.py`.
4. Read `SQLModel.metadata.tables` only after those imports happen.

### Code
See [app/db/base.py](/home/akhil/Desktop/code/InterviewForgeAI/interviewforgeai_backend/app/db/base.py) and [app/models/__init__.py](/home/akhil/Desktop/code/InterviewForgeAI/interviewforgeai_backend/app/models/__init__.py).

### Explanation
SQLModel registers a table when Python imports the class definition. Alembic does not scan files from disk by itself.

### Common Mistakes
Creating `app/models/payment.py` but forgetting to import `Payment` from `app/models/__init__.py`. Alembic then thinks the table does not exist.

### Production Insights
Many teams use a single model-registration module so import behavior stays explicit and predictable.

### Next Step
When adding a model, update `app/models/__init__.py` in the same commit.

## 6. First Migration

### Goal
Create the initial database schema through Alembic.

### Concepts Covered
Initial revision, table creation, indexes, foreign keys, `alembic_version`.

### Architecture
The first revision creates `users`, `interview_sessions`, and `messages`.

### Folder Structure
```text
alembic/
  versions/
    20260517_0001_initial_schema.py
```

### Step-by-Step Implementation
1. Generate a revision in normal development with `uv run alembic revision --autogenerate -m "initial schema"`.
2. Review the generated code.
3. Fix anything Alembic cannot infer correctly.
4. Commit the migration file.

### Code
See [alembic/versions/20260517_0001_initial_schema.py](/home/akhil/Desktop/code/InterviewForgeAI/interviewforgeai_backend/alembic/versions/20260517_0001_initial_schema.py).

### Explanation
The migration is executable history. It tells PostgreSQL exactly how to move from no app schema to the first app schema.

### Common Mistakes
Treating autogenerate as magic. It is a draft generator, not a substitute for review.

### Production Insights
Real teams inspect migrations for table locks, data backfills, defaults, nullable changes, and rollback behavior.

### Next Step
Apply it locally with `uv run alembic upgrade head`.

## 7. Migration Execution Flow

### Goal
Understand what happens when migrations run.

### Concepts Covered
`upgrade head`, transaction, revision graph, `alembic_version`.

### Architecture
Alembic connects to PostgreSQL, checks the current revision in `alembic_version`, and runs missing upgrades in order.

### Folder Structure
```text
alembic.ini
alembic/env.py
alembic/versions/
```

### Step-by-Step Implementation
1. Set `DATABASE_URL` in `.env`.
2. Run `uv run alembic current` to see the applied revision.
3. Run `uv run alembic upgrade head`.
4. Run `uv run alembic current` again.

### Code
```bash
uv run alembic current
uv run alembic upgrade head
uv run alembic history
```

### Explanation
The app does not create tables on startup. The migration command changes the schema before the app uses it.

### Common Mistakes
Running the app before migrations and then debugging missing-table errors in route code.

### Production Insights
CI/CD pipelines usually run migrations as a deploy step before rolling out new application containers.

### Next Step
Add migration execution to your deployment checklist.

## 8. Request And DB Flow

### Goal
Understand how a FastAPI request touches the database.

### Concepts Covered
FastAPI dependency, session scope, services, commit, rollback, response.

### Architecture
Routes receive a session from `get_db()` and pass it to service functions.

### Folder Structure
```text
app/
  routes/
  services/
  db/session.py
```

### Step-by-Step Implementation
1. Request enters FastAPI.
2. FastAPI resolves `Depends(get_db)`.
3. Route calls service logic with the session.
4. Service queries or mutates models.
5. Code commits after a successful business operation.
6. The dependency closes the session.

### Code
```python
from fastapi import Depends
from sqlmodel import Session

from app.db.session import get_db


def route_handler(db: Session = Depends(get_db)):
    ...
```

### Explanation
This keeps HTTP concerns in routes and database/business concerns in services.

### Common Mistakes
Creating sessions inside random helper functions. That makes transaction boundaries hard to reason about.

### Production Insights
One request can use one transaction for a coherent business operation.

### Next Step
Build services that accept `db: Session` as an argument.

## 9. Schema Evolution Workflow

### Goal
Change the database safely as models evolve.

### Concepts Covered
Autogenerate, review, upgrade, downgrade, expand/contract changes.

### Architecture
Every schema change has a model change and a migration change.

### Folder Structure
```text
app/models/
alembic/versions/
```

### Step-by-Step Implementation
1. Edit a SQLModel model.
2. Run `uv run alembic revision --autogenerate -m "describe change"`.
3. Review and adjust the migration.
4. Run `uv run alembic upgrade head` locally.
5. Test the app.
6. Commit model and migration together.

### Code
```bash
uv run alembic revision --autogenerate -m "add user last_login_at"
uv run alembic upgrade head
```

### Explanation
Models describe desired application shape. Migrations describe how to move real databases between shapes.

### Common Mistakes
Changing a model without a migration. The app and database then disagree.

### Production Insights
For risky changes, teams split work into expand, backfill, switch code, and contract migrations.

### Next Step
Use this workflow for every schema change, even locally.

## 10. Why `create_all()` Is Avoided

### Goal
Avoid hidden, uncontrolled schema changes.

### Concepts Covered
Schema drift, migration history, rollbacks, deploy safety.

### Architecture
The app starts and verifies connectivity. Alembic changes schema.

### Folder Structure
`app/db/init_db.py` was removed because table creation scripts are not part of the production flow.

### Step-by-Step Implementation
1. Do not call `SQLModel.metadata.create_all()`.
2. Do not create tables during app startup.
3. Use Alembic revisions for every schema change.

### Code
```bash
uv run alembic upgrade head
```

### Explanation
`create_all()` creates missing tables, but it does not manage table alterations, data migrations, indexes safely, deployment ordering, or rollback history.

### Common Mistakes
Using `create_all()` in development and Alembic in production. That creates two sources of truth.

### Production Insights
Real databases contain data. Schema changes must be intentional, reviewed, repeatable, and observable.

### Next Step
Keep migrations as the only schema-management path.

