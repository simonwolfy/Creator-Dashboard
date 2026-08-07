# Secure Account Storage

Creator Intelligence stores provider secrets through `keyring`. On Windows,
the active keyring backend uses Windows Credential Manager. Vault entries are
scoped by workspace and provider so separate creator workspaces do not share
accounts.

SQLite stores only non-secret metadata such as provider IDs, channel IDs,
redirect URIs, enablement state, sync timestamps, and sanitized health errors.
API keys, client secrets, access and refresh tokens, OBS passwords, and Google
Drive OAuth credentials remain in the operating-system vault. Secret fields in
the UI display a fixed mask, never the saved value.

When an older workspace opens, credential-shaped values are copied to the vault,
removed from database columns or configuration JSON, and SQLite is compacted and
checkpointed so the previous bytes do not remain in the active database or its
WAL. Database backups created after migration therefore contain no provider
secrets.

Disconnect controls clear local vault entries. TikTok disconnect also calls the
official OAuth v2 revoke endpoint before deleting the local values. Other
providers retain their own account-side permission controls; clearing local
credentials prevents Creator Intelligence from using the account.

The logging layer redacts bearer headers, named token/secret/password values,
and recognizable hosted-service key formats before writing to console or file.
Connection health reports only configured/missing state and never secret values.

Security regressions verify vault migration, masking, refresh rotation,
revocation ordering, local deletion, active-database bytes, generated backups,
and logging output.
