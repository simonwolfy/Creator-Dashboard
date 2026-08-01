# Scene and Chapter Intelligence

Phase 7.0C converts transcript and audio information into an editor-oriented
VOD structure.

## Scene segmentation

Transcript segments are grouped using:

- target section duration
- topic-word overlap
- transition language
- hard maximum section duration

Each scene receives:

- timestamps
- topic keywords
- title
- summary
- speech density
- silence ratio
- activity score
- content-value score
- classification
- confidence

## Scene classifications

The first heuristic engine recognizes:

- Dead air / AFK
- Low-value maintenance
- Raid / community event
- Action / gameplay event
- Building / progression
- Explanation / tutorial
- High-value gameplay
- Low-value gameplay
- General gameplay

## Silence detection

When FFmpeg is installed, the service can run `silencedetect` against the
source media or extracted audio.

Settings include:

- noise threshold in decibels
- minimum silence duration

Detected intervals remain linked to the source VOD.

## Low-value detection

A section may be marked low-value because of:

- high silence ratio
- low transcript density
- low content-value score
- AFK language
- menu, inventory, waiting, sorting, or grinding language
- extended standalone silence

These are recommendations for the editor, not automatic deletion commands.

## Unified timeline

The VOD timeline combines:

- scene sections
- transcript chapters
- low-value intervals
- stream markers when available

Later phases will also add highlight candidates, thumbnail frames, and
editor-review decisions to the same timeline.
