# Live Stream Intelligence

## Data model

The live module stores:

- live sessions
- minute-level metric snapshots
- event timeline entries
- stream markers
- Twitch and OBS connection settings
- projections and final outcomes

## Current working mode

Simulation mode is fully functional and provides:

- automatic session creation
- minute-by-minute viewer snapshots
- followers, subscriptions, revenue, and chat activity
- viewer and chat spikes
- follower spikes
- raid markers
- game changes
- manual markers
- live projections
- performance scoring
- session finalization

This allows every dashboard, marker, timeline, and prediction calculation to be
tested without broadcasting.

## Twitch integration foundation

`TwitchLiveAdapter` maps EventSub payloads into the live-session system:

- stream.online
- stream.offline
- channel.raid
- channel.follow
- channel.update
- channel.chat.message

The adapter also validates whether the required local credentials are
configured. Twitch's device-code sign-in fills the broadcaster ID, saves access
and refresh tokens in the operating-system vault, and supports token refresh.
Network transport and EventSub WebSocket reconnection remain isolated behind the
adapter.

## OBS integration foundation

`OBSLiveAdapter` maps OBS WebSocket events into the timeline:

- CurrentProgramSceneChanged
- StreamStateChanged
- RecordStateChanged
- arbitrary OBS events

The configured endpoint defaults to `127.0.0.1:4455`.

## Marker rules

### Viewer spike

Creates a marker when the current viewer count is above the historical mean by
the configured standard-deviation threshold.

### Chat spike

Creates a marker when messages per minute exceed the rolling baseline by the
configured multiplier.

### Follow spike

Creates a marker when the configured number of follow events occur within the
configured time window.

### Raid

Creates a marker when the raid viewer count meets the configured threshold.

### Game change

Creates a chapter-boundary marker whenever the Twitch category changes.

### Manual marker

A manual button creates a high-confidence marker at the current session time.

## Live projection

The projected average blends:

- pre-stream prediction
- current session average
- five-minute viewer velocity
- elapsed-session stabilization

Early projections remain closer to the pre-stream baseline. As the stream
continues, live measurements receive more weight.

## Performance score

The live score combines:

- viewer projection versus baseline
- retention estimate
- chat activity
- followers gained
- revenue per hour

The result is capped at 100 and is intended as an operational score, not a
platform-provided metric.
