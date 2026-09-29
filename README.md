# Ultron / Zora — Personal Jarvis Assistant (V1)

Created by **Debjeet (`dubessix`)** as his long-term local-first engineering, study, planning and personal AI partner.

Ultron is a **Jarvis-style assistant that runs on your own PC**. You talk or type; the AI brain decides by itself which tool to use — open apps, find folders, read/write files, run shell commands, Git, reminders, tasks, calendar, weather, research, music, memory — and answers you in a British Jarvis voice. **Zora** is Ultron's second, calmer personality who takes over automatically when you sound stressed.

> Status: **Personal V1 release candidate.** Automated tests pass (529 backend + 35 frontend). Final acceptance on the owner's Windows/browser/microphone/Spotify hardware and live AI keys is still required (owner-laptop acceptance).

---

## Contents

1. [What you need](#1-what-you-need)
2. [Install — one click](#2-install--one-click)
3. [Install — manual (from GitHub)](#3-install--manual-from-github)
4. [Add your API keys](#4-add-your-api-keys)
5. [Start and stop Ultron](#5-start-and-stop-ultron)
6. [Talking to Ultron (typing)](#6-talking-to-ultron-typing)
7. [Voice — listening (microphone)](#7-voice--listening-microphone)
8. [Voice — speaking (Jarvis voice)](#8-voice--speaking-jarvis-voice)
9. [Jarvis full access and the Approve button](#9-jarvis-full-access-and-the-approve-button)
10. [Ultron and Zora](#10-ultron-and-zora)
11. [Settings reference](#11-settings-reference)
12. [Update to the newest code](#12-update-to-the-newest-code)
13. [Run the tests](#13-run-the-tests)
14. [Troubleshooting](#14-troubleshooting)
15. [APIs for developers](#15-apis-for-developers)
16. [Known limits](#16-known-limits)

---

## 1. What you need

| Need | Why |
|---|---|
| **Windows 10/11 or Ubuntu** | Main supported systems |
| **Python 3.10+** | Runs the backend |
| **Git** | Updates and Git tools |
| **Google Chrome or Microsoft Edge** | **Required for voice listening** (see section 7) |
| Internet | AI brain (cloud) and the Jarvis voice (Edge TTS) |
| At least one **Groq** or **Gemini** key | Without a key Ultron replies `[Offline]` |
| Node.js 20.19+ | *Only* if you change frontend code or ports. Normal install uses the ready prebuilt frontend |
| 8 GB RAM | Recommended |

---

## 2. Install — one click

- **Windows:** double-click `SETUP_ULTRON_WINDOWS.bat`
- **Ubuntu:** run `SETUP_ULTRON_UBUNTU.sh`

The setup window installs everything, keeps your old keys and data, runs the Doctor check, and creates these shortcuts (desktop + Start Menu / Applications):

| Shortcut | What it does |
|---|---|
| **Ultron** | Starts Ultron and opens the browser |
| **Stop Ultron** | Clean shutdown |
| **Ultron Doctor** | Health check — shows what is broken |
| **Open Ultron .env** | Opens your private key file |
| **Ultron Keys** | Simple window to paste keys |

---

## 3. Install — manual (from GitHub)

```bash
git clone https://github.com/dubessix/Ultron-Personal-V1.git
cd Ultron-Personal-V1
python -m venv .venv
```

**Windows (PowerShell):**

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -c constraints.txt
python -m backend.app.cli setup
python -m backend.app.cli doctor
```

**Linux / macOS:**

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt -c constraints.txt
python -m backend.app.cli setup
python -m backend.app.cli doctor
```

`setup` never overwrites an existing `.env` or `config.yaml`.

---

## 4. Add your API keys

Copy `.env.example` to `.env` (setup does this for you) and paste real keys. **Never commit `.env` or paste keys in chat/issues.**

| Key | Get it at | Used for |
|---|---|---|
| `GROQ_API_KEY_1` … `_4` | https://console.groq.com | Main brain (fast, tool calling) |
| `GEMINI_API_KEY_1` … `_4` | https://aistudio.google.com | Backup brain + memory search |
| `NVIDIA_API_KEY_1` … `_4` | https://build.nvidia.com | Coding brain |
| `TAVILY_API_KEY` | https://tavily.com | Web research (optional) |
| `GITHUB_USERNAME_n` + `GITHUB_TOKEN_n` | GitHub → Settings → Developer settings → Tokens | GitHub tools (optional) |

- You can fill any slots — empty values and placeholders (like `your_groq_api_key_1_here`) are ignored. Slots may be non-contiguous: a real key only in `GROQ_API_KEY_3` and `GROQ_API_KEY_4` works fine.
- Several keys for one provider: Ultron stays on ONE key while it works (this keeps Groq's cache warm, so fewer tokens count). He moves to the next key only when Groq really says limit (429), the key is wrong, or that key's minute is full, and then stays on the new key. A busy server or network blip retries the same key. Gemini is used only when every Groq key is really out.
- **One Groq key is enough to start.**

Models (change in `config.yaml` or with an environment variable):

| Purpose | Default | Override |
|---|---|---|
| Groq chat | `openai/gpt-oss-120b` | `GROQ_CHAT_MODEL` |
| Gemini chat | `gemini-2.5-flash` | `GEMINI_CHAT_MODEL` |
| NVIDIA coding | `nvidia/nemotron-3-ultra-550b-a55b` | `NVIDIA_CHAT_MODEL` |
| Gemini embedding | `gemini-embedding-001` | `GEMINI_EMBEDDING_MODEL` |

> If Groq says the 120b model is not available on your free plan, set `GROQ_CHAT_MODEL=openai/gpt-oss-20b` in `.env`.

---

## 5. Start and stop Ultron

Click **Ultron** (or run `ultron start` / `python launcher.py`). A terminal window shows 5 startup checks, then the browser opens at:

- App: **http://127.0.0.1:5173** (or **http://localhost:5173**)
- Backend health: http://127.0.0.1:8000/api/health

Keep that terminal open while you use Ultron. To stop: click **Stop Ultron** or run `ultron stop`.

Once per day, on the first start, Ultron greets you with a short briefing (morning / afternoon / evening).

**Start at login (recommended):** run `ultron autostart on` once. Ultron then starts when you log in and restarts by himself if he crashes (at most 5 tries in 5 minutes, so he never loops). `ultron autostart off` removes it, and `ultron autostart status` shows it. On Ubuntu this is a user service (no sudo); on Windows it is an entry in your Startup folder.

**Health check:** `ultron doctor` lists everything in plain words: AI keys, models, Chrome helper, disk, database, backups, memory size and autostart, each with a one-line fix.

**Backups:** made by themselves once a day (at most 1 GB total; the newest 3 are always kept). If something breaks, `ultron backup --restore` puts back the newest good copy.

---

## 6. Talking to Ultron (typing)

Just type what you want, in normal words. The AI decides which tools to use — you don't need special commands.

```
open my Desktop and show what's there
find my resume folder
how much RAM is free?
create a task: finish project docs tomorrow 10 am
git status of the Ultron project
remind me in 20 minutes to drink water
what's the weather in Kolkata?
```

Ultron runs the tools, looks at the result, and then answers. Tool activity appears in the log panel.

---

## 7. Voice — listening (microphone)

Listening uses the **browser's own speech recognition** (Web Speech API). That keeps the PC light, but it has rules.

### 7.1 Rules (important)

| Rule | Why |
|---|---|
| Use **Google Chrome** or **Microsoft Edge** | Brave, Opera, Firefox and Electron-type app windows have **no working speech service** |
| Open the app at **`http://localhost:5173`** or **`http://127.0.0.1:5173`** | Browsers only allow the mic on `localhost` or `https`. `http://192.168.x.x:5173` from another device **will not work** |
| **Internet on** | Chrome/Edge send the audio to Google/Microsoft to turn it into text |
| **Allow the microphone** when the browser asks | If you clicked Block: click the 🔒 lock icon in the address bar → Microphone → Allow → reload |
| Correct mic selected | Chrome: `chrome://settings/content/microphone` · Windows: Settings → System → Sound → Input |

### 7.2 How to use it

1. Click the **Mic** button in the top bar. It glows — Ultron is now listening for his name.
2. Say the wake word **and** your command in one breath:
   **"Hey Ultron, open the calendar."**
   Or say **"Ultron"**, wait a moment, then say the command within **6 seconds**.
3. Stop talking. After about **2 seconds of silence** the command is sent.
4. Ultron answers out loud. **The mic pauses while he speaks** (so he doesn't hear himself), then goes back to listening.
5. **Say the wake word before every command.** Speech without "Ultron" is ignored — so the TV or other people won't trigger him.
6. Click the Mic button again to stop listening.

**Wake words:** `hey ultron`, `ultron`, `wake up ultron`, `ultron wake up`, `wake up`.

Browsers often mishear "Ultron", so these are accepted too: *altron, ultran, all tron, ul tron, oltron, ok ultron, hi ultron* — and *ultra* / *alton* **when they are the first word** you say (so "an ultra wide monitor" does not wake him). "Electron" and "activate" never wake him.

The words the browser heard are shown under the mic, so you can see what it understood.

### 7.3 Change the listening language

The default is Indian English (`en-IN`), which works best with an Indian accent. To change it, put this in `frontend/.env` and rebuild the frontend (needs Node):

```
VITE_VOICE_LANG=en-GB
```

### 7.4 Listening problems — what the message means

| Message / symptom | Fix |
|---|---|
| *"Voice recognition is unavailable in this browser"* | Use Chrome or Edge |
| *"The microphone only works on https or localhost"* | Open `http://localhost:5173` on the same PC |
| *"This browser cannot reach its speech service"* | You're on Brave/Opera/offline — use Chrome/Edge with internet. In Brave, Google's speech service is blocked |
| *"Speech recognition is blocked here"* | Browser policy or insecure address — use Chrome/Edge at localhost and allow the mic |
| *"Microphone permission was denied"* | Lock icon → Microphone → Allow → reload |
| Mic glows but nothing happens | Say **"Hey Ultron"** clearly first; watch the heard text. Check the right input device and its level in Windows sound settings |
| Stuck on *"Ultron is speaking"* | Fixed: a watchdog now releases the mic automatically if the audio never finishes (within about 15–60 seconds) |
| Heard text is right but no reply | Check the backend terminal and **Ultron Doctor** — usually a missing AI key |

---

## 8. Voice — speaking (Jarvis voice)

Ultron speaks with **Microsoft Edge neural voices** (free, needs internet), via `POST /api/speak`.

| Personality | Voice | Style |
|---|---|---|
| Ultron | `en-GB-RyanNeural` rate -4 %, pitch -2 Hz | Calm British butler, like Jarvis |
| Zora | `en-IN-NeerjaExpressiveNeural` rate -2 %, pitch +1 Hz | Warm and gentle |

Change these in `config.yaml` → `voice`.

**He never reads symbols out.** Before speaking, the text is cleaned:

| On screen | Spoken |
|---|---|
| `CPU 12%` | "12 percent" |
| `6.5 GB / 16 GB` | "6.5 gigabytes of 16 gigabytes" |
| `C:\Users\Deb\Projects` | "the Projects folder" |
| `resume_2026.pdf` | "resume 2026 PDF" |
| `https://python.org` | "Python dot org" |
| code blocks | "I've put the code on your screen." |
| JSON / big tables | "The full details are on screen." |
| `&`, `°C`, `>` | "and", "degrees", "is above" |

---

## 9. Jarvis full access and the Approve button

By default Ultron can work **in any folder** (Desktop, Documents, D: drive…) and run **any shell command**, and it can **find folders by name** ("open my resume folder").

Safety stays on:

- **Always blocked:** Windows/system folders, secret files (`.env`, SSH keys, password stores), disk-wiping commands.
- **Needs one click on Approve:** delete, move/rename, overwrite, and shell commands that change things. The Approve button appears in the top bar with the exact action — nothing runs until you click it.
- Sending your file contents to a cloud AI also asks first.

To go back to strict mode, in `config.yaml`:

```yaml
security:
  access_mode: allowlist        # only folders in allowed_directories
  terminal_policy: allowlist    # only listed commands
```

Or temporarily with environment variables: `ULTRON_ACCESS_MODE=allowlist`, `ULTRON_TERMINAL_POLICY=allowlist`.

---

## 10. Ultron and Zora

- **Ultron** — main personality: sharp, efficient, a British butler.
- **Zora** — second personality: calm and caring. Ultron hands over to Zora **automatically** when your messages show stress (the stress score passes the threshold in `config.yaml`), and you'll hear her voice.

---

## 11. Settings reference

| File | What's in it |
|---|---|
| `.env` | Your private API keys (never share) |
| `config.yaml` | Models, voice, ports, security, wake words, backups |
| `frontend/.env` | Optional: `VITE_API_URL`, `VITE_VOICE_LANG` |
| `data/` | Your database, memory, logs, backups (stays on your PC) |

Useful environment variables: `GROQ_CHAT_MODEL`, `GEMINI_CHAT_MODEL`, `NVIDIA_CHAT_MODEL`, `ULTRON_ACCESS_MODE`, `ULTRON_TERMINAL_POLICY`, `ULTRON_HOME`.

---

## 12. Update to the newest code

```bash
cd Ultron-Personal-V1
git pull
python -m pip install -r requirements.txt -c constraints.txt
```

Then start Ultron again. The prebuilt frontend in `frontend/prebuilt/` is updated with each change, so Node is not needed. If you change frontend code yourself, the launcher rebuilds it (needs Node 20.19+).

---

## 13. Run the tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q --deselect tests/test_world_monitor_queries.py
cd frontend && npm ci && npx vitest run && npm run build
```

Expected: **529 passed** (backend) and **35 passed** (frontend). `test_world_monitor_queries` calls a live internet API and is skipped for that reason.

The tests use a fake AI brain and a fake microphone. They check the logic, not your real keys, mic or speakers.

---

## 14. Troubleshooting

| Problem | Fix |
|---|---|
| Replies start with `[Offline]` | No working AI key — add one in `.env`, run **Ultron Doctor** |
| Ultron chats but never uses tools | Use a tool-capable model (defaults are). Check the log panel for tool calls |
| Voice listening does nothing | See [section 7.4](#74-listening-problems--what-the-message-means) |
| No sound | Internet needed for Edge TTS; check speakers; click once on the page (browsers block autoplay until you interact) |
| "Port already in use" | Another Ultron is running — use **Stop Ultron**, or change `server` ports in `config.yaml` |
| Action waits forever | Look for the **Approve** button in the top bar |
| Anything else | Run **Ultron Doctor**, and read `data/logs/launcher-ui.log` |

---

## 15. APIs for developers

REST: `POST /api/chat` · `POST /api/tools/execute` · `POST /api/actions/confirm` · `GET /api/history` · `GET /api/session-summary/{id}` · `POST /api/speak` · `GET /api/memory/recent` · `POST /api/db/backup` · `GET /api/db/integrity` · `POST /api/db/restore` · `GET /api/providers/status` · `POST /api/personality` · `POST /api/coding-mode` · `GET /api/health`

WebSocket: `/ws/chat` · `/ws/events` · `/ws/logs` · `/ws/dashboard`

How it works: the brain gets native tool schemas and runs an inspect → act → observe loop (up to 8 steps). Keyword rules are only hints; the model makes the decision. Risky actions pause for an Approve token tied to the exact action. Memory lives in SQLite (full-text search + vectors). More detail: `SETUP_GUIDE.md`, `docs/api_reference.md`, `docs/testing_strategy.md`.

---

## 16. Known limits

These can only be confirmed on your own PC, not in automated tests:

- Live Groq / Gemini / NVIDIA / Tavily / GitHub calls
- Real microphone and browser speech accuracy
- Edge-TTS playback through your speakers
- Windows process control and Spotify desktop control
