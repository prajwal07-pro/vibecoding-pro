# ■ AI Multi-File Editor

A local-first, privacy-focused, and token-efficient **AI Codebase Context Bundler, Voice Prompt Studio, and Multi-File Patch Editor** built with **FastAPI** and a zero-dependency **Vanilla JS** frontend.

Designed for developers who work with large language models (ChatGPT, Claude, DeepSeek, Gemini, Grok, etc.) via web interfaces or APIs, **AI Multi-File Editor** eliminates copy-pasting individual files back and forth. It scans your local project, uses AI to automatically pick only the relevant files for your task, lets you dictate complex prompts using a hybrid **Browser Speech + Groq Whisper** pipeline, enforces a **Verified Compact Patch Protocol**, previews exact line-by-line diffs, and applies multi-file changes atomically with **instant 1-click rollbacks**.

---

## Table of Contents

1. [Why Use AI Multi-File Editor?](#-why-use-ai-multi-file-editor)
2. [Key Features](#-key-features)
3. [How It Works (End-to-End Workflow)](#-how-it-works-end-to-end-workflow)
4. [Prerequisites](#-prerequisites)
5. [Installation & Cloning Guide](#-installation--cloning-guide)
6. [Configuration & Environment Variables](#-configuration--environment-variables)
7. [Detailed Guide to the 4 Sections](#-detailed-guide-to-the-4-sections)
   - [1. Source Generator & AI File Analyzer](#1-source-generator--ai-file-analyzer)
   - [2. AI File Editor & Diff Engine](#2-ai-file-editor--diff-engine)
   - [3. Voice Prompt Studio & Audio Archive](#3-voice-prompt-studio--audio-archive)
   - [4. Fixed Format Instructions](#4-fixed-format-instructions)
8. [The Verified Compact Patch Protocol](#-the-verified-compact-patch-protocol)
9. [Safety, Backups, Conflict Detection & Rollbacks](#-safety-backups-conflict-detection--rollbacks)
10. [Directory Structure & Storage](#-directory-structure--storage)
11. [REST API Reference](#-rest-api-reference)
12. [Troubleshooting](#-troubleshooting)
13. [License](#-license)

---

## Why Use AI Multi-File Editor?

When using web-based LLMs on real-world repositories, developers face three major bottlenecks:
1. **Context Bloat:** Uploading entire repositories wastes context window tokens and degrades LLM reasoning.
2. **Slow Prompting:** Typing out detailed architectural requirements takes time, and standard voice dictation tools lose recordings when network errors occur.
3. **Tedious & Risky File Updates:** Asking an LLM to rewrite 800-line files wastes output tokens, hits output limits, and risks accidentally deleting unrelated functions. Manually copying 10 code blocks into your IDE is slow and error-prone.

**AI Multi-File Editor** solves all three problems in one unified local web application (`http://127.0.0.1:8009`).

---

## Key Features

### 1. Smart Source Bundler (`project_source.txt`)
* **Granular Filtering Rules:** Configure Included/Excluded Folders, Files, Extensions, and Filenames with deterministic precedence rules.
* **Binary & Lockfile Protection:** Automatically detects and skips binary files (NUL-byte probing) and lockfiles (`package-lock.json`, `yarn.lock`, etc.).
* **AI-Powered Affected File Analyzer:** Uses `openai/gpt-oss-120b` (or any Groq/OpenAI-compatible model) to inspect your project manifest and select **only** the files that need modification for your specific task.

### 2. Verified Compact Patch Engine
* **4 Operation Modes:** Supports `PATCH` (surgical line-level edits), `FULL` (new files or complete rewrites), `DELETE_FILE` (remove files), and `LEGACY` (backward-compatible raw file replacement).
* **6 Surgical Patch Operations:** `REPLACE`, `DELETE`, `INSERT_BEFORE`, `INSERT_AFTER`, `INSERT_AT_START`, and `INSERT_AT_END`.
* **Zero Line-Number Drift:** Line numbers (`@@LINES`) act only as disambiguation hints; the resolver verifies exact source text (`@@MATCH` / `@@ANCHOR`) against the original snapshot and applies edits bottom-up so independent operations never shift each other's line numbers.
* **Newline & Encoding Preservation:** Automatically detects and preserves `CRLF` (`\r\n`) vs `LF` (`\n`) per file.
* **Partial-Failure Resilience:** If 9 out of 10 files pass validation and 1 fails, you can apply the 9 valid files immediately while keeping **only the failed file block** in the input box for a quick retry.

### 3. Hybrid Voice Prompt Studio (Never Lose a Recording)
* **Dual-Stage Transcription:** Uses the browser's native `SpeechRecognition` API for instant live text preview while you speak, then automatically sends the recorded audio to **Groq Whisper (`whisper-large-v3`)** for high-accuracy transcription when you stop.
* **Automatic Audio Persistence:** Every voice recording is immediately saved to disk (`.editor_data/recordings/` and `<project_root>/.backup/recordings/`) **before** transcription even starts. If your internet drops or API keys fail, you can still play back or download the `.webm`/`.ogg`/`.m4a` recording from the UI.
* **Searchable Prompt & Audio History:** Every copied prompt is archived with its rank, timestamp, character count, raw task text, combined prompt, and an embedded HTML5 audio player.

### 4. Multi-Key Groq API Fallback Chain
* **Zero Downtime on Rate Limits:** Add multiple Groq API keys (`gsk_...`) directly in the browser UI (stored in `localStorage`) or via environment variables.
* **Automatic Failover:** If Key #1 hits a rate limit (`429`), quota error, or network timeout during file analysis or Whisper transcription, the backend automatically retries with Key #2, Key #3, and so on.

### 5. Native OS Folder & File Pickers
* Click **BROWSE…** in the browser to open a native OS file/folder dialog on your machine.
* Automatically falls back through:
  1. `xdg-desktop-portal` (Linux D-Bus native portal)
  2. `zenity` (GNOME/GTK)
  3. `kdialog` (KDE)
  4. `tkinter` (Cross-platform Python built-in for Windows, macOS, and Linux)

---

## How It Works (End-to-End Workflow)

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. VOICE PROMPT (Tab 3)                                                     │
│ Dictate or type your task -> Whisper transcribes -> Copy with Fixed Format  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. GENERATE CONTEXT (Tab 1)                                                 │
│ Scan Project -> AI Analyzer picks affected files -> Outputs project_source  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. PROMPT YOUR LLM (ChatGPT / Claude / DeepSeek / Gemini)                   │
│ Attach `project_source.txt` + Paste Combined Prompt -> Copy LLM's response  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. PREVIEW & APPLY (Tab 2)                                                  │
│ Paste LLM output -> Parse -> Check Working (Diff Preview) -> Confirm Apply  │
│ (Automatic snapshot saved to `<project>/.backup/` for 1-click Restore)      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

* **Python:** `3.9` or higher (`3.10+` recommended)
* **Modern Web Browser:** Chrome, Brave, Edge, or Firefox (Chromium-based browsers recommended for live `webkitSpeechRecognition` preview; Whisper recording works in all modern browsers).
* **Groq API Key (Optional but Recommended):** Free or paid API key from [console.groq.com](https://console.groq.com) for Whisper voice transcription and AI affected-file analysis.
* *(Optional for Linux Native File Dialogs)*: `zenity`, `kdialog`, or `python3-tk` / `python3-dbus`.

---

## Installation & Cloning Guide

Follow these steps to clone and run the project on **Linux, macOS, or Windows**.

### Step 1: Clone the Repository
```bash
git clone https://github.com/<your-username>/<your-repo-name>.git
cd <your-repo-name>
```

### Step 2: Create and Activate a Virtual Environment
Using a virtual environment keeps dependencies isolated.

**On Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**On Windows (Command Prompt):**
```cmd
python -m venv .venv
.venv\Scripts\activate
```

**On Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Step 3: Install Python Dependencies
```bash
pip install -r requirements.txt
```
*(Dependencies installed: `fastapi`, `uvicorn[standard]`, `httpx`, `pydantic`, `python-multipart`)*

### Step 4: Configure Default Project Path (Optional)
At the very top of `main.py` (Line 1), there is a fallback constant:
```python
PROJECT_ROOT = "/path/to/your/default/project"
```
You can either update this line to your preferred default project path **or** leave it as-is and change your project folder anytime directly from the Web UI (**BROWSE…** / **SET ROOT**), which persists your selection in `.editor_data/editor_config.json`.

### Step 5: Run the Server
```bash
python main.py
```
The server starts on **`http://127.0.0.1:8009`** and automatically opens a tab in your default web browser after 1.2 seconds.

---

## Configuration & Environment Variables

You can configure API keys directly in the **GROQ API KEYS** panel at the top of the web UI, or via environment variables before launching `main.py`.

| Environment Variable | Default Value | Description |
| :--- | :--- | :--- |
| `AI_API_BASE` | `https://api.groq.com/openai/v1` | OpenAI-compatible API base URL (Groq, OpenAI, xAI, OpenRouter, or local Ollama/vLLM). |
| `AI_API_KEY` | `""` | Single key or comma-separated list of API keys (fallback if no keys are in browser `localStorage`). Also checks `GROK_API_KEY` and `XAI_API_KEY`. |
| `AI_MODEL` | `openai/gpt-oss-120b` | Chat completion model used by the Section 1 AI Affected-Files Analyzer. |
| `AI_WHISPER_MODEL` | `whisper-large-v3` | Audio transcription model used by the voice recorder. |
| `AI_TIMEOUT` | `120` | HTTP timeout in seconds for AI analysis and transcription requests. |
| `AI_EDITOR_NO_BROWSER` | `0` | Set to `1` (`AI_EDITOR_NO_BROWSER=1 python main.py`) to prevent auto-opening the browser on startup. |

### Example: Running with Custom Environment Variables
```bash
export AI_API_KEY="gsk_key1...,gsk_key2..."
export AI_MODEL="llama-3.3-70b-versatile"
python main.py
```

---

## Detailed Guide to the 4 Sections

### Top Bar: Groq API Keys (Automatic Fallback Chain)
Click **GROQ API KEYS** in the top-right corner of the app to open the key manager:
* Paste one or more `gsk_...` keys (comma-separated or newline-separated) and click **ADD KEY(S)**.
* Keys are stored locally in your browser's `localStorage` (`ai_editor_groq_api_keys_v1`).
* Every AI request tries Key `#1` first and automatically falls back to `#2`, `#3`, etc., if rate-limited or exhausted.

---

### 1. Source Generator & AI File Analyzer
Generates a clean, single-file representation of your codebase (`project_source.txt` in the tool's root directory) to upload to any LLM.

1. **Project Folder:**
   * Enter the absolute path to your project or click **BROWSE…** to pick a folder natively.
   * Click **SCAN** to inspect which files are included, which folders are skipped, and why specific files were excluded.
   * Click **GENERATE ALL** to bundle all included files into `project_source.txt`.
2. **AI-Powered Source Generator:**
   * Instead of bundling your entire repo, describe your task (by voice 🎤, typing, or clicking **FROM SEC 3** to import your prompt from Tab 3).
   * Click **ANALYZE AFFECTED FILES**. The backend builds a lightweight manifest (file paths, sizes, and first 30 lines of each file) and queries the LLM (`openai/gpt-oss-120b`) to determine which files need changes.
   * Review the returned checklist of affected files, check/uncheck items, add custom paths via autocomplete if needed, and click **APPROVE & GENERATE SELECTED** to write a minimal `project_source.txt`.
3. **Filtering Rules & Precedence:**
   * Rules are evaluated in strict order:
     `Excluded Folder` > `Excluded File / Filename` > `Excluded Extension` > `Explicit Included File / Filename` > `Included Extension`.
   * **Included Folders** acts as a whitelist when non-empty (only those folders are traversed).
   * Click **SAVE CONFIG** to persist rules to `.editor_data/gen_config.json` or **RESET DEFAULTS** to restore the built-in presets.

---

### 2. AI File Editor & Diff Engine
Parses LLM responses, validates patches against your real files on disk, previews diffs, applies changes, and manages version history.

1. **Project Root:**
   * Set the target repository root where edits should be applied and click **SET ROOT**.
2. **Paste AI Response:**
   * Paste the raw response from your LLM containing `<<<FILE: ...>>>` blocks into the text area.
   * Click **PARSE FILES**. The frontend parser validates block delimiters and categorizes each file by mode (`PATCH`, `FULL`, `DELETE`, or `LEGACY`).
3. **Check Working & Change Preview:**
   * Click **CHECK WORKING** to dry-run all operations against the live filesystem without modifying any files on disk.
   * Files are grouped into **Failed Validation**, **New Files (`+`)**, **Modified Files (`✎`)**, **Deleted Files (`✗`)**, and **Unchanged Files (`=`)**.
   * Click **VIEW DIFF** on any file to inspect the exact **Old** vs **New / Inserted** lines and line ranges.
4. **Confirm & Apply (with Partial Retry Support):**
   * Click **CONFIRM & APPLY VALID FILES**.
   * If any file failed validation (e.g., an ambiguous `@@MATCH` block), valid files are applied while failed files are **never touched**. The editor automatically keeps only the failed file blocks in the input box (or you can click **KEEP ONLY FAILED IN INPUT**) so you can re-prompt or fix just those files.
5. **History & 1-Click Restore:**
   * Every apply or restore action creates a timestamped snapshot in `<project_root>/.backup/<timestamp>/`.
   * Click **EXAMINE** to inspect the exact before/after state of every file in that operation, or click **RESTORE** to revert your files back to their pre-operation state.

---

### 3. Voice Prompt Studio & Audio Archive
Compose tasks rapidly using voice dictation and combine them with the Compact Patch Protocol instructions.

1. **Voice Input (`🎤`):**
   * Click the microphone button to start recording.
   * While you speak, your browser's speech engine shows a real-time draft in the text box.
   * When you click stop (`■`), the raw audio is saved to disk immediately and sent to **Groq Whisper (`whisper-large-v3`)**, which replaces the draft with a clean, punctuated transcript.
2. **Built-in Audio Player & Fail-Safe Download:**
   * An audio bar appears right below the prompt box so you can replay or download your voice recording at any time—even if Whisper fails due to no internet or invalid API keys.
3. **Action Buttons:**
   * **USE FOR SOURCE GEN:** Sends your task prompt (without the fixed format instructions) directly to Tab 1's AI Analyzer.
   * **COPY TASK ONLY:** Copies only your custom task description to the clipboard.
   * **COPY WITH FORMAT:** Appends the Section 4 Fixed Format Instructions to your task, copies the combined prompt to your clipboard, and saves a permanent snapshot (plus linked audio recording) to **Prompt History**.
4. **Prompt History:**
   * Filter past prompts by keyword, listen to their original voice recordings, **VIEW** full text, **COPY** again, **LOAD** back into the editor, or **DEL**ete entries.

---

### 4. Fixed Format Instructions
Manages the system instructions appended to your prompts when you click **COPY WITH FORMAT**.

* Pre-loaded with a token-optimized specification of the **Verified Compact Patch Protocol**.
* Edit the instructions and click **SAVE** (stored in `.editor_data/fixed_prompt.txt`), **COPY FIXED PROMPT** for standalone use, or **RESET TO DEFAULT** to restore the built-in template.

---

## The Verified Compact Patch Protocol

When an LLM responds using the Fixed Format Instructions, it wraps affected files in `<<<FILE: path>>> ... <<<END FILE>>>` blocks using one of 4 modes:

### Mode 1: `@@PATCH` (Preferred for Existing Files)
```text
<<<FILE: src/utils/math.py>>>
@@PATCH

@@OP: REPLACE
@@LINES: 12-15
@@MATCH
def add(a, b):
    return a + b
@@END MATCH
@@WITH
def add(a: int, b: int) -> int:
    return a + b
@@END WITH
@@END OP

@@OP: INSERT_AFTER
@@LINES: 20
@@ANCHOR
import os
@@END ANCHOR
@@WITH
import sys
@@END WITH
@@END OP

@@OP: DELETE
@@MATCH
# deprecated helper
@@END MATCH
@@END OP

@@END PATCH
<<<END FILE>>>
```
* **Supported `@@OP:` Types:**
  * `REPLACE` (requires `@@MATCH` and `@@WITH`; optional `@@LINES`)
  * `DELETE` (requires `@@MATCH`; optional `@@LINES`)
  * `INSERT_BEFORE` (requires `@@ANCHOR` and `@@WITH`; optional `@@LINES`)
  * `INSERT_AFTER` (requires `@@ANCHOR` and `@@WITH`; optional `@@LINES`)
  * `INSERT_AT_START` (requires `@@WITH`)
  * `INSERT_AT_END` (requires `@@WITH`)
* **Escaping Rule:** Any content line inside `@@MATCH`, `@@ANCHOR`, or `@@WITH` that literally begins with `@@` (or one or more backslashes followed by `@@`) is escaped with a single leading backslash (e.g., `\@@END MATCH`).

### Mode 2: `@@FULL` (For New Files or Complete Rewrites)
```text
<<<FILE: src/new_module.py>>>
@@FULL
def greet(name: str) -> str:
    return f"Hello, {name}!"
@@END FULL
<<<END FILE>>>
```

### Mode 3: `@@DELETE_FILE` (Delete an Existing File)
```text
<<<FILE: src/obsolete.py>>>
@@DELETE_FILE
<<<END FILE>>>
```

### Mode 4: Legacy Raw Mode
```text
<<<FILE: src/config.json>>>
{
  "debug": true
}
<<<END FILE>>>
```

---

## Safety, Backups, Conflict Detection & Rollbacks

1. **Path Traversal Protection:**
   * All file paths are strictly validated via `resolve_rel()`. Absolute paths, null bytes, paths escaping the project root (`../`), and paths targeting `.backup/` are rejected with HTTP `400`.
2. **SHA-256 Optimistic Concurrency Control:**
   * During **CHECK WORKING**, the server computes the `SHA-256` hash of each target file on disk.
   * When you click **CONFIRM & APPLY**, if any file was modified externally (e.g., in VS Code or via `git`) after the preview was generated, the server aborts with HTTP `409 CONFLICT` to prevent overwriting unsaved external work.
3. **Post-Write Verification:**
   * After writing or deleting files, `perform_operation()` re-reads every modified file from disk to verify its contents match the expected output byte-for-byte.
4. **Per-Project `.backup` Snapshots & Safe Restore:**
   * Every operation stores `old/` and `new/` file copies plus a `manifest.json` inside `<project_root>/.backup/<YYYY-MM-DD_HH-MM-SS>/`.
   * Clicking **RESTORE** checks if files were edited since the operation was applied. If edits are detected, it warns you with a list of conflicting files and asks for confirmation before forcing a rollback.

---

## Directory Structure & Storage

```text
.
├── main.py                      # FastAPI backend server, patch resolver, AI & OS picker logic
├── index.html                   # Single-page UI (HTML5 + CSS + Vanilla JS)
├── requirements.txt             # Python package dependencies
├── project_source.txt           # Generated codebase bundle (created when you click Generate)
└── .editor_data/                # Auto-created local state directory
    ├── editor_config.json       # Active project root for Section 2 (AI File Editor)
    ├── gen_config.json          # Active project root & filter rules for Section 1
    ├── prompt_history.json      # Saved prompt snapshots & metadata for Section 3
    ├── fixed_prompt.txt         # Custom saved Fixed Format prompt for Section 4
    └── recordings/              # Saved voice prompt audio files (.webm / .ogg / .m4a)
```
Additionally, inside whatever target **Project Root** you are editing, the tool maintains:
```text
<your-target-project-root>/
└── .backup/
    ├── history.json             # Project-specific edit & restore history log
    ├── recordings/              # Mirror backup of voice recordings
    └── 2025-05-10_14-30-00/     # Timestamped snapshot per apply/restore operation
        ├── manifest.json
        ├── old/                 # Original files before the operation
        └── new/                 # Updated files after the operation
```
*(Note: Both `.backup` and `.editor_data` are included in the default `excluded_folders` list so they are never bundled into `project_source.txt`.)*

---

## REST API Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Serves the main `index.html` single-page application. |
| `GET` | `/api/project` | Returns the current Section 2 Editor Root, existence status, and backup path. |
| `POST` | `/api/project` | Updates and persists the Section 2 Editor Root. |
| `POST` | `/api/check` | Dry-runs parsed files/patches against disk and returns diffs + `SHA-256` hashes. |
| `POST` | `/api/apply` | Verifies hashes, creates a `.backup` snapshot, and writes/deletes target files. |
| `GET` | `/api/history` | Lists all backup/apply history records for the active project root. |
| `GET` | `/api/history/{id}` | Returns full `old` and `new` file contents for a specific history snapshot. |
| `POST` | `/api/history/{id}/restore` | Reverts files to their state prior to `{id}` (supports `force: true/false`). |
| `GET` | `/api/gen/config` | Returns current Section 1 Source Generator rules and default presets. |
| `POST` | `/api/gen/config` | Saves Section 1 Source Generator filter rules. |
| `POST` | `/api/gen/scan` | Scans project tree and returns included files, excluded folders, and reasons. |
| `POST` | `/api/gen/generate` | Generates `project_source.txt` containing all included files. |
| `POST` | `/api/gen/generate-selected` | Generates `project_source.txt` containing only the approved subset of files. |
| `POST` | `/api/gen/folder-contents` | Lists up to 2,000 files inside an excluded folder for inspection. |
| `POST` | `/api/ai/analyze` | Queries `AI_MODEL` with project manifest + task prompt to select affected files. |
| `POST` | `/api/ai/transcribe` | Saves uploaded audio to disk and transcribes it via `AI_WHISPER_MODEL`. |
| `GET` | `/api/recordings/{filename}` | Streams or downloads a saved voice recording file. |
| `POST` | `/api/pick-folder` | Opens a native OS folder selection dialog on the host machine. |
| `POST` | `/api/pick-file` | Opens a native OS file selection dialog on the host machine. |
| `GET` | `/api/prompts` | Lists all saved prompt snapshots in reverse rank order. |
| `POST` | `/api/prompts` | Saves a new prompt snapshot (custom task, combined prompt, audio link). |
| `GET` | `/api/prompts/{id}` | Retrieves a specific prompt snapshot by UUID. |
| `DELETE` | `/api/prompts/{id}` | Deletes a prompt snapshot from history. |
| `GET` | `/api/fixed-prompt` | Gets the active Fixed Format prompt text. |
| `POST` | `/api/fixed-prompt` | Saves custom Fixed Format prompt text. |
| `POST` | `/api/fixed-prompt/reset` | Resets Fixed Format prompt to the built-in default. |

---

## Troubleshooting

### 1. "No native file picker available" when clicking BROWSE…
* **Cause:** Your Linux environment does not have an active D-Bus FileChooser portal, `zenity`, `kdialog`, or `tkinter` installed.
* **Fix:** Install `zenity` (`sudo apt install zenity`), `kdialog`, or `python3-tk` (`sudo apt install python3-tk`), or simply type/paste the folder path directly into the input box.

### 2. "No Groq API keys provided" during Voice Transcription or AI File Analysis
* **Cause:** Neither the browser `localStorage` nor the `AI_API_KEY` environment variable has a key set.
* **Fix:** Click **GROQ API KEYS** in the top-right bar of the web UI, paste your `gsk_...` key from [console.groq.com](https://console.groq.com), and click **ADD KEY(S)**.

### 3. Patch Fails with `match ambiguous (N occurrences); provide accurate @@LINES`
* **Cause:** The `@@MATCH` block occurs multiple times in the file and either no `@@LINES` hint was provided or the `@@LINES` hint did not overlap any of the occurrences.
* **Fix:** Click **KEEP ONLY FAILED IN INPUT** and either add an accurate `@@LINES: start-end` hint to the patch block or ask your LLM to regenerate that single file with more surrounding context lines in `@@MATCH`.

### 4. Microphone Permission Denied
* **Cause:** Browser blocked microphone access.
* **Fix:** Ensure you are accessing the site via `http://127.0.0.1:8009` or `http://localhost:8009` (browsers treat `127.0.0.1` and `localhost` as secure contexts for `navigator.mediaDevices.getUserMedia`) and allow microphone permissions in your browser's address bar.

---

## License

This project is open-source and available under the [MIT License](LICENSE).
