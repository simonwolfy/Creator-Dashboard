# Creator Dashboard

The Creator Dashboard is the first navigation page in Creator Intelligence. It converts the unified content library into a daily operating view without coupling the UI to Twitch, YouTube, Google Drive, or any other integration.

## Data flow

1. Platform integrations and manual workflows create or update `content_items`.
2. `CreatorDashboardService` aggregates content counts, actionable workflow states, recent activity, and scheduled publications.
3. `CreatorDashboardPage` renders metric cards and read-only work tables.
4. The existing `content` module registers both the dashboard service and page, preserving the 21-module architecture.

## Work queue priority

Items are prioritized in this order:

1. Needs review
2. Revision requested
3. Ready to publish
4. Waiting on editor
5. Editing
6. Other actionable states

The dashboard is safe for empty workspaces and will render zero counts and empty tables until content is added or imported.
