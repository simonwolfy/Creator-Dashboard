# Content Intelligence

Phase 8.2 introduces a canonical library for creator content.

## Canonical items

Every VOD, long-form video, Short, clip, local recording, and future platform item receives a permanent UUID. Platform identifiers are secondary identifiers and are unique within a platform.

The content item stores workflow metadata, source locations, publication data, collaborators, tags, performance metrics, and creator-specific fields such as game, series, episode, editor, and status.

## Relationships

`content_relationships` forms a directed graph between content items. A source VOD may have any number of derived outputs. Relationships may also store source time ranges, allowing a Short or edited episode to reference the segment of the original recording from which it was created.

Initial relationship types are free-form but default to `derived_from`. Expected values include:

- `derived_from`
- `clip_from`
- `episode_from`
- `short_from`
- `reupload_of`
- `compilation_contains`

Self-relations and duplicate relations of the same type are prevented.

## Service API

`ContentLibraryService` provides:

- create and update operations
- lookup by permanent internal ID
- filtered text search
- parent and child traversal
- relationship creation

The initial service layer is intentionally platform-independent. Twitch, YouTube, Google Drive, and local-file integrations will map their records into this model rather than defining separate content identities.

## Migration strategy

Migration 4 creates the canonical schema without deleting or rewriting legacy tables. A later migration/import pass will map established records from existing analytics, production, publishing, and creator-planner tables once field-level mapping has been validated against real user data.
