# 🎖️ SSB Preparation Assistant

An AI-powered SSB (Services Selection Board) interview preparation tool built with Streamlit and Google Gemini.

## Features

- **Personal Interview** — OLQ-based feedback on your answers with follow-up questions
- **Lecturette** — Confidence score, filler-word detection, and delivery analysis
- **Group Discussion** — Counter-argument simulation for debate practice
- **SRT** — Situation Reaction Test grading (1–10) with rewritten model answers
- **SSB Mock Interview** — Full sequential interview with:
  - 3-tier Level-Up System (Basic → Intermediate → Advanced)
  - Live camera proctoring (browser-side, no data sent to server)
  - Auto-TTS question delivery + auto-mic activation
  - Cross-questioning engine (warm-up → drill-down mode)
  - 10-question evaluation summaries with proficiency scoring
  - Session recording download (.webm)

---

## One-Step Setup

### Prerequisites

- Python 3.10 or higher
- [ffmpeg](https://ffmpeg.org/download.html) installed and on your PATH (required by Whisper)
- A Gemini API key — get one free at [aistudio.google.com](https://aistudio.google.com/app/apikey)

### Install and run

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd ssb-prep-assistant

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Add your Gemini API key
mkdir -p .streamlit
echo 'GEMINI_API_KEY = "your-key-here"' > .streamlit/secrets.toml

# 5. Run the app
streamlit run main.py
```

The app opens at **http://localhost:8501** in your browser.

---

## Project Structure

```
ssb-prep-assistant/
├── main.py                  # Entry point — Streamlit app + feedback modules
├── mock_interview_ui.py     # Mock Interview UI (level-up system, proctoring)
├── ssb_mock_interview.py    # SSBInterviewController + LevelStateManager
├── ssb_question_bank.py     # 90-question bank (Basic / Intermediate / Advanced)
├── ssb_proctoring.py        # RecordingManager (camera, mic, MediaRecorder)
├── requirements.txt         # Pinned Python dependencies
├── .env.example             # Environment variable reference
├── .gitignore
└── .streamlit/
    └── secrets.toml         # ← create this from .env.example (not committed)
```

**Entry point:** `main.py`  
Run with: `streamlit run main.py`

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | ✅ Yes | Google Gemini API key. Set in `.streamlit/secrets.toml` |

See `.env.example` for the template.

---

## Voice & Camera Support

The Mock Interview module uses browser APIs:

| Feature | Chrome | Edge | Firefox | Safari |
|---|---|---|---|---|
| Camera preview | ✅ | ✅ | ✅ | ✅ |
| TTS (question spoken aloud) | ✅ | ✅ | ✅ | ✅ |
| STT (voice answer) | ✅ | ✅ | ❌ | ❌ |
| Session recording | ✅ | ✅ | ✅ | ⚠️ partial |

**Recommended browser: Chrome or Edge.**  
The app works fully with typed answers in all browsers.

---

## Deployment (Streamlit Community Cloud)

1. Push this repo to GitHub (ensure `.streamlit/secrets.toml` is in `.gitignore`)
2. Go to [share.streamlit.io](https://share.streamlit.io) → New app
3. Set **Main file path** to `main.py`
4. Under **Advanced settings → Secrets**, add:
   ```toml
   GEMINI_API_KEY = "your-key-here"
   ```
5. Deploy

---

## API Rate Limits

The app uses exponential backoff (5 retries, 1 s initial delay, ±0.5 s jitter) on all Gemini calls. If you hit quota limits on the free tier, wait ~60 seconds or upgrade your Gemini plan at [aistudio.google.com](https://aistudio.google.com).
