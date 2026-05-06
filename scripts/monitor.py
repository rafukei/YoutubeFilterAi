#!/usr/bin/env python3
"""
YoutubeFilterAi Monitor — Tarkkailee bugeja ja raportoi Telegramiin.

Tämä skripti:
1. Jäsentää Docker-lokit tunnettuja virhekaavoja vasten (known_bugs.md)
2. Tarkistaa konttien terveyden
3. Suorittaa TURVALLISIA itseparannustoimia (stuck retry counterit)
4. Raportoi Telegramiin kun jotain huomionarvoista tapahtuu

Käyttö:
    python3 scripts/monitor.py [--dry-run] [--verbose]

--dry-run: Ei tee muutoksia, vain raportoi
--verbose: Näyttää kaikki lokirivit (ei vain virheet)
"""

import re
import subprocess
import sys
import time
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

# ── Polut ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent
BUGS_DOC = PROJECT_DIR / "docs" / "known_bugs.md"
COMPOSE_PATH = PROJECT_DIR / "docker-compose.yml"

# Oletusarvot (voidaan ylikirjoittaa ympäristöstä)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
BACKEND_CONTAINER = "youtubefilterai-backend-1"
DB_CONTAINER = "youtubefilterai-db-1"
REDIS_CONTAINER = "youtubefilterai-redis-1"

DRY_RUN = "--dry-run" in sys.argv
VERBOSE = "--verbose" in sys.argv

# ── Tunnetut virhekaavat (päivitä known_bugs.md rinnalla) ─────────────────────
# Muoto: (pattern, bug_id, severity, description)
ERROR_PATTERNS = [
    # BUG-001 related — infinite retry loop
    (
        r"Transcript fetch failed for .+ \(attempt \d+/\d+\)",
        "BUG-001",
        "WARNING",
        "Transcript retry happening — may indicate stuck channel"
    ),
    (
        r"Giving up on video .+ after \d+ failed attempts",
        "BUG-001-RECOVERED",
        "INFO",
        "Channel recovered from stuck video (gave up after max retries)"
    ),
    # IP block
    (
        r"⚠ IP blocked for channel",
        "IP-BLOCK",
        "WARNING",
        "YouTube IP block detected — scheduler may slow down"
    ),
    (
        r"🔒 IP block threshold .+ reached",
        "IP-BLOCK-CRITICAL",
        "ALERT",
        "Multiple IP blocks — scheduler paused"
    ),
    # BUG-006 — scheduler crash
    (
        r"Scheduler loop error",
        "SCHEDULER-CRASH",
        "ERROR",
        "Scheduler crashed — checking if container is healthy"
    ),
    # AI errors
    (
        r"AI query failed for video",
        "AI-FAILURE",
        "WARNING",
        "AI query failed for a video — check API key and rate limits"
    ),
    # Telegram errors
    (
        r"Failed to send via bot",
        "TELEGRAM-FAILURE",
        "WARNING",
        "Telegram send failed — check bot token and chat_id"
    ),
    # OOM / container restarts
    (
        r"Killed",
        "OOM-KILL",
        "ALERT",
        "Container was OOM-killed — check memory limits"
    ),
    # Database errors
    (
        r"IntegrityError",
        "DB-INTEGRITY",
        "ERROR",
        "Database integrity error — may indicate duplicate processing"
    ),
    # Greenlet error (BUG-007)
    (
        r"MissingGreenletError",
        "GREENLET-ERROR",
        "ERROR",
        "ORM lazy-load after rollback — bug in scheduler"
    ),
    # 503 OpenRouter
    (
        r"503",
        "OPENROUTER-503",
        "WARNING",
        "OpenRouter 503 — capacity issue, should retry with fallback"
    ),
    # Transcript unavailable
    (
        r"no subtitles found",
        "NO-SUBTITLES",
        "INFO",
        "Video has no subtitles — will be skipped after retries"
    ),
    # BUG-008 — duplicate channel constraint
    (
        r"duplicate key value violates unique constraint.*uq_user_channel",
        "BUG-008",
        "ERROR",
        "Duplicate channel constraint violated — new channel conflict"
    ),
    # Unknown ERROR level (always值得关注)
    (
        r"^\d{4}-\d{2}-\d{2}.+ERROR",
        "UNKNOWN-ERROR",
        "ERROR",
        "Unknown ERROR in logs — review needed"
    ),
]

# ── Dataclassit ────────────────────────────────────────────────────────────────

class LogLine(NamedTuple):
    timestamp: str
    level: str
    source: str
    message: str
    bug_id: str | None
    severity: str | None

class HealthStatus(NamedTuple):
    container: str
    running: bool
    status: str
    restarts: int
    mem_usage_mb: float | None

class MonitorReport(NamedTuple):
    timestamp: datetime
    log_lines: list[LogLine]
    health_checks: list[HealthStatus]
    auto_fixes: list[str]
    alerts: list[str]
    info_count: int
    warning_count: int
    error_count: int

# ── Logger ────────────────────────────────────────────────────────────────────

def log(msg: str, level: str = "INFO"):
    prefix = {
        "INFO": "ℹ️",
        "WARNING": "⚠️",
        "ERROR": "🔴",
        "ALERT": "🚨",
        "DEBUG": "🔵",
    }.get(level, "•")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {prefix} {msg}")

# ── Docker utilities ───────────────────────────────────────────────────────────

def docker_logs(container: str, tail: int = 200) -> str:
    """Hae kontin lokit."""
    try:
        result = subprocess.run(
            ["docker", "logs", "--tail", str(tail), "--timestamps", container],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        log(f"Docker logs timeout for {container}", "ERROR")
        return ""
    except FileNotFoundError:
        log("Docker not found — not running in container environment?", "ERROR")
        return ""

def docker_inspect(container: str) -> dict:
    """Palauta kontin inspect data dict-muodossa."""
    try:
        result = subprocess.run(
            ["docker", "inspect", container],
            capture_output=True, text=True, timeout=10
        )
        import json
        data = json.loads(result.stdout)
        return data[0] if data else {}
    except Exception:
        return {}

def check_container_health(container: str) -> HealthStatus:
    """Tarkista kontin tila."""
    info = docker_inspect(container)
    if not info:
        return HealthStatus(container, False, "NOT FOUND", 0, None)

    state = info.get("State", {})
    running = state.get("Running", False)
    status = state.get("Status", "unknown")
    restarts = info.get("RestartCount", 0)

    # Memory stats
    mem_usage = None
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format",
             "{{.MemUsage}}", container],
            capture_output=True, text=True, timeout=10
        )
        mem_str = result.stdout.strip()
        if mem_str:
            # Parse "123.4MiB / 512MiB"
            match = re.search(r"([\d.]+)([KMG]i?B)", mem_str)
            if match:
                val, unit = match.groups()
                multipliers = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3,
                              "KB": 1000, "MB": 1000**2, "GB": 1000**3}
                mem_usage = float(val) * multipliers.get(unit, 1) / (1024**2)
    except Exception:
        pass

    return HealthStatus(container, running, status, restarts, mem_usage)

# ── Log parsing ───────────────────────────────────────────────────────────────

def parse_log_lines(raw_log: str) -> list[LogLine]:
    """Jäsentää Docker-lokirivit ja tunnistaa virhekaavat."""
    lines = []
    for line in raw_log.splitlines():
        line = line.strip()
        if not line:
            continue

        # Parse timestamp (Docker adds ISO timestamps)
        timestamp_match = re.match(r"(\d{4}-\d{2}-\d{2}T[\d:.]+Z?)\s*(.*)", line)
        if timestamp_match:
            timestamp = timestamp_match.group(1)[:19]  # trim subseconds
            content = timestamp_match.group(2)
        else:
            timestamp = ""
            content = line

        # Parse level
        level = "INFO"
        if "ERROR" in content:
            level = "ERROR"
        elif "WARNING" in content or "WARN" in content:
            level = "WARNING"
        elif "CRITICAL" in content or "ALERT" in content:
            level = "ALERT"

        # Match bug patterns
        bug_id = None
        severity = None
        description = None
        for pattern, b_id, sev, desc in ERROR_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                bug_id = b_id
                severity = sev
                description = desc
                # Upgrade level based on severity
                if sev == "ALERT":
                    level = "ALERT"
                elif sev == "ERROR" and level != "ALERT":
                    level = "ERROR"
                elif sev == "WARNING" and level not in ("ERROR", "ALERT"):
                    level = "WARNING"
                break

        lines.append(LogLine(
            timestamp=timestamp,
            level=level,
            source="docker",
            message=content[:300],  # cap message length
            bug_id=bug_id,
            severity=severity
        ))

    return lines

def filter_notable_lines(lines: list[LogLine]) -> list[LogLine]:
    """Palauta vain ne rivit jotka ovat huomionarvoisia (ei debug normaalitilanteessa)."""
    notable = []
    for line in lines:
        # Always include ERROR, WARNING, ALERT
        if line.level in ("ERROR", "ALERT"):
            notable.append(line)
        # Include known bug matches even if INFO
        elif line.bug_id and line.severity in ("WARNING", "ERROR", "ALERT", "INFO"):
            notable.append(line)
        # Verbose: include all
        elif VERBOSE:
            notable.append(line)
    return notable

# ── Auto-fix logic (SAFE operations only) ─────────────────────────────────────

def safe_auto_fix_transcript_retries() -> list[str]:
    """
    Tarkista onko kanavilla 'transcript_retry_count' jäänyt jumiin.

    Turvallinen korjaus: Jos retry_count > 0 ja edellisestä yrityksestä on
    yli 30 minuuttia → nollaa counter ja merkitse video viimeiseksi.
    Tämä on TURVALLISTA koska:
    - Ei poista dataa
    - Ei muuta transcripts
    - Vain nollaa stuck counterin
    """
    fixes = []
    try:
        # Tarkista onko backend kontti ajossa
        health = check_container_health(BACKEND_CONTAINER)
        if not health.running:
            return [f"Cannot auto-fix: {BACKEND_CONTAINER} is not running"]

        # Hae stuck retry counts suoraan tietokannasta
        result = subprocess.run(
            ["docker", "exec", DB_CONTAINER,
             "psql", "-U", "ytfilter", "-d", "ytfilter", "-t", "-c",
             "SELECT id, channel_name, transcript_retry_count, last_checked_at "
             "FROM youtube_channels WHERE transcript_retry_count > 0;"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return []  # Ei onnistunut, ohita

        stuck_channels = result.stdout.strip()
        if not stuck_channels:
            return []

        for line in stuck_channels.splitlines():
            if not line.strip():
                continue
            # Parse: id | channel_name | retry_count | last_checked_at
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 4:
                continue
            ch_id, ch_name, retry_count, last_checked = parts[0], parts[1], parts[2], parts[3]

            # Tarkista onko viimeksi tarkistettu yli 30 min sitten
            try:
                from datetime import datetime
                last_dt = datetime.fromisoformat(last_checked.replace("Z", "+00:00"))
                if datetime.now(last_dt.tzinfo) - last_dt < timedelta(minutes=30):
                    continue  # Liian tuore, odotetaan
            except Exception:
                pass

            # Auto-fix: nollaa counter
            fix_msg = (f"Auto-fixing stuck transcript_retry_count={retry_count} "
                       f"for channel '{ch_name}' (stuck >30min)")
            log(fix_msg, "WARNING")
            fixes.append(fix_msg)

            if not DRY_RUN:
                subprocess.run(
                    ["docker", "exec", DB_CONTAINER,
                     "psql", "-U", "ytfilter", "-d", "ytfilter", "-t", "-c",
                     f"UPDATE youtube_channels SET transcript_retry_count=0 "
                     f"WHERE id='{ch_id}';"],
                    capture_output=True, timeout=15
                )
    except Exception as e:
        fixes.append(f"Auto-fix error: {e}")
        log(f"Auto-fix failed: {e}", "ERROR")

    return fixes

def safe_auto_restart_if_dead() -> str | None:
    """
    Jos backend kontti on pysähtynyt tai ei vastaa, yritä käynnistää uudelleen.
    Tämä on TURVALLISTA koska Docker hallinnoi prosesseja.
    """
    health = check_container_health(BACKEND_CONTAINER)
    if health.running and health.status == "running":
        return None  # Kaikki OK

    msg = (f"Backend container {BACKEND_CONTAINER} is {health.status} — "
           f"restarting (was running={health.running}, restarts={health.restarts})")
    log(msg, "ALERT")

    if not DRY_RUN:
        subprocess.run(["docker", "restart", BACKEND_CONTAINER],
                       capture_output=True, timeout=60)
    return msg

# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(message: str) -> bool:
    """Lähetä viesti Telegramiin."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set)", "WARNING")
        return False
    try:
        import urllib.request
        import urllib.parse
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        log(f"Telegram send failed: {e}", "ERROR")
        return False

def format_report(report: MonitorReport) -> str:
    """Muotoile raportti Telegram-viestiksi."""
    lines = [
        f"🖥️ *YoutubeFilterAi Monitor*",
        f"🕐 {report.timestamp.strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    # Konttien tila
    lines.append("📦 *Konttien tila:*")
    for h in report.health_checks:
        icon = "✅" if h.running else "❌"
        mem_str = f" ({h.mem_usage_mb:.0f}MB)" if h.mem_usage_mb else ""
        lines.append(f"  {icon} {h.container}: {h.status}{mem_str} (restarts={h.restarts})")
    lines.append("")

    # Auto-fixes
    if report.auto_fixes:
        lines.append("🔧 *Automaattiset korjaukset:*")
        for f in report.auto_fixes:
            lines.append(f"  • {f}")
        lines.append("")

    # Summary counts
    if report.error_count > 0 or report.warning_count > 0:
        lines.append(f"📊 *Lokiyhteenveto:* {report.error_count}❌ {report.warning_count}⚠️ {report.info_count}ℹ️")
        lines.append("")

    # Notable log lines
    notable = [l for l in report.log_lines if l.level in ("ERROR", "ALERT", "WARNING")]
    if notable:
        lines.append("📋 *Viimeisimmät ongelmat:*")
        seen = set()
        for l in notable[-10:]:  # Max 10 riviä
            key = l.message[:80]
            if key in seen:
                continue
            seen.add(key)
            icon = {"ERROR": "❌", "ALERT": "🚨", "WARNING": "⚠️"}.get(l.level, "•")
            lines.append(f"  {icon} `{l.message[:150]}`")
        lines.append("")

    # BUG-001 specific check
    bug001_active = any(l.bug_id == "BUG-001" for l in report.log_lines)
    if bug001_active:
        lines.append("⚠️ *HUOM:* BUG-001 (infinite retry) aktiivinen — katso docs/known_bugs.md")
        lines.append("")

    lines.append("_Automaattinen monitorointi · 15 min välein_")
    return "\n".join(lines)

# ── Pääohjelma ───────────────────────────────────────────────────────────────

def run_health_checks() -> list[HealthStatus]:
    """Tarkista kaikkien konttien terveys."""
    containers = [BACKEND_CONTAINER, DB_CONTAINER, REDIS_CONTAINER]
    # Lisää muut jos löytyy
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True, text=True
    )
    all_containers = result.stdout.strip().splitlines()
    containers = list(set(containers + all_containers))

    return [check_container_health(c) for c in containers if c]

def run() -> MonitorReport:
    """Suorita yksi monitorointikierros."""
    log("Starting monitor run", "INFO")
    timestamp = datetime.now()

    all_lines: list[LogLine] = []
    health_checks = run_health_checks()

    # Hae lokit tärkeimmistä kontista
    for container in [BACKEND_CONTAINER, DB_CONTAINER]:
        h = check_container_health(container)
        if not h.running:
            continue
        raw = docker_logs(container, tail=200)
        lines = parse_log_lines(raw)
        all_lines.extend(lines)

    notable = filter_notable_lines(all_lines)

    # Auto-fixes
    auto_fixes: list[str] = []
    restart_msg = safe_auto_restart_if_dead()
    if restart_msg:
        auto_fixes.append(restart_msg)
    retry_fixes = safe_auto_fix_transcript_retries()
    auto_fixes.extend(retry_fixes)

    # Count by level
    error_count = sum(1 for l in notable if l.level == "ERROR")
    warning_count = sum(1 for l in notable if l.level == "WARNING")
    info_count = sum(1 for l in notable if l.level == "INFO")

    alerts = [l.message for l in notable if l.level in ("ERROR", "ALERT")]

    return MonitorReport(
        timestamp=timestamp,
        log_lines=notable,
        health_checks=health_checks,
        auto_fixes=auto_fixes,
        alerts=alerts,
        info_count=info_count,
        warning_count=warning_count,
        error_count=error_count,
    )

def main():
    if DRY_RUN:
        log("DRY RUN — no changes will be made", "WARNING")

    report = run()
    msg = format_report(report)

    if VERBOSE:
        print("\n" + "="*60)
        print(msg)
        print("="*60)

    # Lähetä Telegram — mutta ei liian usein (vain jos ongelmia)
    has_problems = (report.error_count > 0 or
                    report.warning_count > 0 or
                    len(report.auto_fixes) > 0 or
                    any(not h.running for h in report.health_checks))

    if has_problems:
        sent = send_telegram(msg)
        if sent:
            log("Report sent to Telegram", "INFO")
        else:
            log("Failed to send to Telegram (or not configured)", "WARNING")
    else:
        log("All clear — no issues found", "INFO")

    # Exit code based on severity
    if report.error_count > 0:
        sys.exit(1)
    elif report.warning_count > 3:
        sys.exit(1)  # Too many warnings is also bad
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
