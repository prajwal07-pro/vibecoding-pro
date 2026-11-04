# 🤖 AI Multi-File Editor

A powerful, **self-hosted, browser-based AI coding assistant** that lets you analyse a project, generate an optimised source bundle, edit multiple files at once via a compact patch protocol, dictate tasks with your voice, and safely apply/rollback every change with full backup history.

Runs entirely on your machine (`http://127.0.0.1:8009`) — no cloud accounts required beyond a Groq API key. Your code never leaves your computer unless *you* send it to the AI for analysis.

---

## 📑 Table of Contents

- [What Is This?](#-what-is-this)
- [Features](#-features)
  - [1. Source Generator](#1-source-generator)
  - [2. AI File Editor](#2-ai-file-editor)
  - [3. Voice Prompt](#3-voice-prompt)
  - [4. Fixed Format](#4-fixed-format)
  - [Cross-cutting Features](#cross-cutting-features)
- [How It Works](#-how-it-works)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Usage Guide](#-usage-guide)
  - [Step 0 — Add Groq API Keys](#step-0--add-groq-api-keys)
  - [Step 1 — Source Generator](#step-1--source-generator)
  - [Step 2 — AI File Editor](#step-2--ai-file-editor)
  - [Step 3 — Voice Prompt](#step-3--voice-prompt)
  - [Step 4 — Fixed Format](#step-4--fixed-format)
- [The Patch Protocol](#-the-patch-protocol)
- [Project Structure](#-project-structure)
- [API Reference](#-api-reference)
- [Backups & History](#-backups--history)
- [Security Notes](#-security-notes)
- [Troubleshooting](#-troubleshooting)
- [FAQ](#-faq)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🚀 What Is This?

**AI Multi-File Editor** is a local web app that turns an AI chat model (Groq's `openai/gpt-oss-120b` by default) into a **surgical multi-file code editor** for your existing project.

The workflow is:

1. **Point it at a folder** on your machine.
2. **Scan & bundle** the project into a single token-efficient `project_source.txt`.
3. **Describe a task** (typed or dictated).
4. **Let the AI decide** which files need to change.
5. **Paste the AI's response** back into the editor.
6. **Preview exact diffs**, apply only the valid files, and **restore** any change from history — with automatic `.backup` snapshots.

Every change is:
- **Diffed** before it touches your disk.
- **Verified** against the current on-disk content (no stale patches).
- **Backed up** in `.backup/<timestamp>/` so you can restore it.
- **Logged** in a browsable history panel.

---

## ✨ Features

### 1. Source Generator

Bundle your whole project (or an AI-selected subset) into one text file for AI ingestion.

- **Flexible scanning rules** — include / exclude by:
  - folders (relative path)
  - specific files (relative path)
  - extensions (`.py`, `.ts`, …)
  - filenames (`Dockerfile`, `Makefile`, …)
- **Precedence is deterministic:** excluded folder → excluded file/filename → excluded extension → explicit include → included extension. *Included folders* act as a whitelist when non-empty, and folder exclusions always win.
- **Binary file detection** — skips any file that looks binary (contains null bytes in the first 8 KB).
- **Native folder / file pickers** — integrates with the system's file dialog via:
  - `xdg-desktop-portal` (Wayland/GTK, preferred on modern Linux desktops)
  - `zenity` (GNOME / GTK fallback)
  - `kdialog` (KDE)
  - `tkinter` (final fallback)
  - Manual path entry always works.
- **AI-powered affected-file analysis** — send a prompt + a compressed manifest of your project to Groq; the model returns the exact list of files that must be modified. You review, tick/untick, add custom paths, then generate.
- **Live preview lists** — see every included file (with size & extension), every excluded folder (with file count), and every excluded file (with the reason for exclusion).
- **Filterable lists** — search filters on all three panels.
- **`project_source.txt`** output — one canonical artefact ready to feed to any LLM.

### 2. AI File Editor

The core apply engine — surgically apply AI-proposed changes.

- **Four parse modes:**
  - **PATCH** — precise `@@OP` operations against the current file (default and preferred).
  - **FULL** — complete file rewrite.
  - **DELETE_FILE** — remove an existing file.
  - **LEGACY** — plain complete-content blocks (backwards compatible).
- **Dry-run preview** — every file is verified before anything is written:
  - **New** (file will be created)
  - **Modified** (diff will be applied)
  - **Deleted** (file will be removed)
  - **Unchanged** (no-op — never touched)
  - **Failed Validation** (explicitly skipped and reported)
- **In-browser diff viewer** — click **VIEW DIFF** on any file to see per-operation hunks, old vs new content, line ranges, insert positions.
- **Atomic multi-file apply** — all files in one transaction, backed up first.
- **Pre-apply conflict detection** — if a file changed on disk since the preview was generated, you get a `409 CONFLICT` and nothing is written.
- **Failed-file retry workflow** — after an apply, if some files failed, only *those* blocks remain in the input box for the next AI turn, alongside the error report.
- **Full history & restore** — every apply is logged with old/new content in `.backup/<timestamp>/`. Browse, examine, and restore any historical operation (with force-override when files have diverged).

### 3. Voice Prompt

Talk your tasks in — get accurate text out.

- **Two-stage speech pipeline:**
  1. **Live browser SpeechRecognition** — instant on-screen preview while you speak.
  2. **Groq Whisper** (`whisper-large-v3`) — accurate final transcription from the recorded audio.
- **Audio recording is always saved**, even if transcription fails. Play it back or download it from the built-in audio player.
- **Prompt history** — every `COPY WITH FORMAT` action snapshots the prompt *and* associates any pending voice recording, all playable/loadable later.
- **Copy variants:**
  - **COPY TASK ONLY** — just your task text.
  - **COPY WITH FORMAT** — task + fixed response-format instructions, also saved to history.
  - **USE FOR SOURCE GEN** — push the prompt straight into Tab 1.
- **Search history** by text.

### 4. Fixed Format

The "contract" the AI must obey when producing output.

- **Compressed, token-efficient** response-format specification (Patch Protocol + validation rules).
- **Fully editable** — save custom variants to disk.
- **Reset to default** at any time.
- **Copy standalone** for use in any chat interface.

### Cross-cutting Features

- **Multi-key Groq fallback chain** — enter *multiple* API keys in the UI. Requests try Key #1 → if it fails (rate-limit, quota, auth, network), it automatically falls back to Key #2, #3, … Each success reports which key was used.
- **Browser LocalStorage** persists your Groq keys so you don't re-enter them.
- **Zero-install frontend** — one HTML file, no build step.
- **Cross-tab workflow** — Section 3 → Section 1 via `USE FOR SOURCE GEN`, Section 3 → clipboard with fixed format, etc.
- **Full backup history** — every apply/restore is a restorable checkpoint.
- **Robust error surfacing** — server errors, validation errors, HTTP failures and conflicts all bubble up to the UI with actionable messages.

---

## 🧠 How It Works
