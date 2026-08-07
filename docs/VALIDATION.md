# Validation Checklist

- Run `python -m pytest`.
- Run `python -m creator_intelligence.core.release_verification --source`.
- Run `python -m creator_intelligence.core.privacy_audit --history`.
- Start the application with `python -m creator_intelligence`.
- Confirm the existing database migrates and opens.
- Confirm navigation modules load.
- Close the application and confirm normal shutdown is logged.
- For a public installer, complete `docs/PUBLIC_RELEASE_CHECKLIST.md` and retain the result with the draft release.
