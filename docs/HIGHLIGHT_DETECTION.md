# Highlight Detection and Candidate Review

## Candidate generation

The detector collects high-value live-session markers and events, orders them
by stream-relative timestamp, and groups signals that occur within the
configured window.

Default grouping window: 150 seconds.

## Scoring

Candidate score combines:

- signal type
- marker strength
- raid size
- chat multiplier
- follower volume
- number of nearby signals
- source confidence

Scores are capped at 100.

## Classification

Current rule-based classifications include:

- Raid reaction
- Strong reaction or manual moment
- High-engagement moment
- Community growth moment
- Community interaction
- Viewer milestone
- Game transition
- General highlight

## Suggested boundaries

Every candidate receives:

- full-highlight start and end
- short-form start and end
- pre-roll
- post-roll
- maximum-length enforcement

The strongest signal becomes the center of the short-form recommendation.

## Review actions

Candidates support:

- approve
- reject
- mark as needs changes
- edit boundaries
- merge
- split
- add reviewer notes
- export to content pipeline

## Pipeline export

Approved candidates can become:

- YouTube Short
- YouTube Highlight
- TikTok Clip
- Multi-platform Clip

The pipeline record retains:

- session ID
- full clip boundaries
- short-form boundaries
- score
- confidence
- classification
- reviewer notes

## Current limitation

This phase detects likely high-value timestamps using analytics and events.
It does not yet inspect transcript content, audio intensity, facial reactions,
or video frames. Those signals can be added without replacing the review queue
or candidate model.
