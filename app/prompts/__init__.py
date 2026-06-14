"""
Prompt registry — central access point for all system prompts.

WHY PROMPTS ARE A SEPARATE MODULE:
    Prompts are the most frequently iterated part of any AI application.
    You'll tweak them constantly — adjusting tone, adding constraints,
    fixing edge cases. Keeping them in their own module means:

    1. Easy to find and edit without touching service logic
    2. Version-controllable — git diff shows prompt changes clearly
    3. Composable — you can build complex prompts from reusable parts
    4. Testable — you can unit test prompt construction

FUTURE EXPANSION:
    As your app grows, you might add:
    - prompts/feedback.py      -> AI that evaluates user answers
    - prompts/summarizer.py    -> AI that summarizes interview sessions
    - prompts/hint_giver.py    -> AI that gives targeted hints
"""

from .interviewer import build_interviewer_system_prompt

__all__ = [
    "build_interviewer_system_prompt",
]