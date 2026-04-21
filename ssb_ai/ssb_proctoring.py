"""
ssb_proctoring.py
─────────────────
RecordingManager — browser-side camera + audio recording component.

Renders a self-contained HTML/JS iframe that:
  1. Requests getUserMedia (camera + mic) on mount
  2. Shows a live PiP-style camera preview
  3. Manages MediaRecorder lifecycle (start / stop / download)
  4. Handles auto-mic activation after TTS finishes speaking
  5. Streams real-time STT transcript back via postMessage
  6. Compiles recorded chunks into a Blob and triggers MP4 download

All recording is handled entirely in the browser (Blob + URL.createObjectURL).
No video data is sent to the server.

Usage (from mock_interview_ui.py):
    from ssb_proctoring import RecordingManager
    rm = RecordingManager()
    rm.render_camera_preview()          # PiP camera widget
    rm.render_voice_input(question)     # auto-mic + live transcript
    rm.render_save_button()             # download MP4 button
"""

from __future__ import annotations
import streamlit.components.v1 as components


# ─── Shared JS state key ──────────────────────────────────────────────────────
# All three components share the same window-level state object so the
# MediaRecorder instance and stream are accessible across iframes via
# window.parent references.

_SHARED_INIT_JS = """
if (!window._ssbProctor) {
  window._ssbProctor = {
    stream:       null,   // MediaStream from getUserMedia
    recorder:     null,   // MediaRecorder instance
    chunks:       [],     // recorded Blob chunks
    videoUrl:     null,   // object URL for download
    isRecording:  false,
    recognition:  null,   // SpeechRecognition instance
    micActive:    false,
  };
}
"""


# ─── Camera Preview Component ─────────────────────────────────────────────────
_CAMERA_PREVIEW_HTML = """
<!DOCTYPE html>
<html>
<head>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #0d1117; font-family: 'Segoe UI', sans-serif; }

  #camera-container {
    position: relative;
    width: 100%;
    max-width: 320px;
    border-radius: 10px;
    overflow: hidden;
    border: 2px solid #1a3a5c;
    background: #111;
  }

  #camera-feed {
    width: 100%;
    display: block;
    transform: scaleX(-1);   /* mirror effect — natural for self-view */
    border-radius: 8px;
  }

  #camera-overlay {
    position: absolute;
    bottom: 0; left: 0; right: 0;
    padding: 6px 10px;
    background: linear-gradient(transparent, rgba(0,0,0,0.75));
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  #rec-indicator {
    display: none;
    align-items: center;
    gap: 6px;
    color: #fff;
    font-size: 12px;
    font-weight: 600;
  }
  #rec-indicator.active { display: flex; }
  #rec-dot {
    width: 10px; height: 10px;
    border-radius: 50%;
    background: #e74c3c;
    animation: blink 1s infinite;
  }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.2} }

  #cam-status {
    color: #aaa;
    font-size: 11px;
  }

  #no-camera {
    display: none;
    padding: 20px;
    text-align: center;
    color: #888;
    font-size: 13px;
  }
</style>
</head>
<body>
<div id="camera-container">
  <video id="camera-feed" autoplay muted playsinline></video>
  <div id="camera-overlay">
    <div id="rec-indicator"><div id="rec-dot"></div> REC</div>
    <span id="cam-status">Starting camera...</span>
  </div>
</div>
<div id="no-camera">Camera unavailable.<br>Check browser permissions.</div>

<script>
const p = window.parent;

// Initialise shared state on parent window
if (!p._ssbProctor) {
  p._ssbProctor = {
    stream: null, recorder: null, chunks: [],
    videoUrl: null, isRecording: false,
    recognition: null, micActive: false,
  };
}

const state = p._ssbProctor;

async function initCamera() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 320, height: 240, facingMode: 'user' },
      audio: true,
    });
    state.stream = stream;

    const video = document.getElementById('camera-feed');
    video.srcObject = stream;

    // Start MediaRecorder
    const mimeType = MediaRecorder.isTypeSupported('video/webm;codecs=vp9,opus')
      ? 'video/webm;codecs=vp9,opus'
      : 'video/webm';

    state.recorder  = new MediaRecorder(stream, { mimeType });
    state.chunks    = [];
    state.isRecording = true;

    state.recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) state.chunks.push(e.data);
    };

    state.recorder.onstop = () => {
      const blob = new Blob(state.chunks, { type: mimeType });
      if (state.videoUrl) URL.revokeObjectURL(state.videoUrl);
      state.videoUrl = URL.createObjectURL(blob);
      state.isRecording = false;
      // Notify save button component
      p.postMessage({ type: 'ssb_recording_ready', url: state.videoUrl }, '*');
    };

    state.recorder.start(1000);  // collect chunks every 1 s

    document.getElementById('rec-indicator').classList.add('active');
    document.getElementById('cam-status').innerText = 'Live';

  } catch (err) {
    document.getElementById('camera-container').style.display = 'none';
    document.getElementById('no-camera').style.display = 'block';
    console.warn('Camera error:', err);
  }
}

initCamera();
</script>
</body>
</html>
"""


# ─── Voice Input Component ────────────────────────────────────────────────────
def _build_voice_input_html(question_text: str, textarea_key: str) -> str:
    """
    Builds the voice input component HTML for a given question.

    Auto-speaks the question via TTS, then auto-activates the mic once TTS
    finishes. Shows real-time transcript.

    The transcript is written into the Streamlit text_area identified by
    ``textarea_key`` via two mechanisms:
      1. Direct DOM injection — finds the <textarea> in the parent document
         by its aria-label / data-testid and sets its value + dispatches an
         'input' event so React picks up the change.
      2. postMessage fallback — sends ``ssb_transcript`` so the bridge
         listener (injected separately) can also update session state.

    When the user clicks "Use This Answer", an ``ssb_auto_submit`` message
    is posted so the bridge can click the hidden submit button automatically.

    Args:
        question_text: The question the IO is asking (will be spoken aloud).
        textarea_key:  The Streamlit widget key of the answer text_area
                       (used to locate the DOM element).
    """
    safe_q = (
        question_text
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
        .replace("\r", "")
    )
    safe_key = textarea_key.replace('"', '\\"')

    return f"""
<!DOCTYPE html>
<html>
<head>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: transparent; font-family: 'Segoe UI', sans-serif; padding: 8px; }}

  .panel {{
    background: #f8fafc;
    border: 1px solid #dde3ea;
    border-radius: 8px;
    padding: 12px 14px;
  }}

  #mic-status {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
  }}

  #mic-icon {{
    font-size: 22px;
    transition: transform 0.2s;
  }}
  #mic-icon.active {{ animation: pulse 0.8s infinite alternate; }}
  @keyframes pulse {{ from{{transform:scale(1)}} to{{transform:scale(1.25)}} }}

  #status-text {{
    font-size: 13px;
    color: #555;
    flex: 1;
  }}

  #transcript-live {{
    min-height: 60px;
    max-height: 120px;
    overflow-y: auto;
    background: #fff;
    border: 1px solid #cdd5df;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 13px;
    color: #222;
    line-height: 1.5;
    margin-bottom: 10px;
  }}
  #transcript-live .interim {{ color: #999; font-style: italic; }}

  .btn-row {{ display: flex; gap: 8px; }}

  .ctrl-btn {{
    flex: 1;
    padding: 7px 0;
    border: none;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s;
  }}
  #btn-mic-toggle {{
    background: #1a3a5c;
    color: #fff;
  }}
  #btn-mic-toggle:hover {{ background: #245080; }}
  #btn-mic-toggle.stop  {{ background: #c0392b; }}
  #btn-mic-toggle.stop:hover {{ background: #a93226; }}

  #btn-use-transcript {{
    background: #27ae60;
    color: #fff;
    display: none;
  }}
  #btn-use-transcript:hover {{ background: #219a52; }}
</style>
</head>
<body>
<div class="panel">
  <div id="mic-status">
    <span id="mic-icon">🎙</span>
    <span id="status-text">Preparing question...</span>
  </div>
  <div id="transcript-live"><span style="color:#bbb;">Your answer will appear here...</span></div>
  <div class="btn-row">
    <button class="ctrl-btn" id="btn-mic-toggle" onclick="toggleMic()">Start Speaking</button>
    <button class="ctrl-btn" id="btn-use-transcript" onclick="useTranscript()">
      Use This Answer &amp; Submit
    </button>
  </div>
</div>

<script>
const QUESTION     = "{safe_q}";
const TEXTAREA_KEY = "{safe_key}";
const p = window.parent;

// Ensure shared state exists on parent window
if (!p._ssbProctor) {{
  p._ssbProctor = {{
    stream: null, recorder: null, chunks: [],
    videoUrl: null, isRecording: false,
    recognition: null, micActive: false,
  }};
}}
const state = p._ssbProctor;

let finalTranscript = '';
let micOn = false;

// ── Inject transcript into the Streamlit textarea in the parent doc ───────
// Streamlit uses React-controlled inputs. Setting .value alone is not enough;
// we must also dispatch a native 'input' event so React's synthetic handler
// fires and updates its internal state.
function injectIntoTextarea(text) {{
  const doc = p.document;

  // Strategy 1: find by data-testid attribute Streamlit adds
  let ta = doc.querySelector('textarea[data-testid="stTextArea-' + TEXTAREA_KEY + '"]');

  // Strategy 2: find by aria-label (Streamlit sets this to the widget label)
  if (!ta) {{
    ta = Array.from(doc.querySelectorAll('textarea'))
              .find(el => el.getAttribute('aria-label') === TEXTAREA_KEY
                       || el.id.includes(TEXTAREA_KEY));
  }}

  // Strategy 3: find the first visible textarea on the page (last resort)
  if (!ta) {{
    const all = Array.from(doc.querySelectorAll('textarea'));
    ta = all.find(el => el.offsetParent !== null) || null;
  }}

  if (ta) {{
    // Use React's internal setter so the synthetic onChange fires
    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
      p.HTMLTextAreaElement.prototype, 'value'
    ).set;
    nativeInputValueSetter.call(ta, text);
    ta.dispatchEvent(new p.Event('input', {{ bubbles: true }}));
    ta.dispatchEvent(new p.Event('change', {{ bubbles: true }}));
    ta.focus();
  }}
}}

// ── TTS: speak question, then auto-start mic ──────────────────────────────
function speakAndListen() {{
  if (!window.speechSynthesis) {{
    setStatus('🎙', 'Ready — click Start Speaking.');
    return;
  }}
  window.speechSynthesis.cancel();
  const utt = new SpeechSynthesisUtterance(QUESTION);
  utt.lang   = 'en-IN';
  utt.rate   = 0.90;
  utt.pitch  = 0.95;
  utt.volume = 1.0;

  const voices = window.speechSynthesis.getVoices();
  const v = voices.find(x => x.lang.startsWith('en') && x.name.toLowerCase().includes('male'))
         || voices.find(x => x.lang.startsWith('en')) || null;
  if (v) utt.voice = v;

  setStatus('🔊', 'Interviewing Officer is speaking...');
  document.getElementById('btn-mic-toggle').disabled = true;

  utt.onend = () => {{
    document.getElementById('btn-mic-toggle').disabled = false;
    setStatus('🎙', 'Your turn — microphone is active. Speak your answer.');
    startMic();
  }};
  utt.onerror = () => {{
    document.getElementById('btn-mic-toggle').disabled = false;
    setStatus('🎙', 'Ready — click Start Speaking.');
  }};

  if (voices.length === 0) {{
    window.speechSynthesis.onvoiceschanged = () => {{
      const v2 = window.speechSynthesis.getVoices()
        .find(x => x.lang.startsWith('en') && x.name.toLowerCase().includes('male'))
        || window.speechSynthesis.getVoices().find(x => x.lang.startsWith('en')) || null;
      if (v2) utt.voice = v2;
      window.speechSynthesis.speak(utt);
    }};
  }} else {{
    window.speechSynthesis.speak(utt);
  }}
}}

// ── STT ───────────────────────────────────────────────────────────────────
function startMic() {{
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {{
    setStatus('⚠️', 'Speech recognition not supported. Use Chrome.');
    return;
  }}

  const rec = new SR();
  rec.lang           = 'en-IN';
  rec.continuous     = true;
  rec.interimResults = true;
  state.recognition  = rec;
  micOn = true;
  finalTranscript    = '';

  const liveBox = document.getElementById('transcript-live');
  liveBox.innerHTML = '';

  const btn = document.getElementById('btn-mic-toggle');
  btn.textContent = 'Stop Recording';
  btn.classList.add('stop');
  document.getElementById('mic-icon').classList.add('active');

  rec.onresult = (event) => {{
    let interim = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {{
      const t = event.results[i][0].transcript;
      if (event.results[i].isFinal) finalTranscript += t + ' ';
      else interim += t;
    }}
    liveBox.innerHTML =
      finalTranscript +
      (interim ? '<span class="interim">' + interim + '</span>' : '');
    liveBox.scrollTop = liveBox.scrollHeight;

    // Keep the shared textarea in sync as the user speaks
    injectIntoTextarea(finalTranscript.trim());
  }};

  rec.onerror = (e) => {{
    setStatus('⚠️', 'Mic error: ' + e.error + '. Please try again.');
    resetMicUI();
  }};

  rec.onend = () => {{
    micOn = false;
    resetMicUI();
    if (finalTranscript.trim()) {{
      setStatus('✅', 'Done. Review transcript and click "Use This Answer & Submit".');
      document.getElementById('btn-use-transcript').style.display = 'block';
      // Ensure textarea has the final value
      injectIntoTextarea(finalTranscript.trim());
      // Also notify the bridge listener
      p.postMessage({{
        type: 'ssb_transcript',
        transcript: finalTranscript.trim(),
      }}, '*');
    }} else {{
      setStatus('🎙', 'Nothing captured. Try again.');
    }}
  }};

  rec.start();
  state.micActive = true;
}}

function stopMic() {{
  if (state.recognition) {{
    state.recognition.stop();
    state.recognition = null;
  }}
  micOn = false;
  state.micActive = false;
  resetMicUI();
}}

function toggleMic() {{
  if (micOn) stopMic();
  else startMic();
}}

function useTranscript() {{
  const t = finalTranscript.trim();
  if (!t) {{ setStatus('⚠️', 'No transcript yet. Speak first.'); return; }}

  // 1. Inject into textarea so the Streamlit Submit button can read it
  injectIntoTextarea(t);

  // 2. Post to bridge — bridge will click the submit button
  p.postMessage({{ type: 'ssb_auto_submit', transcript: t }}, '*');

  setStatus('✅', 'Answer submitted. Waiting for evaluation...');
  document.getElementById('btn-use-transcript').style.display = 'none';
}}

function resetMicUI() {{
  const btn = document.getElementById('btn-mic-toggle');
  btn.textContent = 'Start Speaking';
  btn.classList.remove('stop');
  document.getElementById('mic-icon').classList.remove('active');
}}

function setStatus(icon, text) {{
  document.getElementById('mic-icon').textContent   = icon;
  document.getElementById('status-text').textContent = text;
}}

// Auto-start TTS on load
window.addEventListener('load', () => {{
  setTimeout(speakAndListen, 300);
}});
</script>
</body>
</html>
"""


# ─── Save Button Component ────────────────────────────────────────────────────
_SAVE_BUTTON_HTML = """
<!DOCTYPE html>
<html>
<head>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: transparent; font-family: 'Segoe UI', sans-serif; padding: 4px; }

  #save-btn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 10px 22px;
    background: #1a3a5c;
    color: #fff;
    border: none;
    border-radius: 7px;
    font-size: 14px;
    font-weight: 700;
    cursor: pointer;
    transition: background 0.2s;
    width: 100%;
    justify-content: center;
  }
  #save-btn:hover   { background: #245080; }
  #save-btn:disabled { background: #888; cursor: not-allowed; }

  #save-status {
    margin-top: 8px;
    font-size: 12px;
    color: #666;
    text-align: center;
  }
</style>
</head>
<body>
<button id="save-btn" onclick="saveRecording()" disabled>
  ⏳ Preparing recording...
</button>
<div id="save-status">Recording will be available after the interview ends.</div>

<script>
const p = window.parent;

function saveRecording() {
  const state = p._ssbProctor;
  if (!state || !state.videoUrl) {
    document.getElementById('save-status').innerText = 'No recording available yet.';
    return;
  }

  // Stop recorder if still running
  if (state.recorder && state.recorder.state !== 'inactive') {
    state.recorder.stop();
  }

  // Give recorder time to finalise the blob
  setTimeout(() => {
    const url = p._ssbProctor.videoUrl;
    if (!url) {
      document.getElementById('save-status').innerText = 'Recording not ready. Please wait.';
      return;
    }
    const a = document.createElement('a');
    a.href     = url;
    a.download = 'SSB_Mock_Interview_' + new Date().toISOString().slice(0,19).replace(/:/g,'-') + '.webm';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    document.getElementById('save-status').innerText = 'Download started.';
  }, 800);
}

// Listen for recording-ready signal from camera component
window.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'ssb_recording_ready') {
    const btn = document.getElementById('save-btn');
    btn.disabled    = false;
    btn.textContent = '⬇ Save My SSB Interview (.webm)';
    document.getElementById('save-status').innerText =
      'Recording ready. Click to download.';
  }
});

// Also poll parent state in case message was missed
setInterval(() => {
  const state = p._ssbProctor;
  if (state && state.videoUrl) {
    const btn = document.getElementById('save-btn');
    if (btn.disabled) {
      btn.disabled    = false;
      btn.textContent = '⬇ Save My SSB Interview (.webm)';
    }
  }
}, 2000);
</script>
</body>
</html>
"""


# ─── RecordingManager ─────────────────────────────────────────────────────────
class RecordingManager:
    """
    Manages the browser-side camera preview, voice input, and recording
    download for the SSB Mock Interview proctoring system.

    All media handling is done entirely in the browser via:
      - getUserMedia  → live camera feed + MediaRecorder
      - SpeechRecognition → real-time STT transcript
      - speechSynthesis   → TTS question playback
      - Blob + URL.createObjectURL → downloadable .webm file

    No video data is transmitted to the Python server.
    """

    def render_camera_preview(self, height: int = 260) -> None:
        """
        Renders the live camera preview widget.
        Starts getUserMedia and MediaRecorder automatically.
        Should be placed in the left column of the split-screen layout.
        """
        components.html(_CAMERA_PREVIEW_HTML, height=height, scrolling=False)

    def render_voice_input(self, question_text: str, textarea_key: str = "mi_text_answer", height: int = 200) -> None:
        """
        Renders the voice input panel for a given question.
        Automatically speaks the question via TTS, then activates the mic.
        Shows real-time transcript.

        The transcript is injected directly into the Streamlit text_area
        identified by ``textarea_key`` so the Submit button reads the same
        value whether the user typed or spoke.

        Args:
            question_text: The question the IO is asking (will be spoken aloud).
            textarea_key:  Key of the st.text_area that holds the answer.
            height:        iframe height in pixels.
        """
        html = _build_voice_input_html(question_text, textarea_key)
        components.html(html, height=height, scrolling=False)

    def render_save_button(self, height: int = 90) -> None:
        """
        Renders the 'Save My SSB Interview' download button.
        Becomes active once the MediaRecorder has produced a Blob.
        Should be shown on the report/completion screen.
        """
        components.html(_SAVE_BUTTON_HTML, height=height, scrolling=False)

    def render_stop_recording_js(self) -> None:
        """
        Injects JS to stop the MediaRecorder and finalise the Blob.
        Call this when the interview ends (before showing the report screen).
        """
        components.html(
            """
            <script>
            (function() {
              const state = window.parent._ssbProctor;
              if (state && state.recorder && state.recorder.state !== 'inactive') {
                state.recorder.stop();
              }
              if (state && state.stream) {
                state.stream.getTracks().forEach(t => t.stop());
              }
            })();
            </script>
            """,
            height=0,
            scrolling=False,
        )
