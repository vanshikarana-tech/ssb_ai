"""
mock_interview_ui.py
────────────────────
Streamlit UI for the SSB Mock Personal Interview with Level-Up System.

Screens driven by session.status:
  idle        → Start screen (level selector)
  running     → Split-screen interview (camera + question + voice)
  evaluation  → Evaluation Summary + "Start Next Interview: Level X" button
  complete    → Final report + Save recording button
"""

import streamlit as st
import streamlit.components.v1 as components

from ssb_mock_interview import (
    SSBInterviewController,
    InterviewSession,
    LevelStateManager,
    EvaluationSummary,
    SESSION_LENGTH,
)
from ssb_question_bank import DifficultyLevel, LEVEL_ORDER, QUESTION_BANK
from ssb_proctoring import RecordingManager

# ─── Constants ────────────────────────────────────────────────────────────────
_ANSWER_KEY = "mi_text_answer"

# Level badge colours for the UI
_LEVEL_COLOURS = {
    DifficultyLevel.BASIC:        "#2ecc71",
    DifficultyLevel.INTERMEDIATE: "#e67e22",
    DifficultyLevel.ADVANCED:     "#c0392b",
}

# ─── postMessage Bridge ───────────────────────────────────────────────────────
_BRIDGE_HTML = f"""
<script>
(function() {{
  if (window._ssbBridgeInstalled) return;
  window._ssbBridgeInstalled = true;

  const TEXTAREA_KEY = "{_ANSWER_KEY}";

  function findTextarea() {{
    let ta = document.querySelector('textarea[data-testid="stTextArea-' + TEXTAREA_KEY + '"]');
    if (ta) return ta;
    return Array.from(document.querySelectorAll('textarea'))
                .find(el => el.offsetParent !== null) || null;
  }}

  function injectValue(text) {{
    const ta = findTextarea();
    if (!ta) return false;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype, 'value'
    ).set;
    setter.call(ta, text);
    ta.dispatchEvent(new Event('input',  {{ bubbles: true }}));
    ta.dispatchEvent(new Event('change', {{ bubbles: true }}));
    return true;
  }}

  function clickSubmit() {{
    const btn = document.querySelector('button[data-testid="baseButton-primary"]')
             || Array.from(document.querySelectorAll('button'))
                     .find(b => b.innerText.trim() === 'Submit Answer');
    if (btn) btn.click();
  }}

  window.addEventListener('message', (event) => {{
    if (!event.data || typeof event.data !== 'object') return;

    if (event.data.type === 'ssb_transcript') {{
      // Inject into textarea AND store in sessionStorage so it survives rerenders
      const t = event.data.transcript || '';
      injectValue(t);
      sessionStorage.setItem('ssb_last_transcript', t);
    }}

    if (event.data.type === 'ssb_auto_submit') {{
      const t = event.data.transcript || '';
      injectValue(t);
      sessionStorage.setItem('ssb_last_transcript', t);
      setTimeout(clickSubmit, 120);
    }}
  }});

  // On page load, restore transcript from sessionStorage if textarea is empty
  window.addEventListener('load', () => {{
    setTimeout(() => {{
      const saved = sessionStorage.getItem('ssb_last_transcript');
      if (saved) {{
        const ta = findTextarea();
        if (ta && !ta.value.trim()) injectValue(saved);
      }}
    }}, 500);
  }});
}})();
</script>
"""


# ─── Session State Helpers ────────────────────────────────────────────────────
def _init_session() -> None:
    defaults = {
        "mi_session":           InterviewSession(),
        "mi_voice_transcript":  "",
        "mi_last_evaluation":   "",
        "mi_eval_summary_text": "",   # cached Gemini evaluation text
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _get_api_key() -> str:
    """
    Reads GEMINI_API_KEY from st.secrets (Streamlit Cloud) or falls back to
    a mock/demo mode. No database, no token, no username required.
    """
    try:
        return st.secrets["GEMINI_API_KEY"]
    except (KeyError, FileNotFoundError):
        return ""


def _get_controller() -> SSBInterviewController:
    if "mi_controller" not in st.session_state:
        from google import genai as _genai
        api_key = _get_api_key()
        if not api_key:
            st.error(
                "**GEMINI_API_KEY not found.**\n\n"
                "Go to **Streamlit Cloud → App Settings → Secrets** and add:\n\n"
                "```toml\nGEMINI_API_KEY = \"your_key_here\"\n```\n\n"
                "Get a free key at https://aistudio.google.com/app/apikey"
            )
            st.stop()
        client = _genai.Client(api_key=api_key)
        st.session_state["mi_controller"] = SSBInterviewController(client)
    return st.session_state["mi_controller"]


def _get_rm() -> RecordingManager:
    if "mi_recording_manager" not in st.session_state:
        st.session_state["mi_recording_manager"] = RecordingManager()
    return st.session_state["mi_recording_manager"]


# ─── Level Badge ──────────────────────────────────────────────────────────────
def _level_badge(level: DifficultyLevel) -> str:
    colour = _LEVEL_COLOURS.get(level, "#555")
    return (
        f'<span style="background:{colour};color:#fff;padding:2px 10px;'
        f'border-radius:12px;font-size:12px;font-weight:700;">'
        f'{level.value.upper()}</span>'
    )


# ─── Progress Bar ─────────────────────────────────────────────────────────────
def _render_progress(session: InterviewSession, controller: SSBInterviewController) -> None:
    done, total = controller.get_progress_in_session(session)
    level       = session.level_state.current_level
    colour      = _LEVEL_COLOURS.get(level, "#555")

    col_prog, col_meta = st.columns([3, 1])
    with col_prog:
        st.progress(
            done / total,
            text=f"Question **{done}** of **{total}** — Session {session.level_state.session_number + 1}",
        )
    with col_meta:
        st.markdown(_level_badge(level), unsafe_allow_html=True)
        st.caption(f"Total answered: {session.level_state.total_q_count}")


# ─── Main Entry Point ─────────────────────────────────────────────────────────
def render_mock_interview() -> None:
    _init_session()
    controller: SSBInterviewController = _get_controller()
    rm:         RecordingManager       = _get_rm()
    session:    InterviewSession       = st.session_state["mi_session"]

    st.title("SSB Mock Personal Interview")
    st.markdown(
        "A formal, sequential Personal Interview simulation with a **Level-Up System**. "
        "Answer 10 questions per session. Perform well to unlock harder tiers."
    )
    st.markdown("---")

    components.html(_BRIDGE_HTML, height=0, scrolling=False)

    if   session.status == "idle":       _render_start_screen(controller)
    elif session.status == "running":    _render_interview_screen(session, controller, rm)
    elif session.status == "evaluation": _render_evaluation_screen(session, controller, rm)
    elif session.status == "complete":   _render_complete_screen(session, controller, rm)


# ─── Start Screen ─────────────────────────────────────────────────────────────
def _render_start_screen(controller: SSBInterviewController) -> None:
    st.subheader("Welcome, Candidate.")

    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown(
            """
            **Level-Up System:**
            | Level | Focus | Unlock Threshold |
            |---|---|---|
            | 🟢 Basic | PIQ, Family, Hobbies | Start here |
            | 🟠 Intermediate | SRT, Leadership, Ethics | Avg ≥ 6/10 |
            | 🔴 Advanced | Defence Policy, Strategy | Avg ≥ 7/10 |

            Each session = **10 questions**. No question repeats.
            """
        )
    with col_r:
        st.markdown(
            """
            **How it works:**
            - Answer each question (voice or text)
            - After 10 questions → Evaluation Summary
            - Score high enough → Level Up
            - Score below threshold → Retry same level with fresh questions
            - All 30 questions at a level exhausted → auto-advance
            """
        )

    st.info(
        "Allow camera and microphone access when prompted. "
        "Use **Chrome** or **Edge** for full voice support."
    )

    # Starting level selector (for returning users who want to skip Basic)
    st.markdown("---")
    start_level = st.selectbox(
        "Starting Level",
        options=[l.value for l in LEVEL_ORDER],
        index=0,
        help="New users should start at Basic.",
    )
    st.markdown("---")

    if st.button("Begin Interview", type="primary", use_container_width=True):
        ls = LevelStateManager(current_level=DifficultyLevel(start_level))
        session = controller.start_interview(existing_level_state=ls)
        _store_session(session)
        st.rerun()


# ─── Interview Screen ─────────────────────────────────────────────────────────
def _render_interview_screen(
    session:    InterviewSession,
    controller: SSBInterviewController,
    rm:         RecordingManager,
) -> None:
    _render_progress(session, controller)
    st.markdown("---")

    q = session.current_question

    col_cam, col_interview = st.columns([1, 2], gap="medium")

    with col_cam:
        st.markdown("##### Your Camera")
        st.caption("Monitor your posture and eye contact.")
        rm.render_camera_preview(height=255)

    with col_interview:
        # Level + category tag above the question
        level  = session.level_state.current_level
        colour = _LEVEL_COLOURS.get(level, "#555")
        st.markdown(
            f'<div style="margin-bottom:6px;">'
            f'{_level_badge(level)}&nbsp;&nbsp;'
            f'<span style="font-size:12px;color:#888;">{q.category}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.markdown("##### Interviewing Officer")
        st.info(q.text)

        rm.render_voice_input(q.text, textarea_key=_ANSWER_KEY, height=210)

    st.markdown("---")

    # Previous IO evaluation
    if st.session_state["mi_last_evaluation"]:
        with st.expander(
            f"IO's Assessment — Q{session.level_state.current_q_count} (previous answer)",
            expanded=False,
        ):
            st.markdown(st.session_state["mi_last_evaluation"])

    # Unified answer textarea
    st.markdown("**Your answer** — type below or use the voice panel above:")
    answer_text = st.text_area(
        "Your answer:",
        height=150,
        placeholder="Aim for 60–120 words. Be direct and confident.",
        key=_ANSWER_KEY,
        label_visibility="collapsed",
    )

    col_submit, col_abort = st.columns([3, 1])
    with col_submit:
        if st.button("Submit Answer", type="primary", use_container_width=True, key="mi_submit_text"):
            # Priority: typed text → session_state voice transcript → empty warning
            final = (
                answer_text.strip()
                or st.session_state.get("mi_voice_transcript", "").strip()
            )
            if not final:
                st.warning(
                    "No answer detected. If you used voice, the transcript may not have "
                    "synced — please type your answer or try speaking again."
                )
            else:
                _handle_submit(final, controller)
    with col_abort:
        if st.button("End Interview", use_container_width=True, key="mi_abort"):
            _abort_interview(controller, rm)


# ─── Evaluation Screen ────────────────────────────────────────────────────────
def _render_evaluation_screen(
    session:    InterviewSession,
    controller: SSBInterviewController,
    rm:         RecordingManager,
) -> None:
    ls = session.level_state

    st.subheader(f"Session {ls.session_number + 1} Complete — Evaluation")
    st.markdown(
        f"You have answered **{SESSION_LENGTH} questions** at the "
        f"{_level_badge(ls.current_level)} level.",
        unsafe_allow_html=True,
    )

    # Generate evaluation if not yet cached
    summary: EvaluationSummary | None = session.evaluation
    if summary is None:
        with st.spinner("Generating your Evaluation Summary..."):
            try:
                summary = controller.generate_evaluation(session)
                st.session_state["mi_session"] = session
                st.session_state["mi_eval_summary_text"] = summary.remark
            except RuntimeError as e:
                st.error(str(e))
                return

    st.markdown("---")

    # ── Proficiency dashboard ─────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Proficiency Score",  f"{summary.proficiency_score}/100")
    c2.metric("Avg OLQ Score",      f"{summary.avg_olq_score}/10")
    c3.metric("Level Completed",    summary.level_completed.value)
    c4.metric(
        "Result",
        "LEVEL UP ✓" if summary.levelled_up else "RETRY",
        delta="Threshold met" if summary.levelled_up else "Below threshold",
        delta_color="normal" if summary.levelled_up else "inverse",
    )

    # ── Gemini evaluation text ────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("Evaluation Summary")
    st.markdown(f"```\n{summary.remark}\n```")

    # ── Per-question score breakdown ──────────────────────────────────────────
    with st.expander("Question-by-Question Breakdown", expanded=False):
        for i, rec in enumerate(summary.records, 1):
            score_colour = "#2ecc71" if rec.olq_score >= 7 else ("#e67e22" if rec.olq_score >= 5 else "#e74c3c")
            st.markdown(
                f"**Q{i}** &nbsp; "
                f'<span style="background:{score_colour};color:#fff;padding:1px 8px;'
                f'border-radius:10px;font-size:12px;">{rec.olq_score}/10</span>'
                f" &nbsp; *{rec.category}* &nbsp; ({rec.word_count} words, {rec.answer_duration:.0f}s)",
                unsafe_allow_html=True,
            )
            st.caption(f"> {rec.question_text}")
            with st.expander("IO Evaluation", expanded=False):
                st.markdown(rec.evaluation)

    st.markdown("---")

    # ── Level-up / retry / complete action buttons ────────────────────────────
    if summary.next_level is None and not summary.levelled_up:
        # Already at ADVANCED and didn't level up — still let them continue
        st.info("You are at the Advanced level. Continue practising to sharpen your skills.")

    if summary.levelled_up and summary.next_level:
        next_colour = _LEVEL_COLOURS.get(summary.next_level, "#555")
        btn_label   = f"Start Next Interview: Level {summary.next_level.value}"
        st.success(
            f"Congratulations! You have unlocked the "
            f"**{summary.next_level.value}** level."
        )
    elif summary.next_level:
        btn_label = f"Retry Level {summary.level_completed.value} (new questions)"
        st.warning(
            f"Score was below the threshold for {summary.next_level.value}. "
            f"You will retry {summary.level_completed.value} with fresh questions."
        )
    else:
        btn_label = f"Continue at {summary.level_completed.value} (new questions)"

    col_next, col_end = st.columns([2, 1])
    with col_next:
        # Check if questions remain before showing the button
        test_ls = LevelStateManager(
            current_level=summary.next_level if (summary.levelled_up and summary.next_level)
                          else summary.level_completed,
            used_ids=set(ls.used_ids),
        )
        questions_remain = bool(QUESTION_BANK[test_ls.current_level])

        if st.button(btn_label, type="primary", use_container_width=True, key="mi_next_level"):
            with st.spinner("Loading next session..."):
                try:
                    new_session = controller.start_next_level(session)
                    _store_session(new_session)
                    st.rerun()
                except RuntimeError as e:
                    st.error(str(e))

    with col_end:
        if st.button("End & Save Report", use_container_width=True, key="mi_end_from_eval"):
            _abort_interview(controller, rm)


# ─── Complete Screen ──────────────────────────────────────────────────────────
def _render_complete_screen(
    session:    InterviewSession,
    controller: SSBInterviewController,
    rm:         RecordingManager,
) -> None:
    rm.render_stop_recording_js()

    st.subheader("All Sessions Complete")
    st.success("You have exhausted the question bank. Outstanding commitment.")

    ls     = session.level_state
    scores = [r.olq_score     for r in session.records if r.olq_score > 0]
    words  = [r.word_count    for r in session.records if r.word_count > 0]
    durs   = [r.answer_duration for r in session.records if r.answer_duration > 0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Questions",    ls.total_q_count)
    c2.metric("Sessions Completed", ls.session_number)
    c3.metric("Highest Level",      ls.current_level.value)
    c4.metric("Avg OLQ Score",      f"{sum(scores)/len(scores):.1f}/10" if scores else "N/A")

    st.markdown("---")

    # Save recording
    st.subheader("Save Your Session Recording")
    st.caption("Your interview was recorded locally. Click below to download.")
    rm.render_save_button(height=95)

    st.markdown("---")

    # All evaluation summaries
    if session.evaluation:
        st.subheader("Latest Evaluation Summary")
        st.markdown(f"```\n{session.evaluation.remark}\n```")

    # Full transcript
    with st.expander("Full Interview Transcript", expanded=False):
        for i, rec in enumerate(session.records, 1):
            st.markdown(
                f"**Q{i}** [{rec.level.value} — {rec.category}] "
                f"*(score {rec.olq_score}/10, {rec.word_count} words, {rec.answer_duration:.0f}s)*"
            )
            st.markdown(f"> {rec.question_text}")
            st.markdown(f"**Answer:** {rec.answer}")
            with st.expander("IO Evaluation", expanded=False):
                st.markdown(rec.evaluation)
            st.markdown("---")

    st.markdown("---")
    if st.button("Start Fresh Interview", type="primary", use_container_width=True):
        _reset_session(controller)


# ─── Shared Handlers ──────────────────────────────────────────────────────────
def _handle_submit(
    answer:     str,
    controller: SSBInterviewController,
) -> None:
    """Always reads session fresh from st.session_state to avoid stale reference."""
    if not answer.strip():
        st.warning("Please provide an answer — type it or use the voice panel.")
        return

    # Read session fresh — never use a captured reference from render time
    session: InterviewSession = st.session_state["mi_session"]

    status = st.empty()
    status.info("⏳ Submitting your answer to the Interviewing Officer...")

    try:
        updated = controller.submit_answer(session, answer.strip())
        status.empty()
        if updated.records:
            st.session_state["mi_last_evaluation"] = updated.records[-1].evaluation
        _store_session(updated)
        if _ANSWER_KEY in st.session_state:
            del st.session_state[_ANSWER_KEY]
        st.rerun()
    except ValueError as e:
        status.empty()
        st.warning(str(e))
    except RuntimeError as e:
        status.empty()
        err = str(e)
        if "busy" in err.lower() or "timeout" in err.lower() or "attempt" in err.lower():
            st.error(
                "**Service is busy — could not evaluate your answer.**\n\n"
                "Please wait a moment and click Submit again."
            )
            if st.button("🔄 Retry Submit", key="retry_submit"):
                st.rerun()
        else:
            st.error(f"Error: {err}")
    except Exception as e:
        status.empty()
        st.error(f"Unexpected error: {e}")


def _abort_interview(controller: SSBInterviewController, rm: RecordingManager) -> None:
    rm.render_stop_recording_js()
    _reset_session(controller)


def _store_session(session: InterviewSession) -> None:
    st.session_state["mi_session"]          = session
    st.session_state["mi_voice_transcript"] = ""
    st.session_state["mi_eval_summary_text"] = ""


def _reset_session(controller: SSBInterviewController) -> None:
    st.session_state["mi_session"]           = controller.reset()
    st.session_state["mi_last_evaluation"]   = ""
    st.session_state["mi_voice_transcript"]  = ""
    st.session_state["mi_eval_summary_text"] = ""
    if _ANSWER_KEY in st.session_state:
        del st.session_state[_ANSWER_KEY]
    st.rerun()
