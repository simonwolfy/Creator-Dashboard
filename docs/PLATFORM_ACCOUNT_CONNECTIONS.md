# Platform account connections

Creator Intelligence opens provider authorization pages in the default browser.
Passwords are entered only on the provider's website. Access tokens, refresh
tokens, API keys, and client/app secrets are stored in the operating-system
credential vault rather than the workspace database or logs.

## Twitch

1. In the [Twitch developer console](https://dev.twitch.tv/console/apps), create an
   application and choose **Public** as the client type. Twitch requires 2FA on the
   developer account.
2. Copy the Client ID. A Client Secret and redirect URL are not used by this flow.
3. In Creator Intelligence, open **Live Stream > Connections and rules**, paste the
   Client ID, and click **Connect / reconnect Twitch**.
4. Approve the device sign-in in the browser. The broadcaster ID, access token, and
   refresh token are filled automatically.

The connection requests only the read-only chat, follower, and subscription
permissions used by live intelligence. It cannot post chat messages or change the
channel. Creator Intelligence validates the token when the app starts and hourly,
rotates the public-client refresh token as required, and displays missing
permissions as limited capabilities instead of failing the whole connection.

Twitch's public device flow requires no local OAuth callback, so it works the same
way in the packaged Windows application. Use **Check connection** to validate on
demand, **Refresh credentials** to rotate an expiring token, and **Disconnect and
revoke** to remove access and clear the operating-system vault.

Official reference: [Twitch device code grant](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/#device-code-grant-flow).

## YouTube

1. In Google Cloud, enable **YouTube Data API v3** and **YouTube Analytics API**, then
   configure the OAuth consent screen. While the app is in testing, add the Google
   account that owns the channel as a test user.
2. Create an OAuth client with application type **Desktop app** and download its
   JSON file. Do not commit that file to Git.
3. Open **YouTube > API setup**, click **Import Google OAuth client JSON**, then
   click **Connect YouTube**.
4. Select the channel-owning Google account and approve read-only YouTube and
   YouTube Analytics access. The channel ID and refreshable tokens are filled
   automatically, followed by an initial content-and-analytics sync.

An API key is optional after Google sign-in, but remains supported for public-only
channel synchronization. API-key-only connections are shown as **Limited** because
they cannot read private watch time, retention, subscriber, or share analytics.
Creator Intelligence checks OAuth hourly and refreshes content and Analytics every
30 minutes while the YouTube page is open. Revoked or expired refresh tokens are
shown as reconnect-required states; quota errors preserve the connection and show a
temporary limited state instead of deleting credentials.

Official references: [Google OAuth for mobile and desktop apps](https://developers.google.com/youtube/v3/guides/auth/installed-apps)
and [YouTube Analytics reports](https://developers.google.com/youtube/analytics/reference/reports/query).

## Google Drive

1. In Google Cloud, enable **Google Drive API** and configure the OAuth consent
   screen. Add the connecting account as a test user while the app is in testing.
2. Create an OAuth client with application type **Desktop app** and download its
   JSON file. Do not commit that file to Git.
3. Open **Google Drive**, choose the desktop client JSON, then click **Connect Google
   Drive** and approve access in the browser.
4. The app performs an initial metadata-only top-level folder sync. Use **Drive
   Folders** to browse and map the folders needed by the workspace.

Creator Intelligence requests `drive.metadata.readonly`. It cannot download file
contents or create, edit, move, or delete Drive files. It validates the connection
hourly and refreshes its lightweight folder summary every 30 minutes while the page
is open. Access tokens refresh through the securely stored refresh token. Expired,
revoked, quota-limited, and other error states remain visible with a reconnect or
retry path. **Disconnect and revoke access** clears the local OS-vault credentials
even if Google is temporarily unreachable.

Official references: [Choose Google Drive scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
and [Resolve Drive API errors](https://developers.google.com/workspace/drive/api/guides/handle-errors).

## Instagram

1. Create a Meta developer app, add **Instagram API with Instagram Login**, and
   configure the permissions needed for basic account data and insights.
2. Add a valid OAuth redirect URI. For local development, use
   `http://127.0.0.1:49153/callback/` if the Meta app configuration accepts a local
   callback. For production, use the approved HTTPS callback for that Meta app.
3. Enter the Meta app ID, app secret, and exact redirect URI on the Instagram page.
4. Click **Connect Instagram** and approve access. With a local callback the app
   finishes automatically. With an HTTPS callback, paste the complete final
   callback URL into the dialog so its code and anti-forgery state can be verified.

Instagram Login supports professional **Business** and **Creator** accounts, not
personal consumer accounts. The app requests `instagram_business_basic` and
`instagram_business_manage_insights`; it does not request publishing or media
editing. Standard Access covers accounts owned by or assigned to app-role users,
while other professional accounts require the appropriate Meta review and Advanced
Access. Some metrics vary by media type, and Meta can return an empty result rather
than zero when a metric is unavailable. Creator Intelligence preserves the basic
media sync and marks the connection **Limited** when only some insights are
available.

The connection is checked hourly and content statistics are refreshed every 30
minutes while the page is open. Reconnecting replaces the one active Instagram
account stored for that workspace. Disconnect always clears the local OS-vault
credentials; remove the app under Instagram **Apps and Websites** as well when you
want to revoke the remote grant.

Official reference: [Meta's Instagram API workspace](https://www.postman.com/meta/instagram/overview).

## TikTok

1. Create a TikTok developer app and add **Login Kit for Desktop**.
2. Request or enable `user.info.basic` and `video.list`.
3. Register `http://127.0.0.1:49152/callback/` as the Desktop redirect URI.
4. Enter the client key and client secret on the TikTok page, then click
   **Connect TikTok**.
5. Approve access in the browser. Creator Intelligence validates state and PKCE,
   then fills the open ID, access token, and refresh token automatically.

TikTok's Display API exposes the public account profile and public video counts:
views, likes, comments, and shares. It does not expose creator watch time,
retention, revenue, or audience analytics, and Creator Intelligence does not request
publishing permission. Content remains unavailable until `video.list` is granted;
the page shows partial permissions as **Limited** instead of treating them as a
complete connection.

Access tokens are refreshed automatically and TikTok's rotated refresh token is
saved over the previous one. The connection is checked hourly and public video
statistics are refreshed every 30 minutes while the page is open. Reconnecting
replaces the one active TikTok account stored for that workspace. Disconnect tries
TikTok's revoke endpoint and always clears local credentials, even if TikTok is
temporarily unreachable.

Official references: [TikTok Login Kit for Desktop](https://developers.tiktok.com/doc/login-kit-desktop/),
[Display API](https://developers.tiktok.com/doc/display-api-overview/), and
[access-token management](https://developers.tiktok.com/doc/oauth-user-access-token-management?enter_method=left_navigation).

## Disconnecting

Use the platform's **Disconnect** control to revoke access where the provider
supports programmatic revocation and clear local credential-vault entries. If a
provider cannot be reached, remove Creator Intelligence from that account's
connected-app settings as well.
