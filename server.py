#!/usr/bin/env python3
"""
Kindle Real-Time Monitoring Panel Server (server.py)
Zero third-party dependencies - Pure Python 3 standard library.
Safe read-only access to Token Monitor & Antigravity data.
"""

import os
import sys
import time
import json
import sqlite3
import subprocess
import re
import hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("KPANEL_PORT", 8765))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_INDEX = os.path.join(BASE_DIR, "static", "index.html")
CUSTOM_TASKS_FILE = os.path.join(BASE_DIR, "custom_tasks.json")

TOKEN_MONITOR_DIR = os.path.expanduser(os.environ.get("TOKEN_MONITOR_DIR", "~/Library/Application Support/Token Monitor"))
ANTIGRAVITY_DIR = os.path.expanduser(os.environ.get("ANTIGRAVITY_DIR", "~/.gemini/antigravity"))

DAILY_ARCHIVE_PATH = os.path.join(TOKEN_MONITOR_DIR, "daily-history-archive.json")
SESSION_SQLITE_PATH = os.path.join(TOKEN_MONITOR_DIR, "session-usage-archive.sqlite")
AG_SUMMARIES_DB = os.path.join(ANTIGRAVITY_DIR, "conversation_summaries.db")
AG_PRESENCE_DIR = os.path.join(ANTIGRAVITY_DIR, "presence")
AG_BRAIN_DIR = os.path.join(ANTIGRAVITY_DIR, "brain")

# In-memory sliding window for TPM calculation: list of (timestamp, total_tokens)
_TPM_HISTORY = []
_MAX_TPM_WINDOW_SEC = 180.0


def format_elapsed(seconds):
    """Format seconds into MM:SS or HH:MM:SS string."""
    seconds = int(max(0, seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def parse_iso_ts(ts_str):
    """Safely parse an ISO-like timestamp string to UTC epoch seconds."""
    if not ts_str:
        return 0.0
    try:
        s = ts_str.strip().replace("Z", "+00:00")
        if " " in s and "+" in s:
            # e.g. 2026-10-24 06:10:51.400901+00:00
            s = s.replace(" ", "T")
        dt = datetime.fromisoformat(s)
        return dt.timestamp()
    except Exception:
        return 0.0


def get_token_monitor_stats():
    """
    Read Token Monitor daily history archive JSON and session usage SQLite.
    Returns:
      today_summary: {tokens, cost, inputTokens, outputTokens, cacheReadTokens, messages}
      week_summary: {tokens, cost, inputTokens, outputTokens, cacheReadTokens, messages}
      tpm: int
      hourly_trend: list of {hour: str, tokens: int}
      top_models: list of {modelId, tokens, cost, inputTokens, outputTokens, cacheReadTokens}
      active_external_sessions: list of recent external client sessions (<600s)
    """
    global _TPM_HISTORY

    now = time.time()
    today_summary = {
        "tokens": 0,
        "cost": 0.0,
        "inputTokens": 0,
        "outputTokens": 0,
        "cacheReadTokens": 0,
        "messages": 0
    }
    week_summary = {
        "tokens": 0,
        "cost": 0.0,
        "inputTokens": 0,
        "outputTokens": 0,
        "cacheReadTokens": 0,
        "messages": 0
    }
    models_dict = {}
    hourly_buckets = {}
    active_external_sessions = []
    latest_timed_rate = 0.0

    # 1. Parse daily-history-archive.json
    daily_days = {}
    if os.path.exists(DAILY_ARCHIVE_PATH):
        try:
            with open(DAILY_ARCHIVE_PATH, "r", encoding="utf-8") as f:
                daily_data = json.load(f)
                daily_days = daily_data.get("days", {})
        except Exception as e:
            sys.stderr.write(f"[WARN] Error reading daily archive: {e}\n")

    sorted_dates = sorted(daily_days.keys())
    local_today = datetime.now().strftime("%Y-%m-%d")
    utc_today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    target_today_key = None
    if local_today in daily_days:
        target_today_key = local_today
    elif utc_today in daily_days:
        target_today_key = utc_today
    elif sorted_dates:
        target_today_key = sorted_dates[-1]

    # Calculate week total from last 7 days in daily archive
    week_keys = sorted_dates[-7:] if sorted_dates else []
    for d_key in week_keys:
        d_val = daily_days.get(d_key, {})
        obs = d_val.get("observations", {})
        obs_items = obs.values() if isinstance(obs, dict) else obs
        for item in obs_items:
            tok = int(item.get("tokens", 0) or 0)
            cost = float(item.get("cost", 0.0) or 0.0)
            out_t = int(item.get("outputTokens", 0) or 0)
            cache_t = int(item.get("cacheReadTokens", 0) or 0)
            inp_t = max(0, tok - out_t - cache_t)
            msgs = int(item.get("messages", 0) or 0)

            week_summary["tokens"] += tok
            week_summary["cost"] += cost
            week_summary["inputTokens"] += inp_t
            week_summary["outputTokens"] += out_t
            week_summary["cacheReadTokens"] += cache_t
            week_summary["messages"] += msgs

    # Extract today's base stats from daily archive
    if target_today_key and target_today_key in daily_days:
        d_val = daily_days[target_today_key]
        obs = d_val.get("observations", {})
        obs_items = obs.values() if isinstance(obs, dict) else obs
        for item in obs_items:
            tok = int(item.get("tokens", 0) or 0)
            cost = float(item.get("cost", 0.0) or 0.0)
            out_t = int(item.get("outputTokens", 0) or 0)
            cache_t = int(item.get("cacheReadTokens", 0) or 0)
            inp_t = max(0, tok - out_t - cache_t)
            msgs = int(item.get("messages", 0) or 0)
            m_id = item.get("modelId") or "unknown"

            today_summary["tokens"] += tok
            today_summary["cost"] += cost
            today_summary["inputTokens"] += inp_t
            today_summary["outputTokens"] += out_t
            today_summary["cacheReadTokens"] += cache_t
            today_summary["messages"] += msgs

            if m_id not in models_dict:
                models_dict[m_id] = {
                    "modelId": m_id,
                    "tokens": 0,
                    "cost": 0.0,
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "cacheReadTokens": 0
                }
            models_dict[m_id]["tokens"] += tok
            models_dict[m_id]["cost"] += cost
            models_dict[m_id]["inputTokens"] += inp_t
            models_dict[m_id]["outputTokens"] += out_t
            models_dict[m_id]["cacheReadTokens"] += cache_t

    # 2. Parse session-usage-archive.sqlite (read-only)
    if os.path.exists(SESSION_SQLITE_PATH):
        try:
            conn = sqlite3.connect(f"file:{SESSION_SQLITE_PATH}?mode=ro", uri=True, timeout=2.0)
            c = conn.cursor()
            c.execute("SELECT revision, entry_json FROM sessions ORDER BY revision DESC")
            rows = c.fetchall()
            conn.close()

            s_tokens = 0
            s_cost = 0.0
            s_input = 0
            s_output = 0
            s_cache = 0
            s_msgs = 0
            session_models = {}

            # Prepare 12 hour bucket keys
            for h in range(11, -1, -1):
                dt_hour = datetime.now() - timedelta(hours=h)
                hourly_buckets[dt_hour.strftime("%H:00")] = 0

            for rev, entry_json in rows:
                try:
                    entry = json.loads(entry_json)
                except Exception:
                    continue

                client = entry.get("client", "")
                session_id = entry.get("sessionId", "")
                captured_at = entry.get("capturedAt", "")
                cap_ts = parse_iso_ts(captured_at)
                age_sec = now - cap_ts if cap_ts > 0 else 999999

                today_p = entry.get("periods", {}).get("today", {})
                tok = int(today_p.get("totalTokens", 0) or 0)
                cost = float(today_p.get("costUsd", 0.0) or 0.0)
                inp = int(today_p.get("inputTokens", 0) or 0)
                out = int(today_p.get("outputTokens", 0) or 0)
                cache_r = int(today_p.get("cacheReadTokens", 0) or 0)
                msgs = int(today_p.get("messageCount", 0) or 0)

                s_tokens += tok
                s_cost += cost
                s_input += inp
                s_output += out
                s_cache += cache_r
                s_msgs += msgs

                # Hourly bucketing (past 12h)
                if cap_ts > 0 and age_sec <= 43200:
                    dt_cap = datetime.fromtimestamp(cap_ts)
                    h_key = dt_cap.strftime("%H:00")
                    if h_key in hourly_buckets:
                        hourly_buckets[h_key] += tok

                # Check for timed rate estimate for TPM fallback
                timed_dur = float(today_p.get("timedDurationMs", 0) or 0)
                timed_out = float(today_p.get("timedOutputTokens", 0) or 0)
                if age_sec < 600 and timed_dur > 1000 and timed_out > 0:
                    cand_rate = (timed_out / (timed_dur / 1000.0)) * 60.0
                    if cand_rate > latest_timed_rate:
                        latest_timed_rate = cand_rate

                # Track models in live sessions
                for m_id, m_tok in today_p.get("models", {}).items():
                    m_tok = int(m_tok or 0)
                    m_cost = float(today_p.get("modelCosts", {}).get(m_id, 0.0) or 0.0)
                    if m_id not in session_models:
                        session_models[m_id] = {"tokens": 0, "cost": 0.0}
                    session_models[m_id]["tokens"] += m_tok
                    session_models[m_id]["cost"] += m_cost

                # Channel 2: External client active sessions (<600s)
                if client and client.lower() != "antigravity" and age_sec < 600:
                    project_label = today_p.get("projectLabel") or entry.get("projectLabel") or f"{client} Task"
                    active_external_sessions.append({
                        "id": f"tm_{session_id[:12]}",
                        "client": client,
                        "project": project_label,
                        "tokens": tok,
                        "messages": msgs,
                        "age_sec": age_sec,
                        "startedAt": today_p.get("startedAt") or captured_at
                    })

            # Real-time calibration: if session today tokens exceeds daily archive
            if s_tokens > today_summary["tokens"]:
                delta = s_tokens - today_summary["tokens"]
                prev_today_cost = today_summary["cost"]
                today_summary["tokens"] = s_tokens
                today_summary["cost"] = s_cost
                today_summary["inputTokens"] = s_input
                today_summary["outputTokens"] = s_output
                today_summary["cacheReadTokens"] = s_cache
                today_summary["messages"] = s_msgs
                week_summary["tokens"] += delta
                week_summary["cost"] += max(0.0, s_cost - prev_today_cost)

            # Merge live session models into models_dict
            for m_id, sm in session_models.items():
                if m_id not in models_dict:
                    models_dict[m_id] = {
                        "modelId": m_id,
                        "tokens": sm["tokens"],
                        "cost": sm["cost"],
                        "inputTokens": max(0, sm["tokens"] - int(sm["tokens"] * 0.1)),
                        "outputTokens": int(sm["tokens"] * 0.1),
                        "cacheReadTokens": 0
                    }
                else:
                    if sm["tokens"] > models_dict[m_id]["tokens"]:
                        models_dict[m_id]["tokens"] = sm["tokens"]
                        models_dict[m_id]["cost"] = max(models_dict[m_id]["cost"], sm["cost"])

        except Exception as e:
            sys.stderr.write(f"[WARN] Error reading session SQLite: {e}\n")

    # 3. Real-time TPM Calculation (Sliding window 180s)
    current_tokens = today_summary["tokens"]
    _TPM_HISTORY = [(ts, tok) for ts, tok in _TPM_HISTORY if (now - ts) <= _MAX_TPM_WINDOW_SEC]
    _TPM_HISTORY.append((now, current_tokens))

    calculated_tpm = 0
    if len(_TPM_HISTORY) >= 2:
        oldest_ts, oldest_tok = _TPM_HISTORY[0]
        latest_ts, latest_tok = _TPM_HISTORY[-1]
        dt = latest_ts - oldest_ts
        d_tokens = latest_tok - oldest_tok
        if dt >= 8.0 and d_tokens >= 0:
            calculated_tpm = int((d_tokens / dt) * 60.0)

    if calculated_tpm == 0 and latest_timed_rate > 0:
        # Fallback to recent active session timed rate (estimated total ~ 5x output rate)
        calculated_tpm = int(latest_timed_rate * 5.0)

    # 4. Top 6 Models Ranking
    top_models = sorted(models_dict.values(), key=lambda x: x["tokens"], reverse=True)[:6]
    for m in top_models:
        m["cost"] = round(m["cost"], 4)

    # Format hourly trend list
    trend_list = [{"hour": k, "tokens": v} for k, v in hourly_buckets.items()]

    return (
        today_summary,
        week_summary,
        calculated_tpm,
        trend_list,
        top_models,
        active_external_sessions
    )


def scan_local_scripts():
    """
    Channel 3: Scan running local user scripts via ps -axo pid,etime,command.
    Excludes internal Chrome/esbuild helper subprocesses.
    Returns list of matched task dicts.
    """
    matched = []
    keywords = [
        "scrape_", "remotion render", "hyperframes",
        "flow_automation", "ffmpeg", "camoufox"
    ]
    seen_titles = set()
    try:
        proc = subprocess.run(
            ["ps", "-axo", "pid,etime,command"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2.0
        )
        for line in proc.stdout.splitlines()[1:]:
            parts = line.strip().split(None, 2)
            if len(parts) < 3:
                continue
            pid_str, etime, cmd = parts[0], parts[1], parts[2]
            # Exclude server.py, kpanel, ps, grep, chrome-headless-shell, esbuild, help/version checks
            if any(x in cmd for x in ["server.py", "kpanel", "grep", "ps -axo", "chrome-headless-shell", "--type=", "esbuild", "--help", "--version"]):
                continue
            for kw in keywords:
                if kw in cmd:
                    script_name = kw
                    match_py = re.search(r"([\w\-]+\.(?:py|js|ts|sh))", cmd)
                    if match_py:
                        script_name = match_py.group(1)
                    elif "hyperframes" in cmd:
                        script_name = "hyperframes"
                    elif "remotion render" in cmd:
                        script_name = "remotion render"

                    # Deduplicate multiple instances of background workers
                    if script_name in seen_titles:
                        continue
                    seen_titles.add(script_name)

                    matched.append({
                        "id": f"ps_{pid_str}",
                        "source": "Script",
                        "title": script_name,
                        "status": "RUNNING",
                        "pct": 50,
                        "blocks": 6,
                        "step_text": f"PID {pid_str}",
                        "detail": cmd[:45].strip(),
                        "elapsed": etime.strip()
                    })
                    break
    except Exception as e:
        sys.stderr.write(f"[WARN] Error scanning local script processes: {e}\n")
    return matched[:3]


def get_custom_tasks():
    """
    Channel 4: Read and filter custom reported tasks from custom_tasks.json.
    """
    tasks = []
    if not os.path.exists(CUSTOM_TASKS_FILE):
        return tasks

    now = time.time()
    valid_tasks = []
    changed = False

    try:
        with open(CUSTOM_TASKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                data = []
    except Exception:
        data = []

    for item in data:
        updated_at = float(item.get("updated_at", now))
        ttl = float(item.get("ttl", 3600))
        status = item.get("status", "RUNNING")
        if (now - updated_at) > ttl or status == "DONE":
            changed = True
            continue

        valid_tasks.append(item)

        pct = int(item.get("pct", 50))
        blocks = int(round(pct * 12.0 / 100.0))
        step_text = item.get("step_text") or (f"{item.get('step')}/{item.get('total')}" if "step" in item and "total" in item else f"{pct}%")
        elapsed_sec = now - float(item.get("created_at", updated_at))

        tasks.append({
            "id": item.get("id") or f"custom_{item.get('title', 'task')[:10]}",
            "source": item.get("source") or "Custom",
            "title": item.get("title") or "Custom Task",
            "status": status,
            "pct": max(0, min(100, pct)),
            "blocks": max(0, min(12, blocks)),
            "step_text": step_text,
            "detail": item.get("detail", ""),
            "elapsed": format_elapsed(elapsed_sec)
        })

    if changed:
        try:
            with open(CUSTOM_TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(valid_tasks, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    return tasks


def get_all_inflight_tasks(active_external_sessions):
    """
    Aggregate all 4 channels of in-flight tasks:
    1. Antigravity main & subagents
    2. Token Monitor active external sessions
    3. Local long-running scripts (ps)
    4. Custom reported tasks
    Fallback: 1-2 recent completed/idle AGY tasks if no running tasks.
    """
    now = time.time()
    tasks = []
    recent_idle_agy = []

    # 1. Antigravity Tasks
    if os.path.exists(AG_SUMMARIES_DB):
        try:
            conn = sqlite3.connect(f"file:{AG_SUMMARIES_DB}?mode=ro", uri=True, timeout=2.0)
            c = conn.cursor()
            c.execute("""
                SELECT conversation_id, parent_conversation_id, title, step_count, status, not_fully_idle, last_modified_time, last_user_input_time
                FROM conversation_summaries
                ORDER BY last_modified_time DESC LIMIT 15
            """)
            rows = c.fetchall()
            conn.close()

            for r in rows:
                cid, pid, title, step_count, status_str, not_idle, lmt_str, luit_str = r
                step_count = int(step_count or 0)
                lmt_ts = parse_iso_ts(lmt_str)
                # Active only if status is explicitly RUNNING or not_fully_idle == 1 (and modified within last 6 hours)
                is_running = (
                    (status_str == "CASCADE_RUN_STATUS_RUNNING" or not_idle == 1)
                    and (lmt_ts == 0 or (now - lmt_ts) < 21600)
                )

                clean_title = (title or "").strip() or f"Session {cid[:8]}"
                source_label = "AGY·主控" if (not pid or pid.strip() == "") else "AGY·子代理"

                # Parse elapsed
                start_ts = parse_iso_ts(luit_str) or parse_iso_ts(lmt_str)
                elapsed_str = format_elapsed(now - start_ts) if start_ts > 0 else "00:00"

                # Check task.md inside brain/<cid>/task.md
                task_md_path = os.path.join(AG_BRAIN_DIR, cid, "task.md")
                has_task_md = False
                pct = 0
                step_text = f"Step {step_count}"

                if os.path.exists(task_md_path):
                    try:
                        with open(task_md_path, "r", encoding="utf-8") as f_md:
                            md_content = f_md.read()
                            checked = md_content.count("- [x]")
                            in_prog = md_content.count("- [/]")
                            unchecked = md_content.count("- [ ]")
                            total_items = checked + in_prog + unchecked
                            if total_items > 0:
                                has_task_md = True
                                pct = int(round(100.0 * (checked + 0.5 * in_prog) / total_items))
                                step_text = f"{checked}/{total_items}"
                    except Exception:
                        pass

                if not has_task_md:
                    pct = min(92, 15 + (step_count % 80))

                blocks = max(0, min(12, int(round(pct * 12.0 / 100.0))))

                task_obj = {
                    "id": f"agy_{cid[:8]}",
                    "source": source_label,
                    "title": clean_title,
                    "status": "RUNNING" if is_running else "IDLE_RECENT",
                    "pct": max(0, min(100, pct)),
                    "blocks": blocks,
                    "step_text": step_text,
                    "detail": f"Step {step_count} · {clean_title[:30]}",
                    "elapsed": elapsed_str
                }

                if is_running:
                    tasks.append(task_obj)
                else:
                    if len(recent_idle_agy) < 2:
                        task_obj["status"] = "IDLE_RECENT"
                        task_obj["pct"] = 100
                        task_obj["blocks"] = 12
                        task_obj["detail"] = "已完成 / 最近待命"
                        recent_idle_agy.append(task_obj)

        except Exception as e:
            sys.stderr.write(f"[WARN] Error reading AG conversation summaries: {e}\n")

    # 2. Token Monitor External Active Sessions
    for sess in active_external_sessions:
        c_name = sess["client"].capitalize()
        tok = sess["tokens"]
        msgs = sess["messages"]
        pct = min(90, 15 + msgs * 5)
        blocks = max(0, min(12, int(round(pct * 12.0 / 100.0))))
        tasks.append({
            "id": sess["id"],
            "source": c_name,
            "title": sess["project"][:32],
            "status": "RUNNING",
            "pct": pct,
            "blocks": blocks,
            "step_text": f"Msg {msgs}",
            "detail": f"{tok:,} tok · {msgs} msgs",
            "elapsed": format_elapsed(sess["age_sec"])
        })

    # 3. Local Script Processes
    tasks.extend(scan_local_scripts())

    # 4. Custom Reported Tasks
    tasks.extend(get_custom_tasks())

    # Fallback: if no running tasks at all, show 1-2 recent completed AGY sessions
    if not tasks and recent_idle_agy:
        tasks.extend(recent_idle_agy)

    # Sort tasks by priority:
    # 0: APPROVAL
    # 1: AGY Main / Subagent
    # 2: External TM clients (Devin, Claude, etc.)
    # 3: Custom
    # 4: Script
    # 5: IDLE_RECENT
    def task_sort_key(t):
        status = t.get("status", "")
        src = t.get("source", "")
        if status == "APPROVAL":
            return (0, t.get("id"))
        if src.startswith("AGY"):
            return (1, 0 if "主控" in src else 1, t.get("id"))
        if src in ("Devin", "Claude", "Codex", "OpenCode"):
            return (2, t.get("id"))
        if src == "Custom":
            return (3, t.get("id"))
        if src == "Script":
            return (4, t.get("id"))
        return (5, t.get("id"))

    tasks.sort(key=task_sort_key)
    return tasks


def get_ui_version():
    """Return mtime timestamp of STATIC_INDEX for dynamic hot-reload detection."""
    try:
        return str(int(os.path.getmtime(STATIC_INDEX)))
    except Exception:
        return "1"


def compute_state_hash(today, week, tpm, models, tasks, ui_version=""):
    """
    Compute a short hash of core business state, deliberately excluding second-level clock ticks.
    Enables HTTP 304 Not Modified to keep Kindle e-ink screen at zero repaints when idle.
    Uses tpm // 1000 to prevent minute idle fluctuations from busting 304 cache.
    Includes ui_version so frontend hot reloads immediately when static/index.html updates.
    """
    parts = [
        str(today.get("tokens", 0)),
        str(round(today.get("cost", 0.0), 2)),
        str(today.get("inputTokens", 0)),
        str(today.get("outputTokens", 0)),
        str(week.get("tokens", 0)),
        str(int(tpm) // 1000),
        str(len(tasks)),
        str(ui_version)
    ]
    for t in tasks:
        parts.append(f"{t.get('id')}:{t.get('status')}:{t.get('pct')}:{t.get('blocks')}:{t.get('step_text')}")
    for m in models:
        parts.append(f"{m.get('modelId')}:{m.get('tokens')}")

    raw = "|".join(parts)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


class KindlePanelHandler(BaseHTTPRequestHandler):
    server_version = "KindlePanelServer/1.0"

    def do_HEAD(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        elif path in ("/", "/index.html"):
            if not os.path.exists(STATIC_INDEX):
                self.send_error(404, "static/index.html not found")
                return
            try:
                size = os.path.getsize(STATIC_INDEX)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.end_headers()
            except Exception as e:
                self.send_error(500, f"Error reading index.html: {e}")
        elif path == "/api/state":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
        else:
            self.send_error(404, "Not Found")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        elif path in ("/", "/index.html"):
            self.handle_index()
        elif path == "/api/state":
            self.handle_api_state(parsed)
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/task":
            self.handle_post_task()
        else:
            self.send_error(404, "Not Found")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/task":
            self.handle_delete_task(parsed)
        else:
            self.send_error(404, "Not Found")

    def handle_index(self):
        if not os.path.exists(STATIC_INDEX):
            self.send_error(404, "static/index.html not found")
            return
        try:
            with open(STATIC_INDEX, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Error reading index.html: {e}")

    def handle_api_state(self, parsed):
        query = parse_qs(parsed.query)
        client_hash = query.get("hash", [None])[0]

        (
            today_summary,
            week_summary,
            tpm,
            trend_list,
            top_models,
            active_external_sessions
        ) = get_token_monitor_stats()

        inflight_tasks = get_all_inflight_tasks(active_external_sessions)
        ui_version = get_ui_version()
        state_hash = compute_state_hash(today_summary, week_summary, tpm, top_models, inflight_tasks, ui_version)

        # 304 Not Modified if hash matches
        if client_hash and client_hash == state_hash:
            self.send_response(304)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return

        payload = {
            "state_hash": state_hash,
            "ui_version": ui_version,
            "server_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "summary": {
                "today": today_summary,
                "week": week_summary,
                "tpm": tpm,
                "trend": trend_list
            },
            "models": top_models,
            "inflight_tasks": inflight_tasks
        }

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def handle_post_task(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(raw_body)
        except Exception as e:
            self.send_error(400, f"Invalid JSON body: {e}")
            return

        title = str(data.get("title", "")).strip()
        if not title:
            self.send_error(400, "Missing title")
            return

        now = time.time()
        task_id = data.get("id") or f"custom_{re.sub(r'[^a-zA-Z0-9]', '_', title)[:16]}"
        status = data.get("status", "RUNNING")
        source = data.get("source", "Custom")
        detail = str(data.get("detail", ""))
        ttl = float(data.get("ttl", 3600))

        step = data.get("step")
        total = data.get("total")
        pct = data.get("pct")

        if step is not None and total is not None and int(total) > 0:
            step = int(step)
            total = int(total)
            pct = int(round(100.0 * step / total))
            step_text = f"{step}/{total}"
        elif pct is not None:
            pct = int(pct)
            step_text = f"{pct}%"
        else:
            pct = 50
            step_text = "Running"

        pct = max(0, min(100, pct))
        blocks = max(0, min(12, int(round(pct * 12.0 / 100.0))))

        # Read existing custom tasks
        tasks = []
        if os.path.exists(CUSTOM_TASKS_FILE):
            try:
                with open(CUSTOM_TASKS_FILE, "r", encoding="utf-8") as f:
                    tasks = json.load(f)
                    if not isinstance(tasks, list):
                        tasks = []
            except Exception:
                tasks = []

        # Preserve created_at if updating an existing custom task
        prev_created_at = now
        for t in tasks:
            if t.get("id") == task_id or t.get("title") == title:
                prev_created_at = float(t.get("created_at", now))
                break

        # Remove existing if matching id or title, or if status == DONE
        tasks = [t for t in tasks if t.get("id") != task_id and t.get("title") != title]

        saved_item = None
        if status != "DONE":
            saved_item = {
                "id": task_id,
                "source": source,
                "title": title,
                "status": status,
                "pct": pct,
                "blocks": blocks,
                "step": step,
                "total": total,
                "step_text": step_text,
                "detail": detail,
                "ttl": ttl,
                "created_at": prev_created_at,
                "updated_at": now
            }
            tasks.append(saved_item)

        try:
            with open(CUSTOM_TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(tasks, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.send_error(500, f"Failed saving task: {e}")
            return

        res = {"success": True, "task": saved_item}
        body = json.dumps(res, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_delete_task(self, parsed):
        query = parse_qs(parsed.query)
        task_id = query.get("id", [None])[0]
        title = query.get("title", [None])[0]

        if not task_id and not title:
            self.send_error(400, "Missing id or title query parameter")
            return

        tasks = []
        if os.path.exists(CUSTOM_TASKS_FILE):
            try:
                with open(CUSTOM_TASKS_FILE, "r", encoding="utf-8") as f:
                    tasks = json.load(f)
                    if not isinstance(tasks, list):
                        tasks = []
            except Exception:
                tasks = []

        before_len = len(tasks)
        tasks = [t for t in tasks if t.get("id") != task_id and t.get("title") != title]

        try:
            with open(CUSTOM_TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(tasks, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.send_error(500, f"Failed updating task file: {e}")
            return

        res = {"success": True, "deleted": before_len - len(tasks)}
        body = json.dumps(res, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Concise logging to stdout
        sys.stdout.write(f"[{datetime.now().strftime('%H:%M:%S')}] {self.address_string()} - {format % args}\n")
        sys.stdout.flush()


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def run_server():
    server_address = ("0.0.0.0", PORT)
    httpd = ReusableThreadingHTTPServer(server_address, KindlePanelHandler)
    print(f"==================================================")
    print(f"  Kindle Real-Time Monitoring Panel Server")
    print(f"  Listening on: http://0.0.0.0:{PORT}")
    print(f"  PID: {os.getpid()}")
    print(f"==================================================")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server gracefully...")
        httpd.server_close()


if __name__ == "__main__":
    run_server()
