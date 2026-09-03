# Publishing Planner

Phase 6F coordinates approved content from final edit through publication.

## Capabilities

- Recurring platform-specific publishing slots
- Publishing queue
- 30-day release calendar
- Production-project synchronization
- Automatic placement into the next open slot
- Thumbnail, description, metadata, and upload readiness
- Deadline propagation
- Creator/editor ownership of dependencies
- Missed-date and overdue-dependency warnings
- Historical timing analysis
- Publishing recommendations
- Publication activity history
- Human-approved YouTube, TikTok, and Instagram Reel dispatch
- Durable provider upload/container IDs and retry-safe status reconciliation

## Production integration

Approved production projects can automatically create publishing items.
The editor remains responsible for final-edit completion while the creator
owns publication preparation, scheduling, and release.

## Default publishing slots

The seeded schedule includes example YouTube, YouTube Shorts, and TikTok
slots. These are editable records and should be customized to the creator's
actual cadence.

## Timing intelligence

Historical publishing performance is grouped by:

- platform
- content type
- weekday
- publish hour

The score combines views, retention, engagement, and subscriber gain.
This is intentionally based on the creator's own history rather than generic
industry-wide recommendations.

## Direct publishing

The Edited Content Inbox can publish one approved item at a time to YouTube,
TikTok, or Instagram. YouTube uses resumable upload sessions; TikTok uses local
file upload plus publish-status polling; Instagram uses a public HTTPS source URL,
a Reel container, processing checks, and `media_publish`. Every attempt is tied to
its existing platform-specific publishing item. A retry reconciles the saved
provider ID instead of starting a duplicate post.

YouTube and TikTok default to private visibility. Instagram publishing is public
and therefore has an explicit confirmation. Provider app review, account type,
scope approval, quota, and audit restrictions still apply. Twitch direct
publishing is not supported.
