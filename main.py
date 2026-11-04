import hashlib
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent

# --- AI provider (Groq / OpenAI-compatible, configured via Vercel Env Vars or Frontend Keys) ---
AI_API_BASE = os.environ.get("AI_API_BASE", "https://api.groq.com/openai/v1").rstrip("/")
AI_API_KEY = (
    os.environ.get("GROQ_API_KEY", "")
    or os.environ.get("AI_API_KEY", "")
    or os.environ.get("GROK_API_KEY", "")
    or os.environ.get("XAI_API_KEY", "")
)
AI_MODEL = os.environ.get("AI_MODEL", "openai/gpt-oss-120b")
AI_WHISPER_MODEL = os.environ.get("AI_WHISPER_MODEL", "whisper-large-v3")
AI_TIMEOUT = float(os.environ.get("AI_TIMEOUT", "55"))

# --- Fixed prompt defaults ------------------------------------------------

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

app = FastAPI(title="AI Multi-File Editor (Serverless)")


# ============================================================
# Small pure helpers (no local filesystem dependency)
# ============================================================

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_rel_path(raw: str) -> str:
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

    parts: List[str] = []
    for part in normalised.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise HTTPException(
                status_code=400,
                detail=f"Path escapes the project root and was rejected: {raw}",
            )
        parts.append(part)

    if not parts:
        raise HTTPException(status_code=400, detail=f"Invalid path: {raw}")
    if parts[0] == ".backup":
        raise HTTPException(
            status_code=400,
            detail=f"Paths inside .backup are not allowed: {raw}",
        )
    return "/".join(parts)


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
    if not isinstance(data, dict):
        return dict(DEFAULT_GEN_CONFIG)
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
    source_files: Dict[str, Optional[str]] = {}


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


class ManifestItemIn(BaseModel):
    path: str
    size: int = 0
    head: str = ""


class AnalyzeIn(BaseModel):
    prompt: str
    manifest_items: List[ManifestItemIn] = []
    scanned_count: int = 0
    max_files: int = 50
    api_keys: List[str] = []


class FixedPromptIn(BaseModel):
    text: str


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


def _disambiguate(
    positions: List[int],
    match_len: int,
    hint: Optional[Tuple[int, int]],
) -> Optional[int]:
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
                raise HTTPException(
                    400,
                    f"Op #{idx+1} REPLACE: match ambiguous ({len(positions)} occurrences); provide accurate @@LINES",
                )
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
                    f"conflicts with {e2['type']} lines {e2['line_start']}-{e2['line_end']}",
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
# Stateless Check / Patch Verification
# ============================================================

def _resolve_check_stateless(req: FilesIn) -> dict:
    # Normalize source_files keys provided by the browser workspace
    norm_sources: Dict[str, Optional[str]] = {}
    for k, v in (req.source_files or {}).items():
        try:
            nk = normalize_rel_path(k)
            norm_sources[nk] = v
        except Exception:
            pass

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
            rel = normalize_rel_path(key)
        except HTTPException as exc:
            _fail(str(key), exc.detail)
            continue
        try:
            old = norm_sources.get(rel)
            exists = old is not None
            if exists:
                status = "unchanged" if old == content else "modified"
            else:
                status = "new"
            _add({
                "path": rel,
                "mode": "legacy",
                "status": status,
                "old": old if status == "modified" else None,
                "new": content,
                "old_hash": sha256(old) if exists else None,
                "changes": [],
            })
        except Exception as exc:
            _fail(key, exc)

    for entry in (req.ops or []):
        try:
            rel = normalize_rel_path(entry.path)
        except HTTPException as exc:
            _fail(entry.path, exc.detail)
            continue

        mode = (entry.mode or "").lower()
        try:
            old = norm_sources.get(rel)
            exists = old is not None

            if mode == "full":
                content = entry.content if entry.content is not None else ""
                if exists:
                    status = "unchanged" if old == content else "modified"
                else:
                    status = "new"
                _add({
                    "path": rel,
                    "mode": "full",
                    "status": status,
                    "old": old if status == "modified" else None,
                    "new": content,
                    "old_hash": sha256(old) if exists else None,
                    "changes": [],
                })

            elif mode == "delete":
                if not exists:
                    raise HTTPException(400, f"Cannot delete {rel}: file does not exist in loaded project")
                _add({
                    "path": rel,
                    "mode": "delete",
                    "status": "deleted",
                    "old": old,
                    "new": None,
                    "old_hash": sha256(old),
                    "changes": [{
                        "type": "delete_file",
                        "old": old,
                        "new": "",
                        "line_start": 1,
                        "line_end": max(1, old.count("\n")),
                    }],
                })

            elif mode == "patch":
                if not exists:
                    raise HTTPException(
                        400,
                        f"Cannot patch {rel}: file does not exist in loaded project (use @@FULL to create new files)",
                    )
                new_content, changes = resolve_patch(old, entry.operations)
                status = "unchanged" if new_content == old else "modified"
                _add({
                    "path": rel,
                    "mode": "patch",
                    "status": status,
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

    return {"files": results, "errors": errors}


# ============================================================
# AI provider helpers (Multi-key fallback + Vercel Env Vars)
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
            "No Groq API keys configured. Add Groq API key(s) in the top bar or set GROQ_API_KEY / AI_API_KEY in Vercel Environment Variables.",
        )
    return keys


def _mask_key(k: str) -> str:
    if len(k) <= 10:
        return "***"
    return f"{k[:6]}…{k[-4:]}"


def _build_manifest_from_items(items: List[ManifestItemIn]) -> Tuple[str, int]:
    MAX_TOTAL = 22_000
    MAX_HEAD_LINES = 30
    MAX_PER_FILE = 1_000
    out: List[str] = []
    total = 0
    count = 0
    for item in items:
        rel = item.path.strip().lstrip("/")
        if not rel:
            continue
        head_lines = (item.head or "").splitlines()[:MAX_HEAD_LINES]
        head = "\n".join(head_lines)[:MAX_PER_FILE]
        block = f"=== {rel} ({item.size} B) ===\n{head}\n"
        if total + len(block) > MAX_TOTAL:
            rem_block = f"=== {rel} ({item.size} B) ===\n"
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
    index_path = BASE_DIR / "index.html"
    if index_path.is_file():
        return FileResponse(index_path)
    return HTMLResponse("<h1>AI Multi-File Editor</h1><p>index.html not found.</p>", status_code=404)


@app.get("/api/health")
def api_health():
    return {
        "ok": True,
        "has_server_key": bool(AI_API_KEY),
        "model": AI_MODEL,
        "whisper_model": AI_WHISPER_MODEL,
    }


@app.get("/api/gen/config")
def api_gen_config_get():
    return {"config": dict(DEFAULT_GEN_CONFIG), "defaults": DEFAULT_GEN_CONFIG}


@app.post("/api/gen/config")
def api_gen_config_save(cfg: GenConfigIn):
    norm = normalize_gen_config(cfg.model_dump())
    return {"ok": True, "config": norm}


@app.post("/api/check")
def api_check(req: FilesIn):
    return _resolve_check_stateless(req)


@app.post("/api/ai/analyze")
def api_ai_analyze(req: AnalyzeIn):
    if not (req.prompt or "").strip():
        raise HTTPException(400, "Task prompt is empty.")
    if not req.manifest_items:
        raise HTTPException(400, "No scanned project files provided. Load a project folder or ZIP and scan first.")

    keys = _resolve_api_keys(req.api_keys)
    manifest, manifest_count = _build_manifest_from_items(req.manifest_items)
    if not manifest_count:
        raise HTTPException(400, "No scannable files in manifest.")

    valid_paths = {item.path.strip().lstrip("/") for item in req.manifest_items if item.path.strip()}

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
            "All Groq API keys failed:\n" + "\n".join(attempt_errors),
        )

    raw_files = data.get("files") or []
    files: List[str] = []
    for f in raw_files:
        if not isinstance(f, str):
            continue
        f_clean = f.strip().lstrip("/")
        if f_clean in valid_paths and f_clean not in files:
            files.append(f_clean)
    files = files[: req.max_files]

    return {
        "files": files,
        "reasoning": str(data.get("reasoning", "")).strip(),
        "scanned": req.scanned_count or len(req.manifest_items),
        "manifest_included": manifest_count,
        "key_used": f"Key #{used_key_index} ({used_key_masked})",
        "fallback_attempts": len(attempt_errors),
    }


@app.post("/api/ai/transcribe")
def api_ai_transcribe(
    audio: UploadFile = File(...),
    api_keys: Optional[str] = Form(None),
):
    try:
        content = audio.file.read()
    except Exception as e:
        raise HTTPException(400, f"Could not read uploaded audio: {e}")
    if not content:
        raise HTTPException(400, "Uploaded audio is empty.")

    filename = audio.filename or "voice.webm"
    content_type = audio.content_type or "audio/webm"

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

    keys = _resolve_api_keys(parsed_keys)

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
            "Whisper transcription failed across all Groq API keys: " + " | ".join(attempt_errors),
        )

    return {
        "text": transcribed_text,
        "model": AI_WHISPER_MODEL,
        "key_used": f"Key #{used_key_index} ({used_key_masked})",
        "fallback_attempts": len(attempt_errors),
    }


@app.get("/api/fixed-prompt")
def api_fixed_prompt_get():
    return {"text": DEFAULT_FIXED_PROMPT, "is_default": True}


@app.post("/api/fixed-prompt")
def api_fixed_prompt_save(body: FixedPromptIn):
    if not body.text or not body.text.strip():
        raise HTTPException(400, "Fixed prompt cannot be empty.")
    return {"ok": True}


@app.post("/api/fixed-prompt/reset")
def api_fixed_prompt_reset():
    return {"ok": True, "text": DEFAULT_FIXED_PROMPT}