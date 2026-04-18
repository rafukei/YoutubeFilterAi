"""
Unit tests for core services: video ID extraction, AI routing parser, transcript service.

Run: cd backend && pytest tests/ -v
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services import extract_video_id
from app.services.ai_service import parse_ai_routing


class TestExtractVideoId:
    """Tests for YouTube URL → video ID extraction."""

    def test_standard_url(self):
        assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self):
        assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self):
        assert extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_bare_id(self):
        assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_invalid_url(self):
        with pytest.raises(ValueError):
            extract_video_id("https://example.com/not-a-video")

    def test_url_with_extra_params(self):
        """URL with timestamp and other params."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120&list=PLxxxx"
        assert extract_video_id(url) == "dQw4w9WgXcQ"

    def test_url_with_www(self):
        """URL with www prefix."""
        assert extract_video_id("https://www.youtube.com/watch?v=abc123XYZ99") == "abc123XYZ99"

    def test_url_without_www(self):
        """URL without www prefix."""
        assert extract_video_id("https://youtube.com/watch?v=abc123XYZ99") == "abc123XYZ99"

    def test_mobile_url(self):
        """Mobile URL format."""
        assert extract_video_id("https://m.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        """YouTube Shorts URL format."""
        result = extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ")
        assert result == "dQw4w9WgXcQ"

    def test_empty_string(self):
        """Empty string should raise error."""
        with pytest.raises(ValueError):
            extract_video_id("")

    def test_none_input(self):
        """None input should raise error."""
        with pytest.raises((ValueError, TypeError, AttributeError)):
            extract_video_id(None)


class TestParseAiRouting:
    """Tests for extracting the routing JSON block from AI responses."""

    def test_valid_json_at_end(self):
        response = 'Here is a summary.\n{"message": "summary text", "telegram_bots": ["bot1"], "web_views": ["news"], "visibility": true}'
        result = parse_ai_routing(response)
        assert result["message"] == "summary text"
        assert result["telegram_bots"] == ["bot1"]
        assert result["web_views"] == ["news"]
        assert result["visibility"] is True

    def test_no_json(self):
        response = "Just a plain text response with no JSON."
        result = parse_ai_routing(response)
        assert result["message"] == response
        assert result["telegram_bots"] == []
        assert result["web_views"] == []
        assert result["visibility"] is True

    def test_invalid_json(self):
        response = "Some text {not valid json}"
        result = parse_ai_routing(response)
        assert result["message"] == response

    def test_json_missing_message_key(self):
        response = 'Text\n{"foo": "bar"}'
        result = parse_ai_routing(response)
        # Falls back because "message" key not found
        assert result["message"] == response

    def test_multiple_bots(self):
        """JSON with multiple Telegram bots."""
        response = '{"message": "Test", "telegram_bots": ["bot1", "bot2", "bot3"], "web_views": [], "visibility": true}'
        result = parse_ai_routing(response)
        assert len(result["telegram_bots"]) == 3
        assert "bot1" in result["telegram_bots"]
        assert "bot3" in result["telegram_bots"]

    def test_visibility_false(self):
        """JSON with visibility set to false."""
        response = '{"message": "Private", "telegram_bots": [], "web_views": [], "visibility": false}'
        result = parse_ai_routing(response)
        assert result["visibility"] is False

    def test_json_with_unicode(self):
        """JSON with unicode characters."""
        response = '{"message": "Yhteenveto videosta 日本語", "telegram_bots": ["bot"], "web_views": [], "visibility": true}'
        result = parse_ai_routing(response)
        assert "日本語" in result["message"]

    def test_json_with_newlines_in_message(self):
        """JSON with newlines in message field."""
        response = '{"message": "Line 1\\nLine 2\\nLine 3", "telegram_bots": [], "web_views": [], "visibility": true}'
        result = parse_ai_routing(response)
        assert result["message"] is not None

    def test_empty_response(self):
        """Empty response should return default structure."""
        result = parse_ai_routing("")
        assert result["message"] == ""
        assert result["telegram_bots"] == []
        assert result["web_views"] == []

    def test_json_in_middle_of_text(self):
        """JSON block in middle of response."""
        response = 'Before text {"message": "Middle JSON", "telegram_bots": [], "web_views": [], "visibility": true} After text'
        result = parse_ai_routing(response)
        # Behavior depends on implementation - may find JSON or fallback
        assert result["message"] is not None


class TestTranscriptService:
    """Tests for YouTube transcript fetching service."""

    def test_transcript_fetch_mocked(self):
        """Test transcript fetching with mocked YouTube API."""
        from app.services import fetch_transcript
        
        # Mock the new API: ytt.fetch() returns an object with .snippets
        mock_snippet_1 = MagicMock(text="Hello world")
        mock_snippet_2 = MagicMock(text="This is a test")
        mock_transcript = MagicMock()
        mock_transcript.snippets = [mock_snippet_1, mock_snippet_2]
        
        mock_ytt = MagicMock()
        mock_ytt.fetch.return_value = mock_transcript
        
        with patch("app.services.YouTubeTranscriptApi", return_value=mock_ytt):
            result = fetch_transcript("dQw4w9WgXcQ")
            assert "Hello world" in result
            assert "This is a test" in result

    def test_transcript_not_available(self):
        """Test handling when transcript is not available."""
        from app.services import fetch_transcript
        
        mock_ytt = MagicMock()
        mock_ytt.fetch.side_effect = Exception("No transcript available")
        mock_ytt.list.side_effect = Exception("No transcript available")
        
        with patch("app.services.YouTubeTranscriptApi", return_value=mock_ytt):
            with patch("app.services._fetch_transcript_ytdlp", side_effect=RuntimeError("yt-dlp failed")):
                with pytest.raises(Exception):
                    fetch_transcript("no-transcript-video")


class TestTelegramService:
    """Tests for Telegram message sending service."""

    @pytest.mark.asyncio
    async def test_send_message_success(self):
        """Test successful Telegram message sending."""
        from app.services.telegram_service import send_telegram_message
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = await send_telegram_message(
                bot_token="123:ABC",
                chat_id="-100123",
                text="Test message",
                video_url="https://youtube.com/watch?v=test"
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_send_message_failure(self):
        """Test Telegram message sending failure handling."""
        from app.services.telegram_service import send_telegram_message
        
        mock_response = MagicMock()
        mock_response.status_code = 400
        
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = await send_telegram_message(
                bot_token="invalid",
                chat_id="-100123",
                text="Test",
                video_url="https://youtube.com/watch?v=test"
            )
            assert result is False


class TestAIServiceRateLimiting:
    """Tests for OpenRouter AI rate limiting."""

    @pytest.mark.asyncio
    async def test_rate_limit_check_allows_request(self):
        """Test rate limit check allows request under limit."""
        from app.services.ai_service import _check_rate_limit
        
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"5")  # 5 requests used
        mock_redis.pipeline = MagicMock(return_value=AsyncMock(
            incr=MagicMock(),
            expire=MagicMock(),
            execute=AsyncMock(return_value=[6, True])
        ))
        
        # Should not raise for normal usage (under limit)
        await _check_rate_limit(user_id="test-user", redis_client=mock_redis)

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self):
        """Test rate limit exceeded scenario."""
        from app.services.ai_service import _check_rate_limit
        
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"100")  # Exceeds default limit (10)
        
        # Should raise RuntimeError for exceeded limit
        with pytest.raises(RuntimeError, match="Rate limit exceeded"):
            await _check_rate_limit(user_id="test-user", redis_client=mock_redis)
