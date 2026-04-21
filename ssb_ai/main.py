import streamlit as st
from google import genai
from google.genai import types
import whisper
import os
import time
import random

# ─── Page Config ────────────────────────────────────────────────────────────
st.set_page_config(page_title="SSB Preparation Assistant", page_icon="🎖️")

# ─── Model Configuration ─────────────────────────────────────────────────────
# gemini-2.5-flash: latest flash model, higher quota than 2.0-flash
GEMINI_MODEL        = "gemini-2.5-flash"
MAX_RETRIES         = 5    # Maximum number of retry attempts
INITIAL_DELAY_SEC   = 1.0  # Base delay in seconds (doubles each retry)
JITTER_MAX_SEC      = 0.5  # Max random jitter added to each delay
RETRYABLE_CODES     = {"429", "503"}  # Status codes that trigger a retry

# ─── Load Models (cached — load once, reuse across interactions) ─────────────
@st.cache_resource
def load_whisper_model():
    return whisper.load_model("base")

@st.cache_resource
def load_gemini_client():
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
    except (KeyError, FileNotFoundError):
        st.error(
            "**GEMINI_API_KEY not found.**\n\n"
            "Go to **Streamlit Cloud → App Settings → Secrets** and add:\n\n"
            "```toml\nGEMINI_API_KEY = \"your_key_here\"\n```\n\n"
            "Get a free key at https://aistudio.google.com/app/apikey"
        )
        st.stop()
    return genai.Client(api_key=api_key)

model_whisper = load_whisper_model()
gemini_client = load_gemini_client()

# ─── Module-Specific System Instructions ─────────────────────────────────────
# Dictionary mapping (Switch-Case equivalent) — each module gets its own
# system instruction so the AI's analysis focus changes per task.
MODULE_SYSTEM_INSTRUCTIONS: dict[str, str] = {
    "Personal Interview": """
You are a Senior Interviewing Officer (IO) at the Services Selection Board (SSB), India.
Evaluate the candidate's interview answer for SSB preparation.

Focus on these Officer Like Qualities (OLQs):
- Effective Intelligence, Reasoning Ability, Power of Expression
- Self-Confidence, Sense of Responsibility, Initiative, Liveliness

After your feedback, generate ONE sharp follow-up question an IO would realistically
ask based on the candidate's answer, to simulate a real interview continuation.

Respond in this EXACT format:
---
✅ STRENGTHS
(OLQs demonstrated with brief reasons.)

🔧 IMPROVEMENTS
(Specific, exam-oriented suggestions. Rewrite weak sentences where helpful.)

🎯 FOLLOW-UP QUESTION
(One realistic IO follow-up question based on the answer above.)

💡 MOTIVATIONAL NOTE
(One short, genuine motivational line.)
---
""",

    "Lecturette": """
You are a Senior GTO (Group Testing Officer) at the Services Selection Board (SSB), India.
Evaluate the candidate's Lecturette transcript for SSB preparation.

Focus on:
- Power of Expression, Effective Intelligence, Reasoning Ability
- Self-Confidence (penalise filler words: um, uh, ah, like, basically, you know)
- Liveliness and ability to hold attention

Provide a CONFIDENCE SCORE (0–10) based on clarity, fluency, and absence of fillers.
List any filler words found and their count.

Respond in this EXACT format:
---
🎙️ CONFIDENCE SCORE: X/10

🚫 FILLERS DETECTED
(List each filler word and how many times it appeared. Write "None" if clean.)

✅ STRENGTHS
(OLQs demonstrated with brief reasons.)

🔧 IMPROVEMENTS
(Specific suggestions to improve delivery and content structure.)

💡 MOTIVATIONAL NOTE
(One short, genuine motivational line.)
---
""",

    "Group Discussion": """
You are a Senior GTO (Group Testing Officer) at the Services Selection Board (SSB), India.
Evaluate the candidate's Group Discussion entry for SSB preparation.

Focus on:
- Social Adaptability, Cooperation, Ability to Influence Group
- Reasoning Ability, Power of Expression, Initiative

After your feedback, generate EXACTLY 3 opposing viewpoints that other GD participants
might raise, so the candidate can practice defending their stance.

Respond in this EXACT format:
---
✅ STRENGTHS
(OLQs demonstrated with brief reasons.)

🔧 IMPROVEMENTS
(Specific suggestions to improve GD contribution quality.)

⚔️ COUNTER-ARGUMENTS TO DEFEND AGAINST
1. (First opposing viewpoint)
2. (Second opposing viewpoint)
3. (Third opposing viewpoint)

💡 MOTIVATIONAL NOTE
(One short, genuine motivational line.)
---
""",

    "Situation Reaction Test (SRT)": """
You are a Senior Psychologist at the Services Selection Board (SSB), India.
Evaluate the candidate's response to an SRT situation for SSB preparation.

Focus on:
- Speed of Decision Making, Initiative, Sense of Responsibility
- Effective Intelligence, Self-Confidence, Cooperation

Grade the response on a scale of 1–10 based on:
- Decisiveness (did they act quickly and clearly?)
- Leadership (did they take charge appropriately?)
- Practicality (is the action realistic and effective?)
- OLQ alignment (does the response reflect officer-like thinking?)

Respond in this EXACT format:
---
📊 SRT GRADE: X/10

✅ STRENGTHS
(OLQs demonstrated with brief reasons.)

🔧 IMPROVEMENTS
(What a stronger SRT response would look like — show a rewritten version.)

💡 MOTIVATIONAL NOTE
(One short, genuine motivational line.)
---
""",
}

# ─── SRT Situation Bank ───────────────────────────────────────────────────────
SRT_SITUATIONS: list[str] = [
    "You are leading a patrol when your radio fails mid-mission. Two team members are injured and the nearest base is 10 km away.",
    "A junior colleague is found leaking confidential unit information. He is also your closest friend.",
    "Your unit is stranded due to a flash flood. Supplies last 48 hours but rescue ETA is 72 hours.",
    "During a group trek, one member refuses to continue and is demoralising the rest of the team.",
    "You discover that your senior officer has made a critical error in the operation plan that could endanger lives.",
    "A civilian approaches your patrol claiming to have information about enemy movement, but your orders say to avoid civilian contact.",
    "Your team wins a competition but you notice the winning entry may have violated the rules. No one else has noticed.",
    "You are the only one awake during night duty and notice a fire starting in the supply tent.",
    "A new recruit under your command is being bullied by senior soldiers. Reporting it may create tension in the unit.",
    "You are given two urgent tasks simultaneously by two different senior officers with equal priority.",
    "During a river crossing exercise, a team member panics and refuses to cross. The group is falling behind schedule.",
    "You find a wallet with a large sum of cash and an ID card near the barracks.",
]

def get_random_situation() -> str:
    """Returns a random SRT situation and stores it in session state."""
    situation = random.choice(SRT_SITUATIONS)
    st.session_state["current_situation"] = situation
    return situation

# ─── Exponential Backoff Helper ───────────────────────────────────────────────
def _is_retryable(error_str: str) -> bool:
    """Returns True if the error string indicates a retryable status (429 or 503)."""
    return (
        "429" in error_str
        or "503" in error_str
        or "resource_exhausted" in error_str
        or "quota" in error_str
        or "service_unavailable" in error_str
        or "overloaded" in error_str
    )

def _backoff_delay(attempt: int) -> float:
    """
    Computes exponential backoff delay with random jitter.

    Formula: min(INITIAL_DELAY * 2^(attempt-1), 32s) + uniform(0, JITTER_MAX)

    Args:
        attempt: Current attempt number (1-indexed).

    Returns:
        Seconds to sleep before the next retry.
    """
    delay = INITIAL_DELAY_SEC * (2 ** (attempt - 1))   # 1, 2, 4, 8, 16 …
    delay = min(delay, 32.0)                            # cap at 32 seconds
    jitter = random.uniform(0, JITTER_MAX_SEC)          # add small random variation
    return delay + jitter

# ─── Core AI Function ─────────────────────────────────────────────────────────
def get_feedback(candidate_response: str, mode: str, extra_context: str = "") -> str:
    """
    Sends candidate input to Gemini with the module-specific system instruction.
    Implements exponential backoff with jitter on 429 (quota) and 503 (unavailable).

    Retry schedule (before jitter):
        Attempt 1 → wait 1s → Attempt 2 → wait 2s → Attempt 3 → wait 4s →
        Attempt 4 → wait 8s → Attempt 5 → wait 16s → give up

    Args:
        candidate_response: The user's typed or transcribed answer.
        mode:               Active practice module name.
        extra_context:      Optional prefix (e.g., SRT situation text).

    Returns:
        AI feedback as a clean string ready for display.

    Raises:
        RuntimeError: If all retries are exhausted or a non-retryable error occurs.
    """
    system_instruction = MODULE_SYSTEM_INSTRUCTIONS.get(mode, MODULE_SYSTEM_INSTRUCTIONS["Personal Interview"])

    # Build the user-facing prompt
    if extra_context:
        user_prompt = f"{extra_context}\n\nCandidate's Response:\n\"\"\"{candidate_response}\"\"\""
    else:
        user_prompt = f"Candidate's Response:\n\"\"\"{candidate_response}\"\"\""

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7,
                ),
            )
            # Return clean string — strip leading/trailing whitespace
            return result.text.strip()

        except Exception as e:
            last_error = e
            error_str = str(e).lower()

            if _is_retryable(error_str):
                if attempt < MAX_RETRIES:
                    wait = _backoff_delay(attempt)
                    st.warning(
                        f"⏳ API temporarily unavailable (attempt {attempt}/{MAX_RETRIES}). "
                        f"Retrying in {wait:.1f}s…"
                    )
                    time.sleep(wait)
                    continue
                else:
                    raise RuntimeError(
                        f"API unavailable after {MAX_RETRIES} attempts (429/503). "
                        "Please wait a moment and try again, or check your quota at "
                        "https://aistudio.google.com"
                    ) from e
            else:
                # Non-retryable error — fail immediately
                raise RuntimeError(f"Gemini API error: {e}") from e

    raise RuntimeError(f"All {MAX_RETRIES} retries exhausted. Last error: {last_error}")

# ─── Audio Transcription ──────────────────────────────────────────────────────
import tempfile

def transcribe_audio(audio_bytes) -> str:
    """Transcribes audio using Whisper. Uses a secure temp file that is always cleaned up."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes.getbuffer())
        tmp_path = tmp.name
    try:
        result = model_whisper.transcribe(tmp_path, fp16=False, language="en")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return result["text"].strip()

# ─── UI ───────────────────────────────────────────────────────────────────────
st.title("🎖️ SSB Preparation Assistant")
st.markdown(
    "Practice your **Personal Interview, Lecturette, Group Discussion, or SRT** responses. "
    "Get instant OLQ-based feedback — just like a real SSB assessor would give."
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
ALL_MODULES = ["SSB Mock Interview"] + list(MODULE_SYSTEM_INSTRUCTIONS.keys())

with st.sidebar:
    st.header("⚙️ Settings")
    mode = st.selectbox(
        "Practice Module",
        ALL_MODULES,
    )
    st.markdown("---")
    st.markdown(
        "**OLQs Evaluated:**\n"
        "- Effective Intelligence\n"
        "- Reasoning Ability\n"
        "- Power of Expression\n"
        "- Social Adaptability\n"
        "- Cooperation\n"
        "- Sense of Responsibility\n"
        "- Initiative\n"
        "- Self-Confidence\n"
        "- Speed of Decision Making\n"
        "- Ability to Influence Group\n"
        "- Liveliness"
    )
    st.markdown("---")
    st.caption(f"Model: `{GEMINI_MODEL}`")

# ── Route to Mock Interview module ───────────────────────────────────────────
if mode == "SSB Mock Interview":
    from mock_interview_ui import render_mock_interview
    render_mock_interview()
    st.stop()

# ── SRT: Show situation card BEFORE the input box ────────────────────────────
srt_situation = ""
if mode == "Situation Reaction Test (SRT)":
    st.subheader("📋 Your Situation")

    # Generate a new situation only once per session (or on button press)
    if "current_situation" not in st.session_state:
        get_random_situation()

    srt_situation = st.session_state["current_situation"]
    st.info(f"**Situation:** {srt_situation}")

    if st.button("🔀 New Situation"):
        get_random_situation()
        st.rerun()

    srt_situation = st.session_state["current_situation"]

# ── Lecturette: show timer note ───────────────────────────────────────────────
if mode == "Lecturette":
    st.info("⏱️ **Lecturette tip:** You have 3 minutes. Use the voice tab to record your speech, then evaluate.")

# ─── Input Tabs ───────────────────────────────────────────────────────────────
tab_text, tab_voice = st.tabs(["✍️ Text Input", "🎙️ Voice Input"])

# ── Tab 1: Text Input ─────────────────────────────────────────────────────────
with tab_text:
    placeholder_map = {
        "Personal Interview":          "e.g., Why do you want to join the Indian Army?",
        "Lecturette":                  "e.g., Paste or type your speech transcript here...",
        "Group Discussion":            "e.g., I believe social media has more benefits than drawbacks because...",
        "Situation Reaction Test (SRT)": "e.g., I would first ensure the safety of the injured, then...",
    }

    user_text = st.text_area(
        "Enter your response below:",
        placeholder=placeholder_map.get(mode, "Type your response here..."),
        height=220,
        key="text_input",
    )

    if st.button("🔍 Evaluate My Response", key="eval_text"):
        if user_text.strip():
            with st.spinner("Analyzing your Officer Like Qualities..."):
                try:
                    extra = f"Situation: {srt_situation}" if srt_situation else ""
                    feedback = get_feedback(user_text.strip(), mode, extra_context=extra)

                    # ── Feedback Dashboard ────────────────────────────────────
                    st.markdown("---")
                    st.subheader("📋 Assessor's Feedback")
                    st.markdown(feedback)
                    st.markdown("---")

                except RuntimeError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"Unexpected error: {e}")
        else:
            st.warning("Please type your response before evaluating.")

# ── Tab 2: Voice Input ────────────────────────────────────────────────────────
with tab_voice:
    st.subheader("Speak Your Response")
    if mode == "Lecturette":
        st.markdown("🎙️ Record your 3-minute Lecturette. The AI will analyze fillers and confidence.")
    else:
        st.markdown("Click the microphone, speak your answer, then click **Evaluate**.")

    audio_input = st.audio_input("🎤 Record your response", key="voice_input")

    if audio_input:
        st.audio(audio_input)
        with st.spinner("Converting speech to text..."):
            try:
                spoken_text = transcribe_audio(audio_input)
                st.success("Transcription complete!")
                st.info(f"**What you said:** {spoken_text}")
                st.session_state["spoken_text"] = spoken_text
            except Exception as e:
                st.error(f"Transcription error: {e}")

    if st.button("🔍 Evaluate Spoken Response", key="eval_voice"):
        spoken = st.session_state.get("spoken_text", "").strip()
        if spoken:
            with st.spinner("Analyzing your Officer Like Qualities..."):
                try:
                    extra = f"Situation: {srt_situation}" if srt_situation else ""
                    feedback = get_feedback(spoken, mode, extra_context=extra)

                    # ── Feedback Dashboard ────────────────────────────────────
                    st.markdown("---")
                    st.subheader("📋 Assessor's Feedback")
                    st.markdown(feedback)
                    st.markdown("---")

                except RuntimeError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"Unexpected error: {e}")
        else:
            st.warning("Please record your response first.")
