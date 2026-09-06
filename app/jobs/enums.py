"""Job system enums — types of work and lifecycle states.

JobType: what kind of work the job performs.
    Add a new value here whenever you introduce a new background task.
    The worker uses this to dispatch to the correct handler function.

JobStatus: where the job is in its lifecycle.
    Follows the state machine described in Part 4:

        PENDING → RUNNING → COMPLETED
                          ↘ FAILED → (retry) → PENDING
                                  ↘ DEAD (max attempts exceeded)
"""

from enum import StrEnum


class JobType(StrEnum):
    """Registered background job types.

    Each value maps to a task function in app.jobs.tasks.
    """

    embed_document = "embed_document"


class JobStatus(StrEnum):
    """Job lifecycle states.

    State transitions:
        pending   → running     (worker picks up the job)
        running   → completed   (job succeeds)
        running   → failed      (job throws an exception)
        failed    → pending     (automatic retry, if attempts < max_attempts)
        failed    → dead        (max attempts exceeded, no more retries)
    """

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    dead = "dead"
