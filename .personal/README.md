# FLClash Personal

Android package `io.github.chen017.flclash`. This is an unofficial, separately signed app based on the latest stable FLClash release, retaining its own Android core integration.

Only one Android arm64-v8a APK is built. Keep the official app installed while migrating: export a **local backup** there and import it here, then confirm subscriptions, Age keys, selections and VPN access. Only one Android VPN can run at a time. Do not uninstall the official app until the personal app works.

Use the personal app's ordinary **Check for updates** afterwards. It reads this fork's releases and verifies SHA256SUMS before opening the Android package installer. The permanent signing key allows in-place updates; Android still requires your approval to install an APK. Core-only releases increment both the APK version code and the update comparison version.

Every six hours, Personal Android checks the latest **stable** upstream tag and maintained patches. Inputs are pinned and hashed. Unchanged inputs do not rebuild. Conflicts, failed tests or signing mismatches stop publication and preserve the last usable release. Actions failures appear in the repository Actions page. GitHub can suspend scheduled workflows in inactive forks; check the workflow if no runs appear for a long time. Manual Run workflow remains available.

To maintain: update `.personal/app.patch` or `.personal/core.patch`, run the tests, and push main. Do not edit only the generated `.personal/work/source` tree. `release.py prepare` creates a fresh fixed upstream checkout, applies both checked patches, and records provenance. The published complete-source archive includes actual modified submodules and their licenses; GitHub's automatic source archive alone does not include submodules.

Secrets: ANDROID_KEYSTORE_BASE64, ANDROID_KEYSTORE_PASSWORD. Public variable: ANDROID_CERT_SHA256. Missing signing material fails the build. Never replace the key to fix a build: restore it from the private local key backup, or existing installations cannot update.

Protocol tests and real Xray loopback regression cover both split directions, provider scope/cycles and 0-RTT ticket recovery. Flutter tests cover backup and update behavior. The release verifies the permanent signature, version code and arm64-only native libraries. VPN permission/revoke, real carrier IPv6 and handset battery restrictions still require a physical-phone check.

### Android NAT encrypted entry compatibility

On Android, raw TCP VLESS `random` encryption without TLS splits its first encrypted write into one byte and the remainder, with no fixed delay. This applies to both a cold handshake and the first application write on a resumed zero-RTT session; encryption, keys and server configuration stay unchanged. Other transports and desktop defaults are unchanged. A proxy can explicitly override this with `encryption-fragment: false` (disable) or `true` (enable). The override takes effect when the profile/provider reloads.

This addresses an observed access-path stall where TCP connects but an unsplit random first flight times out. It does not claim to identify the network device responsible. Only the first write of each new encrypted TCP connection is split. The initial 50 ms diagnostic gap was unnecessary in repeated direct-handshake tests and is not part of the implementation.
