# Google Drive Folder Mapping

Phase 8.7.2 lets Creator Intelligence browse Google Drive folders and save durable sync mappings.

Each mapping stores the Drive folder ID, display name, purpose, recursive behavior, metadata-only behavior, enabled state, validation time, and last error. Drive folder IDs are unique, so repeated mapping does not create duplicates.

Supported purposes are Raw Recordings, Exports, Thumbnails, Project Files, Subtitles, and Other.

This phase does not import file metadata or download media. Phase 8.7.3 will use enabled mappings as synchronization roots. OAuth tokens remain in the operating-system credential vault and are never written to SQLite.
