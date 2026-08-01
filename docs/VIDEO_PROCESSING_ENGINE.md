# Phase 7.0A — Video Processing Engine

This is the media foundation for transcription and video intelligence.

## Long-VOD workflow

1. Import an 8–12 hour local VOD.
2. Probe duration, resolution, codecs, frame rate, audio format, and bitrate.
3. Queue one or more operations.
4. Process in a background UI thread with persistent progress.
5. Reuse the resulting artifacts in transcription, chapters, highlights, and editor briefs.

## Operations

- **Extract audio:** mono 16 kHz PCM WAV suitable for speech-to-text.
- **Generate thumbnails:** configurable interval frames, defaulting to every five minutes.
- **Generate proxy:** 720p H.264/AAC review copy.

## Reliability

Jobs are stored in SQLite and support cancellation, retry, error history, and recovery after application interruption. FFmpeg streams media rather than loading a full VOD into memory. Source files are read-only inputs; outputs are written under the application media-processing directory.

## FFmpeg setup

The app searches PATH for `ffmpeg` and `ffprobe`. Custom paths may be supplied with `CREATOR_INTELLIGENCE_FFMPEG` and `CREATOR_INTELLIGENCE_FFPROBE`.

## Next

Phase 7.0B can add chunked, resumable Whisper transcription with timestamped full-text search.
