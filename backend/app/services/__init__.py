"""
YouTube transcript fetching service.

Uses the youtube-transcript-api library to retrieve transcripts
for a given video URL or video ID, with yt-dlp as fallback.

Functions:
    extract_video_id(url: str) -> str
    fetch_transcript(video_id: str) -> str
"""

import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from youtube_transcript_api import YouTubeTranscriptApi

logger = logging.getLogger(__name__)


def extract_video_id(url: str) -> str:
    """Extract the 11-character YouTube video ID from various URL formats.

    Args:
        url: A YouTube URL (watch, short, embed, shorts) or a bare video ID.

    Returns:
        The video ID string.

    Raises:
        ValueError: If the URL format is not recognized.
    """
    patterns = [
        r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"Cannot extract video ID from: {url}")


# Path for YouTube cookies file (optional, helps bypass IP bans)
COOKIES_PATH = Path("/app/youtube_cookies.txt")


def fetch_transcript(video_id: str, languages: Optional[list[str]] = None) -> str:
    """Fetch and concatenate the transcript for a YouTube video.

    Tries youtube-transcript-api first, then falls back to yt-dlp
    which has better anti-ban capabilities.

    Args:
        video_id: The 11-char YouTube video identifier.
        languages: Preferred language codes (default: ["en", "fi"]).

    Returns:
        Plain-text transcript with entries separated by newlines.

    Raises:
        Exception: If no transcript is available from any method.
    """
    if languages is None:
        languages = ["en", "fi"]
    
    # Create API instance with optional cookie support
    kwargs = {}
    if COOKIES_PATH.exists():
        logger.debug("Using cookies file for transcript fetch")
        kwargs["cookie_path"] = str(COOKIES_PATH)
    
    ytt = YouTubeTranscriptApi(**kwargs)
    
    # Method 1: youtube-transcript-api with preferred languages
    try:
        transcript = ytt.fetch(video_id, languages=languages)
        return "\n".join(snippet.text for snippet in transcript.snippets)
    except Exception as api_error:
        logger.debug("youtube-transcript-api preferred langs failed for %s: %s", video_id, str(api_error)[:100])
    
    # Method 2: youtube-transcript-api — list all and try translation/any language
    try:
        transcript_list = ytt.list(video_id)
        available = list(transcript_list)
        if available:
            for t in available:
                if hasattr(t, 'is_translatable') and t.is_translatable:
                    try:
                        translated = t.translate('en')
                        fetched = translated.fetch()
                        return "\n".join(snippet.text for snippet in fetched.snippets)
                    except Exception:
                        pass
            first = available[0]
            fetched = first.fetch()
            lang = getattr(first, 'language_code', 'unknown')
            logger.info("Using %s transcript for video %s", lang, video_id)
            return "\n".join(snippet.text for snippet in fetched.snippets)
    except Exception as list_error:
        logger.debug("youtube-transcript-api list failed for %s: %s", video_id, str(list_error)[:100])
    
    # Method 3: yt-dlp fallback (better at bypassing IP bans)
    logger.info("Trying yt-dlp fallback for transcript %s", video_id)
    return _fetch_transcript_ytdlp(video_id, languages)


def _fetch_transcript_ytdlp(video_id: str, languages: list[str]) -> str:
    """Fetch transcript using yt-dlp as fallback.

    Args:
        video_id: YouTube video ID.
        languages: Preferred language codes.

    Returns:
        Plain-text transcript.

    Raises:
        RuntimeError: If yt-dlp cannot fetch subtitles.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        out_template = f"{tmpdir}/subs"
        
        # Build language preference string
        lang_pref = ",".join(languages) + ",all"
        
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--write-auto-sub",
            "--write-sub",
            "--sub-lang", lang_pref,
            "--sub-format", "vtt",
            "--js-runtimes", "node",
            "--remote-components", "ejs:github",
            "--output", out_template,
            "--no-warnings",
            url,
        ]
        
        # Add cookies if available
        if COOKIES_PATH.exists():
            cmd.extend(["--cookies", str(COOKIES_PATH)])
        
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"yt-dlp timed out fetching subtitles for {video_id}")
        
        # Check stderr for real errors (429, IP block, etc.) even on success
        stderr = result.stderr or ""
        if "429" in stderr or "Too Many Requests" in stderr:
            raise RuntimeError(f"yt-dlp failed for {video_id}: HTTP Error 429: Too Many Requests")
        
        # Find subtitle files (vtt or json3)
        sub_files = list(Path(tmpdir).glob("subs*.*"))
        sub_files = [f for f in sub_files if f.suffix in (".vtt", ".json3") and f.stat().st_size > 0]
        
        if not sub_files:
            error_detail = stderr[:200] if stderr else "no subtitles found"
            raise RuntimeError(f"yt-dlp found no subtitles for {video_id}: {error_detail}")
        
        # Parse the first non-empty subtitle file
        sub_file = sub_files[0]
        content = sub_file.read_text()
        
        if sub_file.suffix == ".json3":
            return _parse_json3_subs(content)
        else:
            return _parse_vtt(content)


def _parse_json3_subs(content: str) -> str:
    """Parse YouTube json3 subtitle format into plain text.

    Args:
        content: Raw json3 subtitle content.

    Returns:
        Plain text transcript.
    """
    try:
        data = json.loads(content)
        lines = []
        for event in data.get("events", []):
            segs = event.get("segs", [])
            text = "".join(s.get("utf8", "") for s in segs).strip()
            if text and text != "\n":
                lines.append(text)
        return "\n".join(lines)
    except (json.JSONDecodeError, KeyError):
        # If JSON parsing fails, return raw content stripped
        return content.strip()


def _parse_vtt(content: str) -> str:
    """Parse VTT subtitle format into plain text.

    Args:
        content: Raw VTT subtitle content.

    Returns:
        Plain text transcript.
    """
    lines = []
    for line in content.split("\n"):
        line = line.strip()
        # Skip headers, timestamps, and empty lines
        if not line or line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if re.match(r"^\d{2}:\d{2}", line) or re.match(r"^\d+$", line):
            continue
        # Remove HTML tags
        clean = re.sub(r"<[^>]+>", "", line)
        if clean:
            lines.append(clean)
    return "\n".join(lines)
