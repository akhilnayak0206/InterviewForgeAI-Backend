"""
Interview Workflow Nodes — Production
=======================================

Each function is a node in the LangGraph interview workflow.

Node contract:
    - Input:  the full InterviewState (read only what you need)
    - Output: a partial dict of ONLY the keys to update
    - NEVER mutate the input state
    - NEVER call other nodes directly
    - Use `get_workflow_llm()` for the LLM — never hardcode a provider

Node categories:
    - LLM nodes:     call the LLM (async, retriable)
    - DB nodes:      read/write the database (sync side effects)
    - Control nodes: routing decisions, interrupts (pure logic)
"""

from __future__ import annotations

import logging
import re
import uuid

from langgraph.types import interrupt
from sqlmodel import select

from app.db.session import SessionLocal
from app.documents.models import DocumentType
from app.models.base import MessageRole, SessionStatus
from app.models.message import Message
from app.models.session import InterviewSession
from app.prompts.workflow_prompts import (
    ANALYZE_RESUME_PROMPT,
    DETERMINE_DIFFICULTY_PROMPT,
    EVALUATE_ANSWER_PROMPT,
    EXTRACT_SKILLS_PROMPT,
    GENERATE_FEEDBACK_PROMPT,
    GENERATE_QUESTION_PROMPT,
    GENERATE_REPORT_PROMPT,
)
from app.rag.context_builder import build_context
from app.rag.retriever import retrieve_by_document_type, retrieve_by_query
from app.workflows.interview_state import InterviewState
from app.workflows.llm import get_workflow_llm

logger = logging.getLogger(__name__)

# ============================================================
# DB NODES — read/write the database
# ============================================================


def load_session(state: InterviewState) -> dict:
    """
    Load the interview session from DB and determine if this is the first turn.

    Reads:  session_id, user_id
    Writes: is_first_turn, max_questions, question_number

    How it works:
        - Opens a DB session (scoped to this node only)
        - Loads the InterviewSession by ID
        - Counts existing assistant messages to determine turn number
        - If no assistant messages → first turn (resume analysis path)
        - If assistant messages exist → subsequent turn (evaluation path)
    """
    logger.info("Node: load_session — starting")

    with SessionLocal() as db:
        session_id = uuid.UUID(state["session_id"])

        db_session = db.get(InterviewSession, session_id)
        if not db_session:
            return {"error": "Session not found"}

        # Count assistant messages = number of questions already asked
        assistant_count = db.exec(
            select(Message).where(
                Message.session_id == session_id,
                Message.role == MessageRole.assistant,
                Message.is_deleted == False,  # noqa: E712
            )
        ).all()

        question_number = len(assistant_count)
        is_first_turn = question_number == 0

        logger.info(
            "Node: load_session — is_first_turn=%s question_number=%d",
            is_first_turn,
            question_number,
        )

        return {
            "is_first_turn": is_first_turn,
            "question_number": question_number,
            "max_questions": state.get("max_questions", 5),
        }


def persist_question(state: InterviewState) -> dict:
    """
    Save the generated question as an assistant message in the DB.

    Reads:  session_id, current_question
    Writes: (none — side effect only)
    """
    logger.info("Node: persist_question — saving to DB")

    with SessionLocal() as db:
        msg = Message(
            session_id=uuid.UUID(state["session_id"]),
            role=MessageRole.assistant,
            content=state["current_question"],
        )
        db.add(msg)
        db.commit()

    logger.info("Node: persist_question — saved")
    return {}


def persist_results(state: InterviewState) -> dict:
    """
    Save the final report and mark the session as completed.

    Reads:  session_id, final_report
    Writes: is_complete
    """
    logger.info("Node: persist_results — saving report to DB")

    with SessionLocal() as db:
        session_id = uuid.UUID(state["session_id"])

        # Save report as an assistant message
        msg = Message(
            session_id=session_id,
            role=MessageRole.assistant,
            content=state["final_report"],
        )
        db.add(msg)

        # Mark session as completed
        db_session = db.get(InterviewSession, session_id)
        if db_session:
            db_session.status = SessionStatus.completed
            db_session.summary = f"Interview completed. Average score: {_avg_score(state)}/100"

        db.commit()

    logger.info("Node: persist_results — session marked completed")
    return {"is_complete": True}


# ============================================================
# RAG NODE - retrieve context from indexed documents
# ============================================================


async def retrieve_context(state: InterviewState) -> dict:
    """Retrieve resume chunks most relevant to the job description.

    Reads: user_id
    Writes: resume_context

    Flow:
        1. Get JD chunks (if available)
        2. Use LLM to extract key requirements from JD
        3. Query resume with those requirements (semantic search)
        4. Build resume_context from matched chunks
        5. Return context for LLM nodes to use

    Fallback: if no JD or no resume chunks match, returns empty string.
    LLM nodes proceed without RAG context and fall back to raw resume_text.
    """
    logger.info("Node: retrieve_context - starting")

    user_id = uuid.UUID(state["user_id"])
    session_id = uuid.UUID(state["session_id"]) if state.get("session_id") else None
    llm = get_workflow_llm()

    try:
        with SessionLocal() as db:
            # Step 1: Get JD chunks (to understand what the role requires)
            jd_chunks = retrieve_by_document_type(
                db=db,
                user_id=user_id,
                document_type=DocumentType.job_description,
                session_id=session_id,
                top_k=8,
            )

            resume_chunks = []
            jd_query = None

            # Step 2: If we have a JD, use LLM to extract key requirements
            if jd_chunks:
                jd_text = "\n".join([chunk.chunk_text for chunk in jd_chunks])

                # LLM extracts key skills/requirements from JD
                extraction_prompt = f"""Extract the top 5 key technical skills and requirements from this job description.
                Return as a comma-separated list, nothing else. Be concise.

                JOB DESCRIPTION:
                {jd_text}"""

                response = await llm.ainvoke(extraction_prompt)
                jd_query = response.content.strip()

                logger.info(
                    "Node: retrieve_context - extracted JD requirements: %s",
                    jd_query,
                )

                # Step 3: Query resume with JD requirements (semantic search)
                resume_chunks = retrieve_by_query(
                    db=db,
                    query=jd_query,
                    user_id=user_id,
                    document_type=DocumentType.resume,
                    session_id=session_id,
                    top_k=10,
                )
            else:
                # No JD: fall back to getting all resume chunks in order
                resume_chunks = retrieve_by_document_type(
                    db=db,
                    user_id=user_id,
                    document_type=DocumentType.resume,
                    session_id=session_id,
                    top_k=10,
                )

            # Step 4: Build resume_context from matched chunks
            resume_context = build_context(resume_chunks)

            logger.info(
                "Node: retrieve_context - resume_chunks=%d | resume_ctx_len=%d | jd_query=%s",
                len(resume_chunks),
                len(resume_context),
                jd_query or "no_jd",
            )

            return {
                "resume_context": resume_context,
                "jd_context": jd_query or "",  # Extracted JD requirements (for reference)
            }

    except Exception as e:
        # Retrieval failure should NOT crash the interview.
        # Log the error and proceed without context.
        logger.warning(
            "Node: retrieve_context - failed, proceeding without RAG | error=%s",
            str(e),
        )
        return {
            "resume_context": "",
            "jd_context": "",
        }


# ============================================================
# LLM NODES — call the LLM
# ============================================================


async def analyze_resume(state: InterviewState) -> dict:
    """
    LLM analyzes the resume to understand the candidate's background.

    Reads:  resume_text
    Writes: resume_analysis
    """
    logger.info("Node: analyze_resume — starting")
    llm = get_workflow_llm()

    prompt = ANALYZE_RESUME_PROMPT.format(resume_text=state["resume_text"])
    response = await llm.ainvoke(prompt)
    analysis = response.content.strip()  # type: ignore

    logger.info("Node: analyze_resume — completed (%d chars)", len(analysis))
    return {"resume_analysis": analysis}


async def extract_skills(state: InterviewState) -> dict:
    """
    LLM extracts a flat list of technical skills from the resume.

    Reads:  resume_text, resume_analysis
    Writes: skills
    """
    logger.info("Node: extract_skills — starting")
    llm = get_workflow_llm()

    prompt = EXTRACT_SKILLS_PROMPT.format(
        resume_text=state["resume_text"],
        resume_analysis=state["resume_analysis"],
    )
    response = await llm.ainvoke(prompt)
    raw_skills = response.content.strip()  # type: ignore

    skills = [s.strip() for s in raw_skills.split(",") if s.strip()]

    logger.info("Node: extract_skills — found %d skills", len(skills))
    return {"skills": skills}


async def determine_difficulty(state: InterviewState) -> dict:
    """
    LLM determines interview difficulty based on resume analysis.

    Reads:  resume_analysis, skills
    Writes: difficulty
    """
    logger.info("Node: determine_difficulty — starting")
    llm = get_workflow_llm()

    prompt = DETERMINE_DIFFICULTY_PROMPT.format(
        resume_analysis=state["resume_analysis"],
        skills=", ".join(state.get("skills", [])),
    )
    response = await llm.ainvoke(prompt)
    raw = response.content.strip().lower()  # type: ignore

    # Validate — only accept known levels, default to "mid"
    difficulty = raw if raw in ("junior", "mid", "senior") else "mid"

    logger.info("Node: determine_difficulty — level=%s", difficulty)
    return {"difficulty": difficulty}


async def generate_question(state: InterviewState) -> dict:
    """
    LLM generates a contextual interview question.

    Reads:  skills, difficulty, resume_analysis, questions_asked, question_number, max_questions
    Writes: current_question, questions_asked (appended), question_number (incremented)

    Note: questions_asked uses a reducer (operator.add), so returning a list
    APPENDS to the existing list rather than overwriting.
    """
    logger.info("Node: generate_question — starting")
    llm = get_workflow_llm()

    existing_questions = state.get("questions_asked", [])
    question_number = state.get("question_number", 0) + 1

    prompt = GENERATE_QUESTION_PROMPT.format(
        skills=", ".join(state.get("skills", [])),
        difficulty=state.get("difficulty", "mid"),
        resume_analysis=state.get("resume_analysis", ""),
        resume_context=state.get("resume_context", "") or "No resume context available.",
        jd_context=state.get("jd_context", "") or "No job description available.",
        questions_asked="\n".join(f"- {q}" for q in existing_questions) or "None yet",
        question_number=question_number,
        max_questions=state.get("max_questions", 5),
    )
    response = await llm.ainvoke(prompt)
    question = response.content.strip()  # type: ignore

    logger.info("Node: generate_question — q#%d generated", question_number)

    return {
        "current_question": question,
        "questions_asked": [question],  # reducer appends this
        "question_number": question_number,
    }


async def evaluate_answer(state: InterviewState) -> dict:
    """
    LLM evaluates the user's answer against the current question.

    Reads:  current_question, current_answer, difficulty
    Writes: current_evaluation, current_score, scores (appended)
    """
    logger.info("Node: evaluate_answer — starting")
    llm = get_workflow_llm()

    prompt = EVALUATE_ANSWER_PROMPT.format(
        question=state["current_question"],
        answer=state["current_answer"],
        difficulty=state.get("difficulty", "mid"),
        resume_context=state.get("resume_context", "") or "No resume context available.",
        jd_context=state.get("jd_context", "") or "No job description available.",
    )
    response = await llm.ainvoke(prompt)
    evaluation_text = response.content.strip()  # type: ignore

    score = _parse_score(evaluation_text)

    logger.info("Node: evaluate_answer — score=%d", score)

    return {
        "current_evaluation": evaluation_text,
        "current_score": score,
        "scores": [score],  # reducer appends this
    }


async def generate_feedback(state: InterviewState) -> dict:
    """
    LLM generates constructive feedback based on the evaluation.

    Reads:  current_question, current_answer, current_evaluation, current_score
    Writes: current_feedback
    """
    logger.info("Node: generate_feedback — starting")
    llm = get_workflow_llm()

    prompt = GENERATE_FEEDBACK_PROMPT.format(
        question=state["current_question"],
        answer=state["current_answer"],
        evaluation=state["current_evaluation"],
        score=state["current_score"],
        jd_context=state.get("jd_context", "") or "No job description available.",
    )
    response = await llm.ainvoke(prompt)
    feedback = response.content.strip()  # type: ignore

    logger.info("Node: generate_feedback — completed")
    return {"current_feedback": feedback}


async def generate_report(state: InterviewState) -> dict:
    """
    LLM generates a comprehensive final interview report.

    Reads:  skills, difficulty, questions_asked, scores
    Writes: final_report
    """
    logger.info("Node: generate_report — starting")
    llm = get_workflow_llm()

    questions = state.get("questions_asked", [])
    scores = state.get("scores", [])

    # Build a formatted list of questions and their scores
    questions_and_scores = "\n".join(
        f"Q{i + 1}: {q} — Score: {scores[i] if i < len(scores) else 'N/A'}/100"
        for i, q in enumerate(questions)
    )

    prompt = GENERATE_REPORT_PROMPT.format(
        skills=", ".join(state.get("skills", [])),
        difficulty=state.get("difficulty", "mid"),
        total_questions=len(questions),
        questions_and_scores=questions_and_scores or "No questions were asked.",
        average_score=_avg_score(state),
        jd_context=state.get("jd_context", "") or "No job description available.",
    )
    response = await llm.ainvoke(prompt)
    report = response.content.strip()  # type: ignore

    logger.info("Node: generate_report — completed")
    return {"final_report": report}


# ============================================================
# CONTROL NODES — routing decisions, interrupts
# ============================================================


def wait_for_answer(state: InterviewState) -> dict:
    """
    Interrupt the graph and return control to the API.

    This is LangGraph's human-in-the-loop pattern:
        1. Graph reaches this node
        2. interrupt() saves state to the checkpointer
        3. Graph execution pauses
        4. The API returns the current question to the frontend
        5. When the user submits an answer, the API calls graph.ainvoke()
           with Command(resume={"current_answer": "..."})
        6. Graph resumes from this node with the answer in state
    """
    logger.info("Node: wait_for_answer — interrupting for user input")

    answer = interrupt("Waiting for user answer")

    logger.info("Node: wait_for_answer — resumed with answer (%d chars)", len(answer))
    return {"current_answer": answer}


# ============================================================
# ROUTER FUNCTIONS — pure logic, no side effects
# ============================================================


def route_by_turn(state: InterviewState) -> str:
    """
    Route based on whether this is the first turn or a subsequent one.

    Returns:
        "first_turn"      → analyze_resume path
        "subsequent_turn" → evaluate_answer path
    """
    if state.get("is_first_turn", True):
        return "first_turn"
    return "subsequent_turn"


def should_continue(state: InterviewState) -> str:
    """
    Decide whether to ask another question or finish the interview.

    Returns:
        "continue" → generate another question
        "finish"   → generate the final report
    """
    question_number = state.get("question_number", 0)
    max_questions = state.get("max_questions", 5)

    logger.info(
        "Router: should_continue | q=%d max=%d",
        question_number,
        max_questions,
    )

    if question_number >= max_questions:
        return "finish"
    return "continue"


# ============================================================
# HELPERS — private functions used by nodes
# ============================================================


def _parse_score(evaluation_text: str) -> int:
    """Extract numeric score from evaluation text. Defaults to 50."""
    match = re.search(r"Score:\s*(\d+)", evaluation_text)
    if match:
        score = int(match.group(1))
        return max(0, min(100, score))
    logger.warning("Could not parse score from evaluation, defaulting to 50")
    return 50


def _avg_score(state: InterviewState) -> int:
    """Calculate average score from all turns."""
    scores = state.get("scores", [])
    if not scores:
        return 0
    return round(sum(scores) / len(scores))
