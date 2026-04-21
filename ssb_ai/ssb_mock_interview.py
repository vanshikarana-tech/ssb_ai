"""
ssb_mock_interview.py
─────────────────────
SSBInterviewController + LevelStateManager + Cross-Questioning Engine

Interview Modes (per session of 10 questions)
──────────────────────────────────────────────
  WARMUP  (questions 1 – WARMUP_COUNT, default 3)
    Pull from the question bank. Listen and store. Minimal probing.
    The IO is building rapport and gathering surface-level PIQ data.

  DRILL   (questions WARMUP_COUNT+1 – 10)
    After every answer, send the last HISTORY_WINDOW chat turns to Gemini
    and ask it to generate a contextual cross-question anchored to a
    specific detail the candidate mentioned.

    Cross-question trigger logic:
      • answer has ≥ CROSS_Q_MIN_WORDS words  →  generate cross-question
      • answer is too short                   →  fall back to question bank
      • Gemini returns FALLBACK sentinel      →  fall back to question bank

    Cross-questions count toward the 10-question session limit.
    They are flagged with is_cross_question=True in QARecord.

Chat History
────────────
  Each Q-A exchange is stored as a ChatTurn(role, text).
  The last HISTORY_WINDOW turns are passed to Gemini as a multi-turn
  `contents` list so the model has full conversational context.

  SDK note: we use client.models.generate_content() with a list of
  Content objects (not start_chat), which is the correct pattern for
  the google-genai ≥1.0 SDK in a stateless Streamlit environment.

Level-Up System
───────────────
  BASIC        → avg OLQ ≥ 6.0  → unlock INTERMEDIATE
  INTERMEDIATE → avg OLQ ≥ 7.0  → unlock ADVANCED
  ADVANCED     → no further level

Exponential backoff (max 5 retries, 1 s initial, ±0.5 s jitter) on all
Gemini calls, retrying on 429 and 503 only.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from google import genai
from google.genai import types

from ssb_question_bank import (
    DifficultyLevel,
    Question,
    QUESTION_BANK,
    LEVEL_ORDER,
    LEVEL_UP_THRESHOLD,
    MIN_SUBSTANTIVE_WORDS,
)

# ─── Constants ────────────────────────────────────────────────────────────────
MAX_RETRIES         = 5
INITIAL_DELAY_SEC   = 1.0
JITTER_MAX_SEC      = 0.5
GEMINI_MODEL        = "gemini-2.5-flash"
SESSION_LENGTH      = 10      # questions per session before evaluation

# Cross-questioning constants
WARMUP_COUNT        = 3       # first N questions are warm-up (no cross-questioning)
HISTORY_WINDOW      = 4       # number of recent Q-A turns sent as chat history
CROSS_Q_MIN_WORDS   = 25      # minimum answer words to attempt a cross-question
CROSS_Q_FALLBACK    = "FALLBACK"   # sentinel Gemini returns when no hook found


# ─── Data Models ──────────────────────────────────────────────────────────────
@dataclass
class QARecord:
    """A single question-answer pair with AI evaluation."""
    question_id:     str
    question_text:   str
    level:           DifficultyLevel
    category:        str
    answer:          str
    evaluation:      str
    olq_score:       int   = 0
    answer_duration: float = 0.0
    word_count:      int   = 0


@dataclass
class EvaluationSummary:
    """
    Generated after every SESSION_LENGTH questions.
    Drives the level-up decision and the UI pause screen.
    """
    session_number:    int              # 1-indexed (1st set of 10, 2nd set, …)
    level_completed:   DifficultyLevel  # level that was just played
    next_level:        Optional[DifficultyLevel]  # None if already at ADVANCED
    avg_olq_score:     float            # mean of olq_score across the set
    proficiency_score: int              # 0–100 composite
    levelled_up:       bool             # True if threshold was met
    remark:            str              # Gemini-generated evaluation text
    records:           list[QARecord]   # the 10 records that triggered this


@dataclass
class LevelStateManager:
    """
    Tracks the candidate's progression across sessions.

    Attributes:
        current_level:      Active difficulty tier.
        user_proficiency:   Running composite score (0–100).
        current_q_count:    Questions answered in the current session of 10.
        total_q_count:      Total questions answered across all sessions.
        used_ids:           Set of question IDs already asked — never repeated.
        session_number:     How many 10-question sets have been completed.
    """
    current_level:    DifficultyLevel          = DifficultyLevel.BASIC
    user_proficiency: float                    = 0.0
    current_q_count:  int                      = 0
    total_q_count:    int                      = 0
    used_ids:         set[str]                 = field(default_factory=set)
    session_number:   int                      = 0

    def level_index(self) -> int:
        return LEVEL_ORDER.index(self.current_level)

    def next_level(self) -> Optional[DifficultyLevel]:
        idx = self.level_index()
        return LEVEL_ORDER[idx + 1] if idx + 1 < len(LEVEL_ORDER) else None

    def available_questions(self) -> list[Question]:
        """Returns questions at current_level that have not been used yet."""
        pool = QUESTION_BANK[self.current_level]
        return [q for q in pool if q.id not in self.used_ids]

    def compute_proficiency(self, recent_scores: list[int], recent_words: list[int]) -> int:
        """
        Composite proficiency score (0–100):
          60% — average OLQ score (normalised to 0–100)
          25% — answer substantiveness (% of answers ≥ MIN_SUBSTANTIVE_WORDS)
          15% — consistency bonus (low std-dev in scores)

        Args:
            recent_scores: OLQ scores (1–10) for the last SESSION_LENGTH answers.
            recent_words:  Word counts for the same answers.

        Returns:
            Integer 0–100.
        """
        if not recent_scores:
            return 0

        n = len(recent_scores)
        avg_score = sum(recent_scores) / n

        # OLQ component (60 pts max)
        olq_component = (avg_score / 10.0) * 60.0

        # Substantiveness component (25 pts max)
        substantive = sum(1 for w in recent_words if w >= MIN_SUBSTANTIVE_WORDS)
        sub_component = (substantive / n) * 25.0

        # Consistency component (15 pts max) — reward low variance
        if n > 1:
            mean = avg_score
            variance = sum((s - mean) ** 2 for s in recent_scores) / n
            std_dev = variance ** 0.5
            # std_dev of 0 → full 15 pts; std_dev of 3+ → 0 pts
            consistency = max(0.0, 1.0 - (std_dev / 3.0)) * 15.0
        else:
            consistency = 15.0

        return min(100, int(olq_component + sub_component + consistency))

    def should_level_up(self, avg_score: float) -> bool:
        threshold = LEVEL_UP_THRESHOLD.get(self.current_level, 0.0)
        return avg_score >= threshold and self.next_level() is not None

    def advance_level(self) -> None:
        nxt = self.next_level()
        if nxt:
            self.current_level = nxt


@dataclass
class InterviewSession:
    """Full state of one 10-question interview session."""
    level_state:      LevelStateManager      = field(default_factory=LevelStateManager)
    records:          list[QARecord]         = field(default_factory=list)
    current_question: Optional[Question]     = None
    status:           str                    = "idle"
    # status: idle | running | evaluation | complete
    evaluation:       Optional[EvaluationSummary] = None
    answer_start_time: float                 = 0.0


# ─── Backoff Helpers ──────────────────────────────────────────────────────────
def _is_retryable(err: str) -> bool:
    return any(k in err for k in (
        "429", "503", "resource_exhausted", "quota",
        "service_unavailable", "overloaded",
    ))


def _backoff_delay(attempt: int) -> float:
    return min(INITIAL_DELAY_SEC * (2 ** (attempt - 1)), 32.0) + random.uniform(0, JITTER_MAX_SEC)


def _call_gemini(client: genai.Client, system_instruction: str, user_prompt: str) -> str:
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.65,
                ),
            )
            return result.text.strip()
        except Exception as e:
            last_error = e
            err = str(e).lower()
            if _is_retryable(err) and attempt < MAX_RETRIES:
                time.sleep(_backoff_delay(attempt))
                continue
            elif _is_retryable(err):
                raise RuntimeError(
                    f"API unavailable after {MAX_RETRIES} attempts. Please wait."
                ) from e
            else:
                raise RuntimeError(f"Gemini API error: {e}") from e
    raise RuntimeError(f"All retries exhausted. Last error: {last_error}")


# ─── System Prompts ───────────────────────────────────────────────────────────
_IO_SYSTEM_PROMPT = """
You are a Senior Interviewing Officer (IO) at the Services Selection Board (SSB), India.
You are conducting a formal Personal Interview to assess Officer Like Qualities (OLQs).

Your persona:
- Formal, composed, and professional. No emojis. No casual language.
- Slightly stern but fair. You probe for depth, not just surface answers.
- You assess: Effective Intelligence, Reasoning Ability, Power of Expression,
  Self-Confidence, Sense of Responsibility, Initiative, Liveliness,
  Social Adaptability, Cooperation, Speed of Decision Making,
  Ability to Influence Group.

When evaluating a candidate's answer, respond in this EXACT format:

OLQ ASSESSMENT
--------------
Score: X/10

Strengths:
(2-3 specific OLQs demonstrated, with brief evidence from the answer.)

Areas for Improvement:
(Specific, actionable suggestions. Rewrite one weak sentence if helpful.)

IO's Note:
(One sentence — what a real IO would note about this candidate.)
"""

_EVALUATION_SYSTEM_PROMPT = """
You are a Senior Interviewing Officer (IO) at the Services Selection Board (SSB), India.
You have just completed a set of {n} questions at the {level} level with a candidate.
The candidate's proficiency score for this set is {proficiency}/100.

Generate a formal Evaluation Summary. Be structured, professional, and free of emojis.

Use this EXACT format:

SESSION EVALUATION SUMMARY
===========================

Level Completed: {level}
Questions Reviewed: {n}
Proficiency Score: {proficiency}/100
Average OLQ Score: {avg_score}/10

Clarity of Thought: X/10
(Did the candidate answer directly and logically?)

Confidence Assessment: X/10
(Based on answer length, directness, and flow.)

OLQ Performance:
(Which 2-3 OLQs were consistently strong? Which 1-2 need work?)

Level Verdict:
(One sentence — did the candidate demonstrate readiness for the next level?)

Recommended Focus for Next Session:
(2-3 specific areas the candidate should prepare before the next level.)
"""


# ─── SSBInterviewController ───────────────────────────────────────────────────
class SSBInterviewController:
    """
    Level-aware sequential interview controller.

    State machine per session (10 questions):
      idle → running → evaluation → [running (next level) | complete]

    Usage:
        ctrl    = SSBInterviewController(client)
        session = ctrl.start_interview()

        while session.status == "running":
            q = session.current_question
            session = ctrl.submit_answer(session, answer_text)

        if session.status == "evaluation":
            summary = ctrl.generate_evaluation(session)
            # show summary to user
            if summary.levelled_up:
                session = ctrl.start_next_level(session)
            else:
                session = ctrl.start_next_level(session)  # retry same level

        if session.status == "complete":
            # all questions at ADVANCED exhausted, or user chose to stop
    """

    def __init__(self, client: genai.Client) -> None:
        self._client = client

    # ── Public API ────────────────────────────────────────────────────────────

    def start_interview(
        self,
        existing_level_state: Optional[LevelStateManager] = None,
    ) -> InterviewSession:
        """
        Starts a new 10-question session.

        Args:
            existing_level_state: Pass the LevelStateManager from a previous
                                  session to continue progression and preserve
                                  used_ids. Pass None for a brand-new start.
        """
        ls = existing_level_state or LevelStateManager()
        session = InterviewSession(level_state=ls, status="running")
        session.current_question = self._pick_question(session)
        session.answer_start_time = time.time()
        return session

    def submit_answer(self, session: InterviewSession, answer: str) -> InterviewSession:
        """
        Evaluates the answer, records it, advances the question counter.

        Transitions:
          running → evaluation  when current_q_count reaches SESSION_LENGTH
          running → running     otherwise
          running → complete    when no questions remain at any level
        """
        if session.status != "running":
            raise RuntimeError("Session is not in running state.")
        if not answer.strip():
            raise ValueError("Answer cannot be empty.")

        q    = session.current_question
        ls   = session.level_state
        dur  = round(time.time() - session.answer_start_time, 1)
        wc   = len(answer.split())

        evaluation = self._evaluate_answer(q, answer)
        score      = self._extract_score(evaluation)

        session.records.append(QARecord(
            question_id=q.id,
            question_text=q.text,
            level=q.level,
            category=q.category,
            answer=answer,
            evaluation=evaluation,
            olq_score=score,
            answer_duration=dur,
            word_count=wc,
        ))

        ls.used_ids.add(q.id)
        ls.current_q_count += 1
        ls.total_q_count   += 1

        if ls.current_q_count >= SESSION_LENGTH:
            # Session of 10 complete — trigger evaluation
            session.status = "evaluation"
            session.current_question = None
        else:
            # Check if questions remain
            if not ls.available_questions():
                session.status = "complete"
                session.current_question = None
            else:
                session.current_question = self._pick_question(session)
                session.answer_start_time = time.time()

        return session

    def generate_evaluation(self, session: InterviewSession) -> EvaluationSummary:
        """
        Computes proficiency, decides level-up, generates Gemini remark.
        Stores the EvaluationSummary in session.evaluation and returns it.
        Must be called when session.status == 'evaluation'.
        """
        if session.status != "evaluation":
            raise RuntimeError("Session is not in evaluation state.")

        ls      = session.level_state
        n       = SESSION_LENGTH
        recent  = session.records[-n:]

        scores  = [r.olq_score for r in recent if r.olq_score > 0]
        words   = [r.word_count for r in recent]
        avg     = sum(scores) / len(scores) if scores else 0.0
        prof    = ls.compute_proficiency(scores, words)
        levelled_up = ls.should_level_up(avg)
        next_lv = ls.next_level()

        ls.session_number += 1

        # Build Gemini prompt
        transcript_parts = []
        for i, rec in enumerate(recent, 1):
            transcript_parts.append(
                f"Q{i} [{rec.category}] ({rec.level.value}): {rec.question_text}\n"
                f"Answer ({rec.answer_duration}s, {rec.word_count} words): {rec.answer}\n"
                f"Score: {rec.olq_score}/10"
            )
        transcript = "\n---\n".join(transcript_parts)

        sys_prompt = _EVALUATION_SYSTEM_PROMPT.format(
            n=n,
            level=ls.current_level.value,
            proficiency=prof,
            avg_score=f"{avg:.1f}",
        )
        user_prompt = (
            f"Q&A Transcript:\n\n{transcript}\n\n"
            "Generate the Session Evaluation Summary now."
        )
        remark = _call_gemini(self._client, sys_prompt, user_prompt)

        summary = EvaluationSummary(
            session_number=ls.session_number,
            level_completed=ls.current_level,
            next_level=next_lv,
            avg_olq_score=round(avg, 1),
            proficiency_score=prof,
            levelled_up=levelled_up,
            remark=remark,
            records=list(recent),
        )
        session.evaluation = summary
        return summary

    def start_next_level(self, session: InterviewSession) -> InterviewSession:
        """
        Advances to the next difficulty level (or retries the current one if
        the threshold was not met) and starts a fresh 10-question session.

        Preserves used_ids and total_q_count from the previous session.
        """
        if session.status != "evaluation":
            raise RuntimeError("Can only advance from evaluation state.")

        ls = session.level_state
        summary = session.evaluation

        if summary and summary.levelled_up:
            ls.advance_level()

        # Reset per-session counter; keep used_ids and total_q_count
        ls.current_q_count = 0

        # Check if any questions remain at the (possibly new) level
        if not ls.available_questions():
            # Exhausted this level — try to advance anyway
            if ls.next_level():
                ls.advance_level()
                ls.current_q_count = 0
            if not ls.available_questions():
                # Truly exhausted all questions
                session.status = "complete"
                session.current_question = None
                return session

        new_session = InterviewSession(level_state=ls, status="running")
        new_session.current_question = self._pick_question(new_session)
        new_session.answer_start_time = time.time()
        # Carry over all records for the final report
        new_session.records = list(session.records)
        return new_session

    def get_level_label(self, session: InterviewSession) -> str:
        return session.level_state.current_level.value

    def get_progress_in_session(self, session: InterviewSession) -> tuple[int, int]:
        """Returns (questions_done_this_session, SESSION_LENGTH)."""
        return session.level_state.current_q_count, SESSION_LENGTH

    def reset(self) -> InterviewSession:
        return InterviewSession()

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _pick_question(self, session: InterviewSession) -> Question:
        """
        Selects a random unused question at the current level.
        Raises RuntimeError if the pool is exhausted (should not happen if
        start_next_level() checks availability first).
        """
        available = session.level_state.available_questions()
        if not available:
            raise RuntimeError(
                f"No questions remaining at level "
                f"{session.level_state.current_level.value}."
            )
        return random.choice(available)

    def _evaluate_answer(self, question: Question, answer: str) -> str:
        user_prompt = (
            f"Difficulty Level: {question.level.value}\n"
            f"Category: {question.category}\n\n"
            f"Question: {question.text}\n\n"
            f"Candidate's answer:\n\"\"\"\n{answer}\n\"\"\""
        )
        return _call_gemini(self._client, _IO_SYSTEM_PROMPT, user_prompt)

    @staticmethod
    def _extract_score(evaluation: str) -> int:
        match = re.search(r"Score:\s*(\d+)\s*/\s*10", evaluation, re.IGNORECASE)
        return int(match.group(1)) if match else 0
