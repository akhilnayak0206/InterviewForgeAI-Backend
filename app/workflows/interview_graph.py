"""
Interview Workflow Graph — Production
======================================

This file defines the structure of the multi-turn interview workflow.

WORKFLOW:

      START
        │
        ▼
    load_session
        │
        ▼
    retrieve_context → route_by_turn
              │
        ┌─────┴─────┐
        ▼           ▼
    FIRST TURN   SUBSEQUENT TURN
        │           │
    analyze_resume   evaluate_answer
        │           │
    extract_skills   generate_feedback
        │           │
    determine_difficulty
        │           │
        └─────┬─────┘
              ▼
        should_continue
              │
        ┌─────┴─────┐
        ▼           ▼
     CONTINUE      FINISH
        │           │
    generate_question   generate_report
        │           │
    persist_question    persist_results
        │           │
    wait_for_answer      END
        │
    INTERRUPT
    (pauses, returns question)

CHECKPOINTING:
    The graph is compiled with a PostgreSQL checkpointer so state
    persists between turns. Each session_id is used as the thread_id.

HUMAN-IN-THE-LOOP:
    The `wait_for_answer` node calls `interrupt()` which pauses the
    graph and returns control to the API. When the user submits an
    answer, the API calls `graph.ainvoke(Command(resume=answer))`.
"""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from app.workflows.interview_nodes import (
    analyze_resume,
    determine_difficulty,
    evaluate_answer,
    extract_skills,
    generate_feedback,
    generate_question,
    generate_report,
    load_session,
    persist_question,
    persist_results,
    retrieve_context,
    route_by_turn,
    should_continue,
    wait_for_answer,
)
from app.workflows.interview_state import InterviewState

logger = logging.getLogger(__name__)


def build_interview_workflow() -> StateGraph:
    """
    Build the StateGraph (uncompiled) for the interview workflow.

    Returns the uncompiled workflow so the caller can compile it
    with the appropriate checkpointer.
    """

    workflow = StateGraph(InterviewState)

    # — Nodes ——————————————————————————

    # DB nodes
    workflow.add_node("load_session", load_session)
    workflow.add_node("persist_question", persist_question)
    workflow.add_node("persist_results", persist_results)

    # RAG node - retrieves document context before LLM nodes
    workflow.add_node("retrieve_context", retrieve_context)

    # LLM nodes — first turn
    workflow.add_node("analyze_resume", analyze_resume)
    workflow.add_node("extract_skills", extract_skills)
    workflow.add_node("determine_difficulty", determine_difficulty)

    # LLM nodes — every turn
    workflow.add_node("generate_question", generate_question)

    # LLM nodes — subsequent turns
    workflow.add_node("evaluate_answer", evaluate_answer)
    workflow.add_node("generate_feedback", generate_feedback)

    # LLM nodes — final turn
    workflow.add_node("generate_report", generate_report)

    # Control nodes
    workflow.add_node("wait_for_answer", wait_for_answer)

    # — Edges ——————————————————————————

    # Entry: START -> load_session -> retrieve_context -> route
    workflow.add_edge(START, "load_session")
    workflow.add_edge("load_session", "retrieve_context")

    # Conditional: route by turn type (after retrieval)
    workflow.add_conditional_edges(
        "retrieve_context",
        route_by_turn,
        {
            "first_turn": "analyze_resume",
            "subsequent_turn": "evaluate_answer",
        },
    )

    # Conditional: route by turn type
    workflow.add_conditional_edges(
        "load_session",
        route_by_turn,
        {
            "first_turn": "analyze_resume",
            "subsequent_turn": "evaluate_answer",
        },
    )

    # First turn path: analyze → extract → difficulty → should_continue
    workflow.add_edge("analyze_resume", "extract_skills")
    workflow.add_edge("extract_skills", "determine_difficulty")
    workflow.add_edge("determine_difficulty", "generate_question")

    # Subsequent turn path: evaluate → feedback → should_continue
    workflow.add_edge("evaluate_answer", "generate_feedback")

    # After feedback, decide whether to continue or finish
    workflow.add_conditional_edges(
        "generate_feedback",
        should_continue,
        {
            "continue": "generate_question",
            "finish": "generate_report",
        },
    )

    # Question path: generate → persist → wait for answer (interrupt)
    workflow.add_edge("generate_question", "persist_question")
    workflow.add_edge("persist_question", "wait_for_answer")

    # After user answers, go back to load_session to start the next turn
    workflow.add_edge("wait_for_answer", "load_session")

    # Finish path: report → persist → END
    workflow.add_edge("generate_report", "persist_results")
    workflow.add_edge("persist_results", END)

    return workflow
