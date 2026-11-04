PROJECT_ROOT = "/home/prajwalrawoot/.popos/ideas/case taking multiuser"

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = Path(PROJECT_ROOT).expanduser().resolve()

DATA_DIR = BASE_DIR / ".editor_data"
RECORDINGS_DIR = DATA_DIR / "recordings"
EDITOR_CONFIG_FILE = DATA_DIR / "editor_config.json"
GEN_CONFIG_FILE = DATA_DIR / "gen_config.json"
PROMPT_HISTORY_FILE = DATA_DIR / "prompt_history.json"
FIXED_PROMPT_FILE = DATA_DIR / "fixed_prompt.txt"
GENERATED_OUTPUT = BASE_DIR / "project_source.txt"
_LOCK = threading.Lock()

RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

# --- AI provider (Grok / Groq-compatible) --------------------------------
AI_API_BASE = os.environ.get("AI_API_BASE", "https://api.groq.com/openai/v1").rstrip("/")
AI_API_KEY = os.environ.get("AI_API_KEY", "") or os.environ.get("GROK_API_KEY", "") or os.environ.get("XAI_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "openai/gpt-oss-120b")
AI_WHISPER_MODEL = os.environ.get("AI_WHISPER_MODEL", "whisper-large-v3")
AI_TIMEOUT = float(os.environ.get("AI_TIMEOUT", "120"))

# --- Fixed prompt ---------------------------------------------------------

OLD_DEFAULT_FIXED_PROMPT = """Complete the task described above. The following are response-format and implementation constraints, not a replacement for the task.

TOKEN EFFICIENCY
Use minimum reasonable tokens while preserving 100% of required functionality, behavior, correctness, security, compatibility, type safety and output throughput. Compress representation, never functionality. Do not sacrifice maintainability or correctness.

RESPONSE FORMAT — VERIFIED COMPACT PATCH PROTOCOL
Return only affected files. Wrap every file block inside one outer copyable text block. Put nothing outside that block. Do not explain changes.

Each file is one block:

<<<FILE: relative/path/to/file.ext>>>
[MODE CONTENT]
<<<END FILE>>>

Choose the smallest correct mode per file.

1. PATCH (preferred for small changes to existing files)

<<<FILE: path>>>
@@PATCH

@@OP: REPLACE
@@LINES: 120-124
@@MATCH
[exact current source lines, verbatim, including indentation]
@@END MATCH
@@WITH
[replacement lines]
@@END WITH
@@END OP

@@OP: INSERT_AFTER
@@LINES: 180
@@ANCHOR
[exact existing line(s) to insert after]
@@END ANCHOR
@@WITH
[new lines]
@@END WITH
@@END OP

@@OP: DELETE
@@MATCH
[exact current source lines to remove]
@@END MATCH
@@END OP

@@END PATCH
<<<END FILE>>>

Operation types: REPLACE, DELETE, INSERT_BEFORE, INSERT_AFTER, INSERT_AT_START, INSERT_AT_END.
Rules:
- @@MATCH must contain the exact original source lines, including indentation. If it occurs more than once, provide an accurate @@LINES hint to disambiguate; otherwise the patch will be rejected.
- @@ANCHOR is the exact existing line(s) for INSERT_BEFORE / INSERT_AFTER.
- Omit @@MATCH for INSERT_AT_START / INSERT_AT_END.
- @@LINES is an optional one-indexed location hint like 120-124 or 180. It is a navigation aid only. The editor verifies @@MATCH / @@ANCHOR against the real source and never edits based on line numbers alone.
- All line numbers refer to the original file snapshot. Independent operations in the same file resolve against that same original, not a partially modified version.
- Do not emit unchanged code or KEEP ranges. Unchanged source is preserved automatically.
- Preserve the original file's newline convention and trailing-newline state.
- Escape any line whose content starts with @@ (or with backslashes followed by @@) by prefixing one backslash, e.g. \\@@END MATCH inside a MATCH block.

2. FULL — entire-file content for a NEW file, or a genuine whole-file rewrite

<<<FILE: path>>>
@@FULL
[complete final content]
@@END FULL
<<<END FILE>>>

3. DELETE_FILE — remove an existing file entirely

<<<FILE: path>>>
@@DELETE_FILE
<<<END FILE>>>

4. LEGACY — complete final content (accepted for backward compatibility; prefer PATCH for existing files)

<<<FILE: path>>>
[complete final content]
<<<END FILE>>>

COMPLETENESS
Every emitted file block must be fully resolved by the operations it declares. Never include a patch you cannot construct exactly from the current source. If a required source file is unavailable, request it instead of guessing.

CONSTRAINTS
- Never mix PATCH, FULL, and DELETE_FILE modes for the same path in one response.
- Reject ambiguity instead of guessing. If @@MATCH is not unique and no valid @@LINES hint disambiguates it, use FULL.
- Preserve unrelated code, imports, types, public APIs, dependencies, comments and existing behavior.
- Keep output minimal: prefer PATCH over FULL whenever the change is localized.

PRIORITY
Correctness > source preservation > safety > minimal tokens."""

DEFAULT_FIXED_PROMPT = """Complete the task described above. The following are response-format constraints, not a replacement for the task.

EFFICIENCY
Minimum reasonable tokens while preserving 100% of functionality, behavior, correctness, security, compatibility, type safety, throughput. Compress representation, never functionality. Preserve maintainability.

FORMAT — COMPACT PATCH PROTOCOL
Return only affected files, all inside one outer copyable text block. Nothing outside it. No explanations.

Per file:

<<<FILE: relative/path/to/file.ext>>>
[MODE CONTENT]
<<<END FILE>>>

Choose the smallest correct mode.

1. PATCH (preferred for small edits to existing files)

<<<FILE: path>>>
@@PATCH

@@OP: REPLACE
@@LINES: 120-124
@@MATCH
[exact original source lines, verbatim, incl. indentation]
@@END MATCH
@@WITH
[replacement lines]
@@END WITH
@@END OP

@@OP: INSERT_AFTER
@@LINES: 180
@@ANCHOR
[exact existing line(s)]
@@END ANCHOR
@@WITH
[new lines]
@@END WITH
@@END OP

@@OP: DELETE
@@MATCH
[exact original source lines to remove]
@@END MATCH
@@END OP

@@END PATCH
<<<END FILE>>>

Ops: REPLACE, DELETE, INSERT_BEFORE, INSERT_AFTER, INSERT_AT_START, INSERT_AT_END.
- @@MATCH: exact original source incl. indentation. If it occurs more than once, provide accurate @@LINES or the patch is rejected.
- @@ANCHOR: exact existing line(s) for INSERT_BEFORE/AFTER.
- Omit @@MATCH for INSERT_AT_START/END.
- @@LINES: optional one-indexed hint (120-124 or 180). Navigation only; editor verifies against real source, never edits by number alone.
- Line numbers refer to the original snapshot; independent ops resolve against the same original, not a partially modified version.
- Do not emit unchanged code or KEEP ranges. Unchanged source is preserved automatically.
- Preserve original newline convention and trailing-newline state.
- Escape any line starting with @@ (or \\...@@) with one leading backslash, e.g. \\@@END MATCH.

2. FULL — new file, or genuine whole-file rewrite
<<<FILE: path>>>
@@FULL
[complete final content]
@@END FULL
<<<END FILE>>>

3. DELETE_FILE
<<<FILE: path>>>
@@DELETE_FILE
<<<END FILE>>>

4. LEGACY — complete content (accepted for backward compatibility; prefer PATCH)

COMPLETENESS
Every emitted block must fully resolve from current source. Never guess; request missing source instead.

CONSTRAINTS
- Never mix PATCH, FULL, DELETE_FILE for the same path in one response.
- Reject ambiguity instead of guessing. If @@MATCH is not unique and no valid @@LINES disambiguates, use FULL.
- Preserve unrelated code, imports, types, public APIs, dependencies, comments, behavior.
- Prefer PATCH over FULL when the change is localized.

PRIORITY
Correctness > source preservation > safety > minimal tokens."""

DEFAULT_GEN_CONFIG = {
    "root": "",
    "included_folders": [],
    "excluded_folders": [
        ".git", ".github", "node_modules", ".next", "dist", "build", "out",
        "coverage", "__pycache__", ".venv", "venv", "target", ".cache",
        ".idea", ".vscode", ".turbo", ".vercel", ".backup", "data",
        ".editor_data", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ],
    "included_files": [],
    "excluded_files": [
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
        "README.md", "LICENSE", ".DS_Store", "Thumbs.db",
    ],
    "included_extensions": [
        ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".cc",
        ".h", ".hpp", ".cs", ".php", ".html", ".htm", ".css", ".scss",
        ".sass", ".less", ".json", ".xml", ".yaml", ".yml", ".sql", ".go",
        ".rs", ".swift", ".kt", ".kts", ".dart", ".rb", ".lua", ".vue",
        ".svelte", ".toml", ".ini", ".cfg", ".conf", ".env", ".md", ".sh",
    ],
    "excluded_extensions": [
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".svg",
        ".mp3", ".mp4", ".wav", ".ogg", ".webm", ".mov", ".avi", ".pdf",
        ".zip", ".tar", ".gz", ".7z", ".rar", ".exe", ".dll", ".so", ".dylib",
        ".pyc", ".pyo", ".class", ".o", ".a", ".wasm", ".woff", ".woff2",
        ".ttf", ".otf", ".eot", ".db", ".sqlite", ".sqlite3", ".lock",
    ],
    "included_filenames": ["Dockerfile", "Makefile", "Procfile", ".gitignore"],
    "excluded_filenames": [],
}

app = FastAPI(title="AI Multi-File Editor")


# ============================================================
# Editor root (dynamic, persisted)
# ============================================================

def load_editor_root() -> Path:
    if EDITOR_CONFIG_FILE.is_file():
        try:
            data = json.loads(EDITOR_CONFIG_FILE.read_text(encoding="utf-8"))
            r = str(data.get("root", "")).strip()
            if r:
                return Path(r).expanduser().resolve()
        except Exception:
            pass
    return DEFAULT_ROOT


def save_editor_root(path: str) -> None:
    atomic_write_json(EDITOR_CONFIG_FILE, {"root": str(path)})


def current_backup_dir() -> Path:
    return load_editor_root() / ".backup"


def current_history_file() -> Path:
    return current_backup_dir() / "history.json"


# ============================================================
# Small helpers
# ============================================================

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_file(p) -> str:
    return Path(p).read_text(encoding="utf-8")


def write_file(p, content: str) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def atomic_write_text(p, text: str) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def atomic_write_json(p, data) -> None:
    atomic_write_text(p, json.dumps(data, indent=2, ensure_ascii=False))


def get_ext(filename: str) -> str:
    name = filename.lower()
    if name.startswith(".") and name.count(".") == 1:
        return name
    return os.path.splitext(name)[1]


def is_binary_file(path: Path, probe: int = 8192) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(probe)
        return b"\x00" in chunk
    except Exception:
        return True


def safe_join(root: Path, rel: str) -> Path:
    rel_norm = rel.replace("\\", "/").lstrip("/")
    p = (root / rel_norm).resolve()
    p.relative_to(root)
    return p


def resolve_rel(raw: str, root: Optional[Path] = None):
    if root is None:
        root = load_editor_root()
    if raw is None:
        raise HTTPException(status_code=400, detail="A file path is missing.")
    text = str(raw).strip()
    if not text:
        raise HTTPException(status_code=400, detail="An empty file path is not allowed.")
    if "\x00" in text:
        raise HTTPException(status_code=400, detail=f"Path contains a null byte: {raw!r}")

    normalised = text.replace("\\", "/")
    if normalised.startswith("/"):
        raise HTTPException(status_code=400, detail=f"Absolute paths are not allowed: {raw}")
    if len(normalised) > 1 and normalised[1] == ":":
        raise HTTPException(status_code=400, detail=f"Absolute paths are not allowed: {raw}")

    full = (root / normalised).resolve()
    try:
        rel = full.relative_to(root).as_posix()
    except ValueError:
        raise HTTPException(status_code=400,
                            detail=f"Path escapes the project root and was rejected: {raw}")
    if not rel or rel == ".":
        raise HTTPException(status_code=400, detail=f"Invalid path: {raw}")
    if rel.split("/")[0] == ".backup":
        raise HTTPException(status_code=400,
                            detail=f"Paths inside .backup are not allowed: {raw}")
    return rel, full


def save_recording_bytes(content: bytes, original_filename: str = "voice.webm") -> str:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    ext = os.path.splitext(original_filename or "")[1].lower()
    if ext not in (".webm", ".ogg", ".m4a", ".mp4", ".wav", ".mp3"):
        ext = ".webm"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"rec_{stamp}_{uuid.uuid4().hex[:8]}{ext}"
    target = RECORDINGS_DIR / fname
    target.write_bytes(content)

    # Also copy into active project's .editor_recordings folder if root exists
    try:
        proj_root = load_editor_root()
        if proj_root.is_dir():
            proj_rec_dir = proj_root / ".backup" / "recordings"
            proj_rec_dir.mkdir(parents=True, exist_ok=True)
            (proj_rec_dir / fname).write_bytes(content)
    except Exception:
        pass

    return fname


# ============================================================
# History / backup
# ============================================================

def load_history(history_file: Optional[Path] = None) -> List[dict]:
    f = Path(history_file) if history_file else current_history_file()
    if not f.is_file():
        return []
    try:
        data = json.loads(read_file(f))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_history(items: List[dict], history_file: Optional[Path] = None) -> None:
    f = Path(history_file) if history_file else current_history_file()
    atomic_write_json(f, items)


def new_backup_dir(bdir: Path) -> Path:
    bdir.mkdir(parents=True, exist_ok=True)
    base = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    candidate = bdir / base
    counter = 1
    while candidate.exists():
        candidate = bdir / f"{base}_{counter}"
        counter += 1
    return candidate


def perform_operation(ops: List[dict], op_type: str) -> dict:
    bdir = current_backup_dir()
    backup = new_backup_dir(bdir)
    backup.mkdir(parents=True, exist_ok=False)
    hist_file = bdir / "history.json"

    manifest = {
        "id": backup.name,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "type": op_type,
        "files": [],
    }

    for op in ops:
        rel = op["rel"]
        manifest["files"].append({
            "path": rel,
            "status": op["status"],
            "old_exists": bool(op["old_exists"]),
            "new_exists": bool(op["new_exists"]),
        })
        if op["old_exists"]:
            try:
                write_file(backup / "old" / rel, op["old_content"])
            except Exception:
                pass
        if op["new_exists"]:
            try:
                write_file(backup / "new" / rel, op["new_content"])
            except Exception:
                pass

    write_file(backup / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

    errors: List[dict] = []
    applied = 0
    for op in ops:
        try:
            if op["new_exists"]:
                write_file(op["full"], op["new_content"])
            else:
                if op["full"].exists():
                    op["full"].unlink()
            applied += 1
        except Exception as exc:
            errors.append({"path": op["rel"], "error": str(exc)})

    for op in ops:
        rel = op["rel"]
        if any(e["path"] == rel for e in errors):
            continue
        try:
            if op["new_exists"]:
                if not op["full"].is_file():
                    errors.append({"path": rel, "error": "file missing after write"})
                elif read_file(op["full"]) != op["new_content"]:
                    errors.append({"path": rel, "error": "content differs after write"})
            else:
                if op["full"].exists():
                    errors.append({"path": rel, "error": "file still exists after delete"})
        except Exception as exc:
            errors.append({"path": rel, "error": f"verification error: {exc}"})

    bad = {e["path"] for e in errors}
    applied = max(0, applied - len(bad))

    record = {
        "id": backup.name,
        "timestamp": manifest["timestamp"],
        "type": op_type,
        "count": len(ops),
        "files": [{"path": o["rel"], "status": o["status"]} for o in ops],
    }
    with _LOCK:
        history = load_history(hist_file)
        history.insert(0, record)
        save_history(history, hist_file)

    return {"record": record, "applied": applied, "errors": errors}


def backup_dir_for(history_id: str) -> Path:
    if (not history_id or "/" in history_id or "\\" in history_id
            or history_id in (".", "..") or history_id.startswith(".")):
        raise HTTPException(status_code=400, detail="Invalid history id.")
    bdir = current_backup_dir()
    candidate = (bdir / history_id).resolve()
    try:
        candidate.relative_to(bdir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid history id.")
    if not (candidate / "manifest.json").is_file():
        raise HTTPException(status_code=404, detail=f"History entry not found: {history_id}")
    return candidate


# ============================================================
# Generator config + scan + generate
# ============================================================

def _norm_list(raw, lower=False, dot_if_ext=False):
    out = []
    seen = set()
    for x in (raw or []):
        if x is None:
            continue
        s = str(x).strip().replace("\\", "/")
        if not s:
            continue
        if dot_if_ext:
            if not s.startswith("."):
                s = "." + s
        if lower:
            s = s.lower()
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def normalize_gen_config(data: dict) -> dict:
    base = dict(DEFAULT_GEN_CONFIG)
    if not isinstance(data, dict):
        return base
    return {
        "root": str(data.get("root", "")).strip(),
        "included_folders": _norm_list(data.get("included_folders")),
        "excluded_folders": _norm_list(data.get("excluded_folders")),
        "included_files": _norm_list(data.get("included_files")),
        "excluded_files": _norm_list(data.get("excluded_files")),
        "included_extensions": _norm_list(data.get("included_extensions"), lower=True, dot_if_ext=True),
        "excluded_extensions": _norm_list(data.get("excluded_extensions"), lower=True, dot_if_ext=True),
        "included_filenames": _norm_list(data.get("included_filenames")),
        "excluded_filenames": _norm_list(data.get("excluded_filenames")),
    }


def load_gen_config() -> dict:
    if not GEN_CONFIG_FILE.is_file():
        return dict(DEFAULT_GEN_CONFIG)
    try:
        return normalize_gen_config(json.loads(read_file(GEN_CONFIG_FILE)))
    except Exception:
        return dict(DEFAULT_GEN_CONFIG)


def save_gen_config(cfg: dict) -> None:
    atomic_write_json(GEN_CONFIG_FILE, normalize_gen_config(cfg))


def scan_project(config: dict) -> dict:
    root_raw = str(config.get("root", "")).strip()
    if not root_raw:
        raise HTTPException(400, "Project root is empty. Set a project folder first.")
    root_path = Path(root_raw).expanduser()
    try:
        root_path = root_path.resolve()
    except Exception as e:
        raise HTTPException(400, f"Invalid path: {e}")
    if not root_path.is_dir():
        raise HTTPException(400, f"Not a directory: {root_path}")

    excl_folders = set(config["excluded_folders"])
    incl_folders = set(config["included_folders"])
    excl_files = set(config["excluded_files"])
    incl_files = set(config["included_files"])
    excl_exts = set(config["excluded_extensions"])
    incl_exts = set(config["included_extensions"])
    excl_names = set(config["excluded_filenames"])
    incl_names = set(config["included_filenames"])

    output_resolved = GENERATED_OUTPUT.resolve()

    def should_descend(rel_folder: str) -> bool:
        if not incl_folders:
            return True
        for inc in incl_folders:
            if inc == "" or inc == rel_folder:
                return True
            if inc.startswith(rel_folder + "/") or rel_folder.startswith(inc + "/"):
                return True
        return False

    def should_consider_file(rel_file: str) -> bool:
        if not incl_folders:
            return True
        for inc in incl_folders:
            if inc == "" or rel_file.startswith(inc + "/") or rel_file == inc:
                return True
        return False

    included: List[dict] = []
    excluded_folders: List[dict] = []
    excluded_files: List[dict] = []
    errors: List[str] = []

    def count_files(folder: Path, limit: int = 5000) -> int:
        n = 0
        try:
            for p in folder.rglob("*"):
                if p.is_file():
                    n += 1
                    if n >= limit:
                        break
        except Exception:
            return -1
        return n

    for current, dirs, files in os.walk(root_path, followlinks=False):
        rel_current = Path(current).relative_to(root_path).as_posix()
        if rel_current == ".":
            rel_current = ""

        keep_dirs: List[str] = []
        for d in sorted(dirs):
            rel_d = (rel_current + "/" + d) if rel_current else d
            if d in excl_folders or rel_d in excl_folders:
                excluded_folders.append({
                    "path": rel_d,
                    "reason": "excluded folder rule",
                    "file_count": count_files(Path(current) / d),
                })
                continue
            if not should_descend(rel_d):
                continue
            keep_dirs.append(d)
        dirs[:] = keep_dirs

        for f in sorted(files):
            if f == "project_source.txt":
                try:
                    if (Path(current) / f).resolve() == output_resolved:
                        continue
                except Exception:
                    continue

            rel_f = (rel_current + "/" + f) if rel_current else f
            if not should_consider_file(rel_f):
                continue

            ext = get_ext(f)
            reason = None
            if rel_f in excl_files:
                reason = "excluded file path"
            elif f in excl_names:
                reason = "excluded filename"
            elif ext and ext in excl_exts:
                reason = f"excluded extension {ext}"
            if reason:
                excluded_files.append({"path": rel_f, "reason": reason})
                continue

            include = (rel_f in incl_files or f in incl_names
                       or (ext and ext in incl_exts))
            if not include:
                excluded_files.append({"path": rel_f, "reason": "no matching include rule"})
                continue

            full = Path(current) / f
            try:
                size = full.stat().st_size
            except Exception:
                size = 0

            if is_binary_file(full):
                excluded_files.append({"path": rel_f, "reason": "binary file"})
                continue

            included.append({"path": rel_f, "size": size, "ext": ext})

    return {
        "root": str(root_path),
        "included": included,
        "excluded_folders": excluded_folders,
        "excluded_files": excluded_files,
        "errors": errors,
    }


def generate_source(config: dict, selected_files: Optional[List[str]] = None) -> dict:
    scan = scan_project(config)
    root = Path(scan["root"])
    wanted = set(selected_files) if selected_files is not None else None

    parts: List[str] = []
    errors: List[str] = []
    count = 0
    total_bytes = 0

    for item in scan["included"]:
        rel = item["path"]
        if wanted is not None and rel not in wanted:
            continue
        try:
            full = safe_join(root, rel)
        except ValueError as e:
            errors.append(f"{rel}: {e}")
            continue
        try:
            content = full.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            errors.append(f"{rel}: {e}")
            continue
        chunk = "/" + rel + "\n\n" + content + "\n\n"
        parts.append(chunk)
        total_bytes += len(chunk.encode("utf-8"))
        count += 1

    try:
        GENERATED_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        GENERATED_OUTPUT.write_text("".join(parts), encoding="utf-8")
    except Exception as e:
        raise HTTPException(500, f"Could not write project_source.txt: {e}")

    return {
        "ok": True,
        "output": str(GENERATED_OUTPUT),
        "included_count": count,
        "excluded_folders_count": len(scan["excluded_folders"]),
        "excluded_files_count": len(scan["excluded_files"]),
        "errors": errors,
        "bytes": total_bytes,
    }


# ============================================================
# Prompt history + fixed prompt
# ============================================================

def load_prompt_store() -> dict:
    if not PROMPT_HISTORY_FILE.is_file():
        return {"next_rank": 1, "items": []}
    try:
        data = json.loads(read_file(PROMPT_HISTORY_FILE))
        if not isinstance(data, dict):
            raise ValueError("bad structure")
        items = data.get("items", [])
        if not isinstance(items, list):
            items = []
        return {"next_rank": max(1, int(data.get("next_rank", len(items) + 1))), "items": items}
    except Exception:
        return {"next_rank": 1, "items": []}


def save_prompt_store(store: dict) -> None:
    atomic_write_json(PROMPT_HISTORY_FILE, store)


def load_fixed_prompt() -> str:
    if FIXED_PROMPT_FILE.is_file():
        try:
            saved = read_file(FIXED_PROMPT_FILE)
        except Exception:
            return DEFAULT_FIXED_PROMPT
        if saved.strip() == OLD_DEFAULT_FIXED_PROMPT.strip():
            try:
                save_fixed_prompt(DEFAULT_FIXED_PROMPT)
            except Exception:
                pass
            return DEFAULT_FIXED_PROMPT
        return saved
    return DEFAULT_FIXED_PROMPT


def save_fixed_prompt(text: str) -> None:
    atomic_write_text(FIXED_PROMPT_FILE, text)


# ============================================================
# Native file picker
# ============================================================

PORTAL_HELPER = '''\
import sys
try:
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
except Exception:
    sys.exit(2)

kind = sys.argv[1] if len(sys.argv) > 1 else "folder"
initial = sys.argv[2] if len(sys.argv) > 2 else ""

try:
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    portal = bus.get_object(
        "org.freedesktop.portal.Desktop",
        "/org/freedesktop/portal/desktop",
    )
    chooser = dbus.Interface(portal, "org.freedesktop.portal.FileChooser")
    opts = {
        "multiple": False,
        "directory": (kind == "folder"),
        "modal": True,
    }
    if initial:
        try:
            opts["current_folder"] = dbus.ByteArray((initial + "/").encode("utf-8"))
        except Exception:
            pass
    handle = chooser.OpenFile("", "Select", dbus.Dictionary(opts, signature="sv"))
    result = {"path": ""}
    loop = GLib.MainLoop()

    def on_resp(code, results):
        if code == 0:
            uris = results.get("uris", [])
            if uris:
                from urllib.parse import urlparse, unquote
                result["path"] = unquote(urlparse(str(uris[0])).path)
        loop.quit()

    req = bus.get_object("org.freedesktop.portal.Desktop", handle)
    iface = dbus.Interface(req, "org.freedesktop.portal.Request")
    iface.connect_to_signal("Response", on_resp)
    GLib.timeout_add_seconds(900, loop.quit)
    loop.run()
    sys.stdout.write(result["path"])
except Exception:
    sys.exit(3)
'''

TK_PICKER = (
    "import sys, tkinter as tk\n"
    "from tkinter import filedialog\n"
    "initial = sys.argv[1] if len(sys.argv) > 1 else ''\n"
    "kind = sys.argv[2] if len(sys.argv) > 2 else 'file'\n"
    "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
    "try:\n"
    "    if kind == 'folder':\n"
    "        p = filedialog.askdirectory(initialdir=(initial or None), title='Select Folder')\n"
    "    else:\n"
    "        p = filedialog.askopenfilename(initialdir=(initial or None), title='Select File')\n"
    "finally:\n"
    "    r.destroy()\n"
    "sys.stdout.write(p or '')\n"
)


def _try_portal(kind: str, initial: str):
    try:
        res = subprocess.run(
            [sys.executable, "-c", PORTAL_HELPER, kind, initial or ""],
            capture_output=True, text=True, timeout=900,
        )
    except Exception:
        return None
    if res.returncode == 0:
        return res.stdout
    return None


def _try_zenity(kind: str, initial: str):
    if not shutil.which("zenity"):
        return None
    if kind == "folder":
        cmd = ["zenity", "--file-selection", "--directory", "--title=Select Folder"]
    else:
        cmd = ["zenity", "--file-selection", "--title=Select File"]
    if initial:
        cmd.append("--filename=" + initial.rstrip("/") + "/")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except Exception:
        return None
    if res.returncode == 0:
        return res.stdout.strip()
    if res.returncode == 1:
        return ""
    return None


def _try_kdialog(kind: str, initial: str):
    if not shutil.which("kdialog"):
        return None
    if kind == "folder":
        cmd = ["kdialog", "--getexistingdirectory", initial or "."]
    else:
        cmd = ["kdialog", "--getopenfilename", initial or "."]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except Exception:
        return None
    if res.returncode == 0:
        return res.stdout.strip()
    if res.returncode == 1:
        return ""
    return None


def _try_tkinter(kind: str, initial: str):
    try:
        res = subprocess.run(
            [sys.executable, "-c", TK_PICKER, initial or "", kind],
            capture_output=True, text=True, timeout=900,
        )
    except Exception:
        return None
    if res.returncode == 0:
        return res.stdout.strip()
    return None


def _pick_path(kind: str, initial: str) -> str:
    for fn in (_try_portal, _try_zenity, _try_kdialog, _try_tkinter):
        out = fn(kind, initial)
        if out is not None:
            return out
    raise HTTPException(
        500,
        "No native file picker available. Install xdg-desktop-portal "
        "(with python3-dbus and python3-gi), zenity or kdialog. "
        "Manual path entry still works.",
    )


# ============================================================
# Patch protocol — models & resolver
# ============================================================

class PatchOperationIn(BaseModel):
    type: str
    lines: Optional[str] = None
    match: Optional[str] = None
    anchor: Optional[str] = None
    with_content: Optional[str] = None


class PatchFileIn(BaseModel):
    path: str
    mode: str
    operations: List[PatchOperationIn] = []
    content: Optional[str] = None


class FilesIn(BaseModel):
    files: Dict[str, str] = {}
    ops: List[PatchFileIn] = []
    expected: Optional[Dict[str, Optional[str]]] = None


class RestoreIn(BaseModel):
    force: bool = False


class GenConfigIn(BaseModel):
    root: str = ""
    included_folders: List[str] = []
    excluded_folders: List[str] = []
    included_files: List[str] = []
    excluded_files: List[str] = []
    included_extensions: List[str] = []
    excluded_extensions: List[str] = []
    included_filenames: List[str] = []
    excluded_filenames: List[str] = []


class GenerateSelectedIn(BaseModel):
    config: GenConfigIn
    files: List[str] = []


class AnalyzeIn(BaseModel):
    prompt: str
    config: GenConfigIn
    max_files: int = 50
    api_keys: List[str] = []


class FolderContentsIn(BaseModel):
    root: str
    path: str


class PickIn(BaseModel):
    initial: str = ""
    base: str = ""


class PromptSnapshotIn(BaseModel):
    custom_prompt: str
    combined_prompt: str
    recording_filename: Optional[str] = None


class FixedPromptIn(BaseModel):
    text: str


class EditorRootIn(BaseModel):
    root: str


def _detect_newline(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def _convert_newlines(text: str, target: str) -> str:
    normalized = text.replace("\r\n", "\n")
    if target == "\r\n":
        return normalized.replace("\n", "\r\n")
    return normalized


def _split_keepends(text: str) -> List[str]:
    lines: List[str] = []
    i, n = 0, len(text)
    while i < n:
        j = text.find("\n", i)
        if j < 0:
            lines.append(text[i:])
            break
        lines.append(text[i:j + 1])
        i = j + 1
    return lines


def _strip_lc(line: str) -> str:
    return line.rstrip("\r\n")


def _parse_line_hint(hint: Optional[str]) -> Optional[Tuple[int, int]]:
    if not hint:
        return None
    m = re.match(r"^(\d+)(?:\s*-\s*(\d+))?$", hint.strip())
    if not m:
        return None
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else start
    if start < 1 or end < start:
        return None
    return (start, end)


def _find_sequence(source_lines: List[str], match_lines: List[str]) -> List[int]:
    if not match_lines:
        return []
    norm_src = [_strip_lc(l) for l in source_lines]
    norm_match = [_strip_lc(l) for l in match_lines]
    n, m = len(norm_match), len(norm_src)
    if n > m:
        return []
    out: List[int] = []
    for i in range(m - n + 1):
        if norm_src[i:i + n] == norm_match:
            out.append(i)
    return out


def _disambiguate(positions: List[int], match_len: int,
                  hint: Optional[Tuple[int, int]]) -> Optional[int]:
    if not positions:
        return None
    if len(positions) == 1:
        return positions[0]
    if hint:
        hs, he = hint
        candidates = []
        for p in positions:
            m_start = p + 1
            m_end = p + match_len
            if m_start <= he and m_end >= hs:
                candidates.append(p)
        if len(candidates) == 1:
            return candidates[0]
    return None


def resolve_patch(source: str, operations: List[PatchOperationIn]) -> Tuple[str, List[dict]]:
    src_nl = _detect_newline(source)
    source_lines = _split_keepends(source)

    offsets = [0]
    for line in source_lines:
        offsets.append(offsets[-1] + len(line))

    edits: List[dict] = []

    for idx, op in enumerate(operations):
        op_type = (op.type or "").upper().strip()
        hint = _parse_line_hint(op.lines)

        if op_type == "REPLACE":
            if op.match is None or op.with_content is None:
                raise HTTPException(400, f"Op #{idx+1} REPLACE missing @@MATCH or @@WITH")
            match_text = _convert_newlines(op.match, src_nl)
            match_lines = _split_keepends(match_text)
            positions = _find_sequence(source_lines, match_lines)
            pos = _disambiguate(positions, len(match_lines), hint)
            if pos is None:
                if not positions:
                    raise HTTPException(400, f"Op #{idx+1} REPLACE: match block not found in source")
                raise HTTPException(400, f"Op #{idx+1} REPLACE: match ambiguous ({len(positions)} occurrences); provide accurate @@LINES")
            start_c = offsets[pos]
            end_c = offsets[pos + len(match_lines)]
            replacement = _convert_newlines(op.with_content, src_nl)
            edits.append({
                "start": start_c, "end": end_c, "replacement": replacement,
                "index": idx, "type": "replace",
                "old": source[start_c:end_c],
                "line_start": pos + 1, "line_end": pos + len(match_lines),
            })

        elif op_type == "DELETE":
            if op.match is None:
                raise HTTPException(400, f"Op #{idx+1} DELETE missing @@MATCH")
            match_text = _convert_newlines(op.match, src_nl)
            match_lines = _split_keepends(match_text)
            positions = _find_sequence(source_lines, match_lines)
            pos = _disambiguate(positions, len(match_lines), hint)
            if pos is None:
                if not positions:
                    raise HTTPException(400, f"Op #{idx+1} DELETE: match block not found in source")
                raise HTTPException(400, f"Op #{idx+1} DELETE: match ambiguous ({len(positions)} occurrences)")
            start_c = offsets[pos]
            end_c = offsets[pos + len(match_lines)]
            edits.append({
                "start": start_c, "end": end_c, "replacement": "",
                "index": idx, "type": "delete",
                "old": source[start_c:end_c],
                "line_start": pos + 1, "line_end": pos + len(match_lines),
            })

        elif op_type in ("INSERT_BEFORE", "INSERT_AFTER"):
            if op.anchor is None or op.with_content is None:
                raise HTTPException(400, f"Op #{idx+1} {op_type} missing @@ANCHOR or @@WITH")
            anchor_text = _convert_newlines(op.anchor, src_nl)
            anchor_lines = _split_keepends(anchor_text)
            positions = _find_sequence(source_lines, anchor_lines)
            pos = _disambiguate(positions, len(anchor_lines), hint)
            if pos is None:
                if not positions:
                    raise HTTPException(400, f"Op #{idx+1} {op_type}: anchor not found in source")
                raise HTTPException(400, f"Op #{idx+1} {op_type}: anchor ambiguous ({len(positions)} occurrences)")
            insertion = _convert_newlines(op.with_content, src_nl)
            if op_type == "INSERT_BEFORE":
                insert_pos = offsets[pos]
                line_num = pos + 1
            else:
                insert_pos = offsets[pos + len(anchor_lines)]
                line_num = pos + len(anchor_lines) + 1
            edits.append({
                "start": insert_pos, "end": insert_pos, "replacement": insertion,
                "index": idx, "type": op_type.lower(),
                "old": "",
                "line_start": line_num, "line_end": line_num,
            })

        elif op_type == "INSERT_AT_START":
            if op.with_content is None:
                raise HTTPException(400, f"Op #{idx+1} INSERT_AT_START missing @@WITH")
            insertion = _convert_newlines(op.with_content, src_nl)
            edits.append({
                "start": 0, "end": 0, "replacement": insertion,
                "index": idx, "type": "insert_at_start",
                "old": "", "line_start": 1, "line_end": 1,
            })

        elif op_type == "INSERT_AT_END":
            if op.with_content is None:
                raise HTTPException(400, f"Op #{idx+1} INSERT_AT_END missing @@WITH")
            insertion = _convert_newlines(op.with_content, src_nl)
            total = offsets[-1]
            edits.append({
                "start": total, "end": total, "replacement": insertion,
                "index": idx, "type": "insert_at_end",
                "old": "",
                "line_start": len(source_lines) + 1, "line_end": len(source_lines) + 1,
            })

        else:
            raise HTTPException(400, f"Op #{idx+1}: unknown operation type '{op_type}'")

    replaces = [e for e in edits if e["end"] > e["start"]]
    for i, e1 in enumerate(replaces):
        for e2 in replaces[i + 1:]:
            if e1["start"] < e2["end"] and e2["start"] < e1["end"]:
                raise HTTPException(
                    400,
                    f"Operations overlap: {e1['type']} lines {e1['line_start']}-{e1['line_end']} "
                    f"conflicts with {e2['type']} lines {e2['line_start']}-{e2['line_end']}"
                )
    inserts = [e for e in edits if e["end"] == e["start"]]
    for ie in inserts:
        for re_ in replaces:
            if re_["start"] < ie["start"] < re_["end"]:
                raise HTTPException(400, f"Insertion inside replaced/deleted region at line {ie['line_start']}")

    edits_sorted = sorted(edits, key=lambda e: (e["start"], e["end"], e["index"]), reverse=True)
    result = source
    for e in edits_sorted:
        result = result[:e["start"]] + e["replacement"] + result[e["end"]:]

    changes = [
        {
            "type": e["type"],
            "old": e["old"],
            "new": e["replacement"],
            "line_start": e["line_start"],
            "line_end": e["line_end"],
        }
        for e in edits
    ]
    changes.sort(key=lambda c: c["line_start"])
    return result, changes


# ============================================================
# Check / apply
# ============================================================

def _resolve_check(req: FilesIn) -> dict:
    root = load_editor_root()
    if not root.is_dir():
        raise HTTPException(400, f"Editor root does not exist: {root}")

    results: List[dict] = []
    errors: List[dict] = []
    seen = set()

    def _add(result: dict):
        if result["path"] in seen:
            raise HTTPException(400, f"Duplicate path: {result['path']}")
        seen.add(result["path"])
        results.append(result)

    def _fail(path: str, detail):
        seen.add(path)
        errors.append({"path": path, "error": str(detail)})

    for key, content in (req.files or {}).items():
        try:
            rel, full = resolve_rel(key, root)
        except HTTPException as exc:
            _fail(str(key), exc.detail)
            continue
        try:
            exists = full.is_file()
            old = None
            if exists:
                old = read_file(full)
                status = "unchanged" if old == content else "modified"
            else:
                status = "new"
            _add({
                "path": rel, "mode": "legacy", "status": status,
                "old": old if status == "modified" else None,
                "new": content,
                "old_hash": sha256(old) if exists else None,
                "changes": [],
            })
        except Exception as exc:
            _fail(key, exc)

    for entry in (req.ops or []):
        try:
            rel, full = resolve_rel(entry.path, root)
        except HTTPException as exc:
            _fail(entry.path, exc.detail)
            continue

        mode = (entry.mode or "").lower()
        try:
            if mode == "full":
                content = entry.content if entry.content is not None else ""
                exists = full.is_file()
                old = None
                if exists:
                    old = read_file(full)
                    status = "unchanged" if old == content else "modified"
                else:
                    status = "new"
                _add({
                    "path": rel, "mode": "full", "status": status,
                    "old": old if status == "modified" else None,
                    "new": content,
                    "old_hash": sha256(old) if exists else None,
                    "changes": [],
                })

            elif mode == "delete":
                if not full.is_file():
                    raise HTTPException(400, f"Cannot delete {rel}: file does not exist")
                old = read_file(full)
                _add({
                    "path": rel, "mode": "delete", "status": "deleted",
                    "old": old, "new": None,
                    "old_hash": sha256(old),
                    "changes": [{"type": "delete_file", "old": old, "new": "",
                                 "line_start": 1, "line_end": max(1, old.count("\n"))}],
                })

            elif mode == "patch":
                if not full.is_file():
                    raise HTTPException(400, f"Cannot patch {rel}: file does not exist (use @@FULL to create new files)")
                old = read_file(full)
                new_content, changes = resolve_patch(old, entry.operations)
                status = "unchanged" if new_content == old else "modified"
                _add({
                    "path": rel, "mode": "patch", "status": status,
                    "old": old if status == "modified" else None,
                    "new": new_content,
                    "old_hash": sha256(old),
                    "changes": changes if status == "modified" else [],
                })

            else:
                raise HTTPException(400, f"Unknown mode '{entry.mode}' for {entry.path}")

        except HTTPException as exc:
            _fail(rel, exc.detail)
        except Exception as exc:
            _fail(rel, exc)

    return {"root": str(root), "files": results, "errors": errors}


# ============================================================
# AI provider helpers (Multi-key fallback)
# ============================================================

def _resolve_api_keys(frontend_keys: Optional[List[str]] = None) -> List[str]:
    keys: List[str] = []
    seen = set()
    for raw in (frontend_keys or []):
        if not raw:
            continue
        for part in re.split(r"[\r\n,]+", str(raw)):
            k = part.strip()
            if k and k not in seen:
                seen.add(k)
                keys.append(k)
    if AI_API_KEY:
        for part in re.split(r"[\r\n,]+", AI_API_KEY):
            k = part.strip()
            if k and k not in seen:
                seen.add(k)
                keys.append(k)
    if not keys:
        raise HTTPException(
            400,
            "No Groq API keys provided. Enter one or more Groq API keys in the top bar (or set AI_API_KEY)."
        )
    return keys


def _mask_key(k: str) -> str:
    if len(k) <= 10:
        return "***"
    return f"{k[:6]}…{k[-4:]}"


def _build_manifest(scan: dict) -> Tuple[str, int]:
    root = Path(scan["root"])
    MAX_TOTAL = 22_000
    MAX_HEAD_LINES = 30
    MAX_PER_FILE = 1_000
    out: List[str] = []
    total = 0
    count = 0
    for item in scan["included"]:
        rel = item["path"]
        try:
            full = safe_join(root, rel)
            text = full.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        head_lines = text.splitlines()[:MAX_HEAD_LINES]
        head = "\n".join(head_lines)[:MAX_PER_FILE]
        block = f"=== {rel} ({item['size']} B) ===\n{head}\n"
        if total + len(block) > MAX_TOTAL:
            rem_block = f"=== {rel} ({item['size']} B) ===\n"
            if total + len(rem_block) > MAX_TOTAL + 4_000:
                break
            out.append(rem_block)
            total += len(rem_block)
            count += 1
            continue
        out.append(block)
        total += len(block)
        count += 1
    return "\n".join(out), count


# ============================================================
# Routes
# ============================================================

@app.get("/")
def index():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/api/recordings/{filename}")
def api_get_recording(filename: str):
    if not filename or "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(400, "Invalid recording filename.")
    target = (RECORDINGS_DIR / filename).resolve()
    try:
        target.relative_to(RECORDINGS_DIR.resolve())
    except ValueError:
        raise HTTPException(400, "Invalid recording path.")
    if not target.is_file():
        raise HTTPException(404, "Recording not found.")
    return FileResponse(target, filename=filename)


@app.get("/api/project")
def api_project_get():
    root = load_editor_root()
    return {
        "root": str(root),
        "name": root.name,
        "exists": root.is_dir(),
        "backup_dir": str(root / ".backup"),
        "default": str(DEFAULT_ROOT),
    }


@app.post("/api/project")
def api_project_set(body: EditorRootIn):
    raw = (body.root or "").strip()
    if not raw:
        raise HTTPException(400, "Root path is empty.")
    p = Path(raw).expanduser()
    try:
        p = p.resolve()
    except Exception as e:
        raise HTTPException(400, f"Invalid path: {e}")
    if not p.is_dir():
        raise HTTPException(400, f"Not an existing directory: {p}")
    save_editor_root(str(p))
    return api_project_get()


@app.post("/api/check")
def api_check(req: FilesIn):
    return _resolve_check(req)


@app.post("/api/apply")
def api_apply(req: FilesIn):
    check = _resolve_check(req)
    expected = req.expected or {}
    root = load_editor_root()

    conflicts: List[str] = []
    ops: List[dict] = []
    for f in check["files"]:
        rel = f["path"]
        if rel in expected and expected[rel] != f["old_hash"]:
            conflicts.append(rel)
            continue
        if f["status"] == "unchanged":
            continue
        _, full = resolve_rel(rel, root)
        ops.append({
            "rel": rel, "full": full,
            "old_exists": f["old"] is not None or f["status"] == "deleted",
            "old_content": f["old"],
            "new_exists": f["new"] is not None,
            "new_content": f["new"],
            "status": f["status"],
        })

    if conflicts:
        raise HTTPException(status_code=409, detail={
            "message": "CONFLICT: files changed since the preview was generated.",
            "conflicts": conflicts,
        })

    applied = 0
    write_errors: List[dict] = []
    record = None
    if ops:
        result = perform_operation(ops, "apply")
        applied = result["applied"]
        write_errors = result["errors"]
        record = result["record"]

    all_errors = list(check["errors"]) + write_errors
    return {
        "ok": len(all_errors) == 0,
        "applied": applied,
        "errors": all_errors,
        "record": record,
        "message": (
            f"Applied {applied} file(s)."
            + (f" {len(all_errors)} failed." if all_errors else "")
        ),
    }


@app.get("/api/history")
def api_history():
    return {"history": load_history()}


@app.get("/api/history/{history_id}")
def api_history_item(history_id: str):
    backup = backup_dir_for(history_id)
    manifest = json.loads(read_file(backup / "manifest.json"))
    files = []
    for entry in manifest.get("files", []):
        rel = entry["path"]
        old = None
        new = None
        if entry.get("old_exists"):
            p = backup / "old" / rel
            if p.is_file():
                old = read_file(p)
        if entry.get("new_exists"):
            p = backup / "new" / rel
            if p.is_file():
                new = read_file(p)
        files.append({
            "path": rel,
            "status": entry.get("status", "modified"),
            "old_exists": bool(entry.get("old_exists")),
            "new_exists": bool(entry.get("new_exists")),
            "old": old, "new": new,
        })
    return {
        "id": manifest.get("id", history_id),
        "timestamp": manifest.get("timestamp", ""),
        "type": manifest.get("type", ""),
        "files": files,
    }


@app.post("/api/history/{history_id}/restore")
def api_restore(history_id: str, body: RestoreIn):
    root = load_editor_root()
    backup = backup_dir_for(history_id)
    manifest = json.loads(read_file(backup / "manifest.json"))
    ops: List[dict] = []
    conflicts: List[str] = []

    for entry in manifest.get("files", []):
        rel, full = resolve_rel(entry["path"], root)
        current_exists = full.is_file()
        current_content = read_file(full) if current_exists else None

        new_exists = bool(entry.get("new_exists"))
        new_content = None
        if new_exists:
            p = backup / "new" / rel
            new_content = read_file(p) if p.is_file() else None

        target_exists = bool(entry.get("old_exists"))
        target_content = None
        if target_exists:
            p = backup / "old" / rel
            target_content = read_file(p) if p.is_file() else None

        if new_exists:
            if not current_exists or current_content != new_content:
                conflicts.append(rel)
        else:
            if current_exists:
                conflicts.append(rel)

        if target_exists == current_exists:
            if not target_exists or target_content == current_content:
                continue

        ops.append({
            "rel": rel, "full": full,
            "old_exists": current_exists, "old_content": current_content,
            "new_exists": target_exists, "new_content": target_content,
            "status": "restored" if target_exists else "deleted",
        })

    if conflicts and not body.force:
        raise HTTPException(status_code=409, detail={
            "message": "CONFLICT: these files changed after the original operation.",
            "conflicts": conflicts,
        })
    if not ops:
        return {"ok": True, "restored": 0,
                "message": "Nothing to restore — files are already in the previous state."}
    result = perform_operation(ops, "restore")
    return {"ok": True, "restored": result["applied"],
            "errors": result["errors"], "record": result["record"]}


# ---- Generator routes ------------------------------------------

@app.get("/api/gen/config")
def api_gen_config_get():
    cfg = load_gen_config()
    if not cfg.get("root"):
        cfg["root"] = str(DEFAULT_ROOT)
    return {"config": cfg, "defaults": DEFAULT_GEN_CONFIG}


@app.post("/api/gen/config")
def api_gen_config_save(cfg: GenConfigIn):
    norm = normalize_gen_config(cfg.model_dump())
    save_gen_config(norm)
    return {"ok": True, "config": norm}


@app.post("/api/gen/scan")
def api_gen_scan(cfg: GenConfigIn):
    return scan_project(normalize_gen_config(cfg.model_dump()))


@app.post("/api/gen/generate")
def api_gen_generate(cfg: GenConfigIn):
    norm = normalize_gen_config(cfg.model_dump())
    save_gen_config(norm)
    return generate_source(norm)


@app.post("/api/gen/generate-selected")
def api_gen_generate_selected(req: GenerateSelectedIn):
    norm = normalize_gen_config(req.config.model_dump())
    save_gen_config(norm)
    if not req.files:
        raise HTTPException(400, "No files selected.")
    return generate_source(norm, selected_files=req.files)


# ---- AI routes (with Multi-Key Fallback) -----------------------

@app.post("/api/ai/analyze")
def api_ai_analyze(req: AnalyzeIn):
    if not (req.prompt or "").strip():
        raise HTTPException(400, "Task prompt is empty.")
    keys = _resolve_api_keys(req.api_keys)

    cfg = normalize_gen_config(req.config.model_dump())
    scan = scan_project(cfg)
    manifest, manifest_count = _build_manifest(scan)
    if not manifest_count:
        raise HTTPException(400, "No scannable files — check include rules and root path.")

    valid_paths = {item["path"] for item in scan["included"]}

    system_msg = (
        "You analyse a codebase and select exactly which files must be modified "
        "to fulfil a task. Output strict JSON only."
    )
    user_msg = (
        f"TASK:\n{req.prompt.strip()}\n\n"
        f"PROJECT FILES (path, size, first lines):\n\n{manifest}\n\n"
        f"Select files that MUST change to complete the task. "
        f"Return JSON: {{\"files\": [\"rel/path.ext\", ...], \"reasoning\": \"one sentence\"}}. "
        f"Rules: do not list files that only need inspection; do not list lockfiles "
        f"or vendored code; include any new files that must be created; max "
        f"{req.max_files} files; JSON only."
    )

    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    attempt_errors: List[str] = []
    data = None
    used_key_index = 0
    used_key_masked = ""

    with httpx.Client(timeout=AI_TIMEOUT) as client:
        for idx, key in enumerate(keys, start=1):
            masked = _mask_key(key)
            try:
                r = client.post(
                    f"{AI_API_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json=payload,
                )
            except httpx.HTTPError as e:
                attempt_errors.append(f"Key #{idx} ({masked}): network error ({e})")
                continue

            if r.status_code != 200:
                attempt_errors.append(f"Key #{idx} ({masked}): HTTP {r.status_code} ({r.text[:180]})")
                continue

            try:
                content = r.json()["choices"][0]["message"]["content"] or ""
                data = json.loads(content)
                used_key_index = idx
                used_key_masked = masked
                break
            except Exception as e:
                attempt_errors.append(f"Key #{idx} ({masked}): invalid JSON response ({e})")
                continue

    if data is None:
        raise HTTPException(
            502,
            "All Groq API keys failed:\n" + "\n".join(attempt_errors)
        )

    raw_files = data.get("files") or []
    files: List[str] = []
    for f in raw_files:
        if not isinstance(f, str):
            continue
        f = f.strip()
        if f in valid_paths and f not in files:
            files.append(f)
    files = files[: req.max_files]

    return {
        "files": files,
        "reasoning": str(data.get("reasoning", "")).strip(),
        "scanned": len(scan["included"]),
        "manifest_included": manifest_count,
        "key_used": f"Key #{used_key_index} ({used_key_masked})",
        "fallback_attempts": len(attempt_errors),
    }


@app.post("/api/ai/transcribe")
def api_ai_transcribe(
    audio: UploadFile = File(...),
    api_keys: Optional[str] = Form(None),
    save_prompt_history: Optional[str] = Form(None),
):
    try:
        content = audio.file.read()
    except Exception as e:
        raise HTTPException(400, f"Could not read uploaded audio: {e}")
    if not content:
        raise HTTPException(400, "Uploaded audio is empty.")

    filename = audio.filename or "voice.webm"
    content_type = audio.content_type or "audio/webm"

    # Always save the audio recording to disk immediately so it is never lost
    saved_recording = save_recording_bytes(content, filename)
    recording_url = f"/api/recordings/{saved_recording}"

    parsed_keys: List[str] = []
    if api_keys:
        try:
            raw_list = json.loads(api_keys)
            if isinstance(raw_list, list):
                parsed_keys = [str(x) for x in raw_list]
            else:
                parsed_keys = [str(api_keys)]
        except Exception:
            parsed_keys = [str(api_keys)]

    try:
        keys = _resolve_api_keys(parsed_keys)
    except HTTPException as exc:
        raise HTTPException(
            400,
            {
                "message": exc.detail,
                "recording_filename": saved_recording,
                "recording_url": recording_url,
            },
        )

    attempt_errors: List[str] = []
    transcribed_text: Optional[str] = None
    used_key_index = 0
    used_key_masked = ""

    with httpx.Client(timeout=AI_TIMEOUT) as client:
        for idx, key in enumerate(keys, start=1):
            masked = _mask_key(key)
            files = {"file": (filename, content, content_type)}
            data = {"model": AI_WHISPER_MODEL}
            try:
                r = client.post(
                    f"{AI_API_BASE}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {key}"},
                    files=files,
                    data=data,
                )
            except httpx.HTTPError as e:
                attempt_errors.append(f"Key #{idx} ({masked}): {e}")
                continue

            if r.status_code != 200:
                attempt_errors.append(f"Key #{idx} ({masked}): HTTP {r.status_code} ({r.text[:160]})")
                continue

            try:
                transcribed_text = (r.json().get("text") or "").strip()
                used_key_index = idx
                used_key_masked = masked
                break
            except Exception as e:
                attempt_errors.append(f"Key #{idx} ({masked}): parse error ({e})")
                continue

    if transcribed_text is None:
        raise HTTPException(
            502,
            {
                "message": "Whisper transcription failed across all Groq API keys: " + " | ".join(attempt_errors),
                "recording_filename": saved_recording,
                "recording_url": recording_url,
            },
        )

    return {
        "text": transcribed_text,
        "model": AI_WHISPER_MODEL,
        "recording_filename": saved_recording,
        "recording_url": recording_url,
        "key_used": f"Key #{used_key_index} ({used_key_masked})",
        "fallback_attempts": len(attempt_errors),
    }


@app.post("/api/gen/folder-contents")
def api_gen_folder_contents(req: FolderContentsIn):
    root = Path(req.root).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(400, "Invalid project root")
    try:
        folder = safe_join(root, req.path)
    except ValueError:
        raise HTTPException(400, "Path escapes project root")
    if not folder.is_dir():
        raise HTTPException(404, "Folder not found")

    files: List[dict] = []
    errors: List[str] = []
    try:
        for p in folder.rglob("*"):
            if p.is_file():
                try:
                    files.append({
                        "path": p.relative_to(root).as_posix(),
                        "size": p.stat().st_size,
                    })
                except Exception:
                    pass
            if len(files) >= 2000:
                errors.append("Listing truncated at 2000 files.")
                break
    except PermissionError as e:
        errors.append(f"Permission denied: {e}")
    except Exception as e:
        errors.append(str(e))

    files.sort(key=lambda x: x["path"])
    return {"files": files, "errors": errors}


# ---- Picker routes ---------------------------------------------

@app.post("/api/pick-folder")
def api_pick_folder(req: PickIn):
    path = _pick_path("folder", req.initial)
    rel = ""
    if path and req.base:
        try:
            rel = Path(path).resolve().relative_to(Path(req.base).expanduser().resolve()).as_posix()
        except Exception:
            rel = ""
    return {"path": path, "relative": rel}


@app.post("/api/pick-file")
def api_pick_file(req: PickIn):
    path = _pick_path("file", req.initial)
    rel = ""
    if path and req.base:
        try:
            rel = Path(path).resolve().relative_to(Path(req.base).expanduser().resolve()).as_posix()
        except Exception:
            rel = ""
    return {"path": path, "relative": rel}


# ---- Prompt history + fixed prompt routes ----------------------

@app.get("/api/prompts")
def api_prompts_list():
    store = load_prompt_store()
    items = sorted(store["items"], key=lambda x: x.get("rank", 0), reverse=True)
    return {"items": items, "next_rank": store["next_rank"]}


@app.post("/api/prompts")
def api_prompts_add(body: PromptSnapshotIn):
    if not body.custom_prompt or not body.custom_prompt.strip():
        raise HTTPException(400, "Custom prompt is empty.")
    if not body.combined_prompt or not body.combined_prompt.strip():
        raise HTTPException(400, "Combined prompt is empty.")
    rec_file = (body.recording_filename or "").strip() or None
    with _LOCK:
        store = load_prompt_store()
        rank = int(store.get("next_rank", 1))
        record = {
            "id": str(uuid.uuid4()),
            "rank": rank,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "custom_prompt": body.custom_prompt,
            "combined_prompt": body.combined_prompt,
            "char_count": len(body.combined_prompt),
            "recording_filename": rec_file,
            "recording_url": f"/api/recordings/{rec_file}" if rec_file else None,
        }
        store["items"].append(record)
        store["next_rank"] = rank + 1
        save_prompt_store(store)
    return {"ok": True, "item": record}


@app.get("/api/prompts/{prompt_id}")
def api_prompts_get(prompt_id: str):
    for item in load_prompt_store()["items"]:
        if item.get("id") == prompt_id:
            return item
    raise HTTPException(404, "Prompt not found")


@app.delete("/api/prompts/{prompt_id}")
def api_prompts_delete(prompt_id: str):
    with _LOCK:
        store = load_prompt_store()
        before = len(store["items"])
        store["items"] = [it for it in store["items"] if it.get("id") != prompt_id]
        if len(store["items"]) == before:
            raise HTTPException(404, "Prompt not found")
        save_prompt_store(store)
    return {"ok": True}


@app.get("/api/fixed-prompt")
def api_fixed_prompt_get():
    text = load_fixed_prompt()
    return {"text": text, "is_default": not FIXED_PROMPT_FILE.is_file() or text.strip() == DEFAULT_FIXED_PROMPT.strip()}


@app.post("/api/fixed-prompt")
def api_fixed_prompt_save(body: FixedPromptIn):
    if not body.text or not body.text.strip():
        raise HTTPException(400, "Fixed prompt cannot be empty.")
    save_fixed_prompt(body.text)
    return {"ok": True}


@app.post("/api/fixed-prompt/reset")
def api_fixed_prompt_reset():
    if FIXED_PROMPT_FILE.is_file():
        try:
            FIXED_PROMPT_FILE.unlink()
        except Exception as e:
            raise HTTPException(500, f"Could not delete stored fixed prompt: {e}")
    return {"ok": True, "text": DEFAULT_FIXED_PROMPT}


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    HOST = "127.0.0.1"
    PORT = 8009
    URL = f"http://{HOST}:{PORT}"

    ed_root = load_editor_root()

    print("=" * 52)
    print("AI MULTI-FILE EDITOR")
    print("=" * 52)
    print()
    print(f"Editor root: {ed_root}")
    print(f"Data dir:    {DATA_DIR}")
    print(f"Recordings:  {RECORDINGS_DIR}")
    print(f"Backups:     {ed_root / '.backup'}")
    print(f"AI provider: {AI_API_BASE} · model={AI_MODEL}")
    print(f"AI key set:  {'yes (env)' if AI_API_KEY else 'configure in Frontend UI or env'}")
    print(f"Web:         {URL}")
    print()

    if os.environ.get("AI_EDITOR_NO_BROWSER") != "1":
        threading.Timer(1.2, lambda: webbrowser.open(URL)).start()

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
