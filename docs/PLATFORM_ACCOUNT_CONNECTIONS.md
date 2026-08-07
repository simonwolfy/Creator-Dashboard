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
   Client ID, and click **Connect Twitch**.
4. Approve the device sign-in in the browser. The broadcaster ID, access token, and
   refresh token are filled automatically.

The connection requests read-only chat, follower, subscription, and bits scopes
used by live intelligence. Twitch may show those permissions during approval.

Official reference: [Twitch device code grant](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/#device-code-grant-flow).

## YouTube

1. In Google Cloud, enable **YouTube Data API v3** and configure the OAuth consent
   screen. While the app is in testing, add the Google account that owns the channel
   as a test user.
2. Create an OAuth client with application type **Desktop app** and download its
   JSON file. Do not commit that file to Git.
3. Open **YouTube > API setup**, click **Import Google OAuth client JSON**, then
   click **Connect YouTube**.
4. Select the channel-owning Google account and approve read-only YouTube access.
   The channel ID and refreshable tokens are filled automatically.

An API key is optional after Google sign-in, but remains supported for public-only
channel synchronization.

Official reference: [Google OAuth for mobile and desktop apps](https://developers.google.com/youtube/v3/guides/auth/installed-apps).

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

The account must be eligible for the Instagram professional API features enabled
for the Meta app. Available insights depend on Meta review and granted permissions.

## TikTok

1. Create a TikTok developer app and add **Login Kit for Desktop**.
2. Request or enable `user.info.basic` and `video.list`.
3. Register `http://127.0.0.1:49152/callback/` as the Desktop redirect URI.
4. Enter the client key and client secret on the TikTok page, then click
   **Connect TikTok**.
5. Approve access in the browser. Creator Intelligence validates state and PKCE,
   then fills the open ID, access token, and refresh token automatically.

Content and analytics access can remain unavailable until TikTok approves the app
and its requested scopes.

Official reference: [TikTok Login Kit for Desktop](https://developers.tiktok.com/doc/login-kit-desktop/).

## Disconnecting

Use the platform's **Disconnect** control to revoke access where the provider
supports programmatic revocation and clear local credential-vault entries. If a
provider cannot be reached, remove Creator Intelligence from that account's
connected-app settings as well.
