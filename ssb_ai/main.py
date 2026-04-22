import streamlit as st
from google import genai
from google.genai import types
import whisper
import os
import random
import logging

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception,
)

# ─── Logging (errors visible in terminal / Streamlit Cloud logs) ─────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Page Config ────────────────────────────────────────────────────────────
st.set_page_config(page_title="SSB Preparation Assistant", page_icon="🎖️")

# ─── Model Configuration ─────────────────────────────────────────────────────
GEMINI_MODEL    = "gemini-2.5-flash"
MAX_ATTEMPTS    = 10   # total attempts before giving up
MAX_WAIT_SEC    = 10   # cap per-attempt wait so user never waits > 10 s
RETRYABLE_CODES = {"429", "503"}

# ─── Dynamic status messages shown to the user during retries ────────────────
_RETRY_MESSAGES = {
    1:  "Analyzing your response...",
    2:  "Still analyzing, please wait...",
    3:  "Connecting to AI assessor...",
    4:  "Taking a moment longer than usual...",
    5:  "Still working on it — almost there...",
    6:  "The service is a bit busy right now...",
    7:  "Holding on, retrying the connection...",
    8:  "Almost there, connection is a bit slow...",
    9:  "One more try...",
    10: "Final attempt...",
}

def _retry_msg(attempt: int) -> str:
    return _RETRY_MESSAGES.get(attempt, "Processing...")

def _is_retryable_error(exc: Exception) -> bool:
    """Returns True for 429 (quota) and 503 (unavailable) errors only."""
    s = str(exc).lower()
    return any(k in s for k in (
        "429", "503", "resource_exhausted", "quota",
        "service_unavailable", "overloaded",
    ))

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

# ─── Core AI Function ─────────────────────────────────────────────────────────
def get_feedback(candidate_response: str, mode: str, extra_context: str = "") -> str:
    """
    Sends candidate input to Gemini with tenacity-powered retry logic.

    Retry policy:
      - 10 attempts total
      - wait_exponential_jitter: starts ~1 s, doubles each attempt, capped at 10 s
      - Only retries on 429 / 503 (quota / unavailable)
      - Dynamic Streamlit status message updates on each retry
      - Logs error code to terminal on every failed attempt
      - Shows friendly 'Network Timeout' button after all attempts exhausted
    """
    system_instruction = MODULE_SYSTEM_INSTRUCTIONS.get(
        mode, MODULE_SYSTEM_INSTRUCTIONS["Personal Interview"]
    )
    if extra_context:
        user_prompt = f"{extra_context}\n\nCandidate's Response:\n\"\"\"{candidate_response}\"\"\""
    else:
        user_prompt = f"Candidate's Response:\n\"\"\"{candidate_response}\"\"\""

    # Mutable attempt counter accessible inside the nested function
    attempt_counter = {"n": 0}
    status_placeholder = st.empty()

    @retry(
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=MAX_WAIT_SEC, jitter=1),
        retry=retry_if_exception(_is_retryable_error),
        reraise=True,
    )
    def _call() -> str:
        attempt_counter["n"] += 1
        n = attempt_counter["n"]
        msg = _retry_msg(n)

        # Update Streamlit spinner message dynamically
        if n == 1:
            status_placeholder.info(f"⏳ {msg}")
        else:
            status_placeholder.warning(f"⏳ Attempt {n}/{MAX_ATTEMPTS}: {msg}")

        try:
            result = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7,
                ),
            )
            status_placeholder.empty()
            return result.text.strip()

        except Exception as e:
            # Log error code to terminal on every failure
            err_str = str(e)
            code = "429" if "429" in err_str else ("503" if "503" in err_str else "unknown")
            logger.error(
                "Gemini API error on attempt %d/%d — code: %s — %s",
                n, MAX_ATTEMPTS, code, err_str[:200],
            )
            raise  # let tenacity decide whether to retry

    try:
        return _call()
    except Exception as e:
        status_placeholder.empty()
        err_str = str(e)
        code = "429" if "429" in err_str else ("503" if "503" in err_str else "unknown")
        logger.error("All %d attempts exhausted. Final error code: %s — %s", MAX_ATTEMPTS, code, err_str[:300])

        # Friendly UI — no raw error shown to user
        st.error(
            "**Service is busy — Network Timeout.**\n\n"
            "The AI assessor couldn't be reached after several attempts. "
            "This is usually a temporary quota issue."
        )
        if st.button("🔄 Try Again", key=f"retry_btn_{random.randint(0, 99999)}"):
            st.rerun()
        st.stop()

# ─── Audio Transcription ──────────────────────────────────────────────────────
import tempfile

def transcribe_audio(audio_bytes) -> str:
    """
    Transcribes audio using Whisper.
    Accepts either an UploadedFile (from st.audio_input) or a BytesIO object.
    Uses a secure temp file that is always cleaned up.
    """
    # st.audio_input returns an UploadedFile — use .read(), not .getbuffer()
    if hasattr(audio_bytes, "read"):
        raw = audio_bytes.read()
    elif hasattr(audio_bytes, "getbuffer"):
        raw = bytes(audio_bytes.getbuffer())
    else:
        raw = bytes(audio_bytes)

    if not raw:
        raise ValueError("Audio buffer is empty — nothing was recorded.")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(raw)
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
        # Debug: confirm bytes reached Python backend
        audio_input.seek(0)
        byte_size = len(audio_input.read())
        audio_input.seek(0)
        st.caption(f"✅ Audio captured — {byte_size:,} bytes received by server.")

        if byte_size < 1000:
            st.warning("Recording seems too short. Please speak for at least 2 seconds.")
        else:
            with st.spinner("Converting speech to text..."):
                try:
                    spoken_text = transcribe_audio(audio_input)
                    if spoken_text:
                        st.success("Transcription complete!")
                        st.info(f"**What you said:** {spoken_text}")
                        st.session_state["spoken_text"] = spoken_text
                    else:
                        st.warning("Transcription returned empty. Try speaking more clearly.")
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
