# Automated Import Center

## Supported files

The first production import module recognizes:

- Twitch daily analytics CSV/TSV
- YouTube content analytics CSV/TSV
- Twitch raid-history CSV/TSV

Detection is based on normalized column headers, not filenames.

## Processing sequence

1. File fingerprinting
2. Export-type detection
3. Header mapping
4. Row normalization
5. Required-key validation
6. Existing-record comparison
7. Staging preview
8. Database backup
9. Transactional upsert
10. Archive copy
11. Import-history record
12. Optional rollback

## Row dispositions

- `Insert`: new platform record
- `Update`: existing record has changed
- `Duplicate`: existing record is identical
- `Rejected`: required data is missing or invalid

## Watched folders

Watched folders may be scanned manually or scanned and committed in one action.
Recursive scanning and post-import archive behavior are persisted in SQLite.

This build lays the persistence and service foundation for a later background
watcher process. Folder scans are initiated from the Import Center interface so
the desktop app does not silently modify the database without user visibility.

## Rollback

Every committed import creates a complete SQLite backup. Rollback restores that
backup and creates an additional safety backup of the current database first.

Because the rollback restores the entire database state from before the import,
later changes made after that import are also reverted. The interface labels
rollback explicitly for this reason.
