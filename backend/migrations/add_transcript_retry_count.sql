-- Migration: Add transcript_retry_count to youtube_channels
-- Prevents infinite retry loops when a video has no subtitles.
-- A retry counter tracks consecutive transcript failures per channel;
-- the scheduler gives up after 3 attempts so the channel isn't blocked.
ALTER TABLE youtube_channels ADD COLUMN IF NOT EXISTS transcript_retry_count INTEGER NOT NULL DEFAULT 0;
