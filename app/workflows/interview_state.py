"""
Interview Workflow State
=========================

This TypedDict is the **single source of truth** for the entire interview.

State evolves across multiple turns:
    Turn 1: resume → analysis → skills → difficulty → question → PAUSE
    Turn 2: answer → evaluation → feedback → question → PAUSE
    ...
    Turn N: answer → evaluation → feedback → report → END

Key design decisions:
    - `total=False` so we can invoke with only the fields available at that turn
    - `Annotated[list, operator.add]` for lists that accumulate across turns
    - `current_*` fields are overwritten each turn (working memory)
    - `questions_asked` / `scores` accumulate (history)
"""

from __future__ import annotations

import operator
from typing import Annotated, Required, TypedDict


class InterviewState(TypedDict, total=False):
    """
    Production interview workflow state.

    Split into logical sections:
        Identity   - who is this, which session
        Resume     - analyzed once on first turn
        Config     - interview parameters
        Current    - working memory for this turn (overwritten each turn)
        History    - accumulated across all turns (uses reducers)
        Final      - set on the last turn
        Control    - routing and error handling
    """

    # — Identity (set once by the API route) —
    session_id: Required[str]
    user_id: Required[str]

    # — Resume Analysis (set on first turn, read on all turns) —
    resume_text: str
    resume_analysis: str
    skills: list[str]
    difficulty: str

    # -- Retrieved Context (set by retrieve_context node, read by LLM nodes) --
    # Populated from vector search over the user's indexed documents.
    # Empty string when no documents are indexed (graceful fallback).
    resume_context: str
    jd_context: str

    # — Interview Configuration —
    max_questions: int
    question_number: int

    # — Current Turn (overwritten each turn) —
    current_question: str
    current_answer: str
    current_evaluation: str
    current_score: int
    current_feedback: str

    # — History (accumulated across turns via reducers) —
    questions_asked: Annotated[list[str], operator.add]
    scores: Annotated[list[int], operator.add]

    # — Final Output —
    final_report: str
    is_complete: bool

    # — Control Flow —
    is_first_turn: bool
    error: str
