# Background Import Watcher and Notifications

## Runtime model

The watcher runs in a daemon thread only while Creator Intelligence is open.
It does not install a Windows service or create a hidden startup task.

This design keeps database activity visible and ensures the process stops when
the desktop application closes.

## Scan behavior

The watcher:

1. Reads enabled watched folders
2. Scans CSV and TSV files
3. Ignores previously imported file hashes
4. Stages new files or commits them according to settings
5. Records folder scan results
6. Creates notifications
7. Generates operational alerts
8. Sleeps until the next interval

The minimum interval is 10 seconds. The default is 60 seconds.

## Auto-commit

Auto-commit is disabled by default.

When disabled:
- recognized files are staged
- the user receives an "Import ready for review" notification
- the user commits from the Import Center

When enabled:
- valid staged changes are committed automatically
- backups and archive copies are still created
- completion, warning, duplicate, and failure notifications are generated

## Notification categories

- Import
- Backup
- Rollback
- Prediction
- Model
- Pipeline
- Calendar
- Integration
- System

The first operational rules include:

- completed imports
- imports with warnings
- duplicate files
- failed imports
- staged imports awaiting review
- overdue content-pipeline items
- calendar items occurring in the next 24 hours
- watcher failures

## Future integration

Other modules can use `NotificationService.create(...)` without modifying the
notification interface. Prediction retraining, live-stream monitoring,
financial thresholds, and integration failures can therefore use the same
notification center.
