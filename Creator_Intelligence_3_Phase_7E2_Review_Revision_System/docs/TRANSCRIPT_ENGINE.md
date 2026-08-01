# Transcript Engine

Phase 7.0B adds timestamped transcript storage and search.

## Supported input

- OpenAI Whisper command-line output
- Configurable Whisper-compatible wrapper
- SRT
- WebVTT
- JSON segment arrays
- Plain text or Markdown for testing and legacy notes

## Local transcription

The engine searches for:

1. `CREATOR_INTELLIGENCE_WHISPER`
2. `faster-whisper`
3. `whisper`

When the standard OpenAI Whisper command is available, Creator Intelligence
runs it with JSON output and word timestamps.

Other Whisper distributions expose different command-line interfaces. The
custom environment variable can point to a wrapper accepting:

```text
--input <audio>
--model <model>
--language <language>
--output <json path>
```

The JSON result should contain either a segment array or:

```json
{"segments": [...]}
```

## Long VOD handling

Transcription jobs operate against the audio artifact created by Video
Processing when available. The source video remains untouched.

For 8–12 hour VODs:

- use a 16 kHz mono WAV
- begin with the `base` or `small` model
- process one transcription job at a time
- preserve generated JSON so the transcript can be rebuilt without
  transcribing again

Actual processing time depends heavily on CPU/GPU hardware and the selected
model.

## Search

Transcript segments are indexed with SQLite FTS5 when available. A normal
substring-search fallback is created for SQLite builds without FTS5.

Search results include:

- VOD/transcript title
- segment timestamp
- matching text
- segment boundaries

## Chapters

The first chapter engine is intentionally transparent and heuristic. It uses:

- target chapter duration
- minimum and maximum duration
- transition language
- recurring keywords
- the first concise sentence in each chapter
- extractive summaries

Later phases can replace or supplement these titles with a local or remote
language model without changing transcript storage.
