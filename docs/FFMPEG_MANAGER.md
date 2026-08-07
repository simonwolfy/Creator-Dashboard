# Phase 9.0 — FFmpeg Manager

The FFmpeg Manager supplies Creator Intelligence with validated FFmpeg and FFprobe executable paths without modifying the system PATH.

## Detection order

1. Creator Intelligence's saved `config/ffmpeg.json`
2. `CREATOR_INTELLIGENCE_FFMPEG` and `CREATOR_INTELLIGENCE_FFPROBE`
3. the current process PATH
4. common Windows Package Manager installation locations

Both executables must exist and respond successfully to `-version` before the manager reports **Ready**.

## Installation

On Windows, **Install with WinGet** runs a bounded, silent installation of the `Gyan.FFmpeg` package. Package and source agreements are accepted explicitly. The UI remains responsive while installation runs.

The installer does not alter PATH directly. After installation, Creator Intelligence discovers the WinGet package and saves the exact executable paths. If discovery is delayed, the user can restart the application or select the package's `bin` folder manually.

## Manual configuration

**Select FFmpeg bin folder** requires a directory containing both:

- `ffmpeg.exe`
- `ffprobe.exe`

The tools are executed with `-version` before the configuration is saved atomically.

## Safety boundaries

- no arbitrary download URL
- no shell command construction
- no system PATH mutation
- no administrator request initiated by Creator Intelligence
- installation timeout: 15 minutes
- configuration is local and excluded from source control through the existing `config/settings.json` pattern; `config/ffmpeg.json` should remain local runtime configuration

## Integration

The Video Processing and Video Metadata services receive the validated paths when their module services are created. Restart Creator Intelligence after changing tool configuration if an already-open processing page still shows the previous status.
