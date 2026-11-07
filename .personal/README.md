# FLClash Personal

完整中文需求与维护清单见 [个人 Fork 定制说明](https://github.com/Chen017/mihomo/blob/codex/window-builds/CUSTOMIZATIONS.md)。后续升级请保留列出的配置语义和签名身份；移除补丁前应先验证上游已有等价实现。

Android package `io.github.chen017.flclash`. This is an unofficial, separately signed app based on the latest stable FLClash release, retaining its own Android core integration.

Only one Android arm64-v8a APK is built. Keep the official app installed while migrating: export a **local backup** there and import it here, then confirm subscriptions, Age keys, selections and VPN access. Only one Android VPN can run at a time. Do not uninstall the official app until the personal app works.

Use the personal app's ordinary **Check for updates** afterwards. It reads this fork's releases and verifies SHA256SUMS before opening the Android package installer. The permanent signing key allows in-place updates; Android still requires your approval to install an APK. Core-only releases increment both the APK version code and the update comparison version.

### Maintenance and local checks

- `app.patch` carries the personal Android identity, update comparison, editor hints and app regressions. Keep the files mirrored on `main` in sync with it. `core.patch` carries the personal transport changes and their Go tests. Both patches have explicit upstream bases in `release.py` for three-way application. Refresh the corresponding base when regenerating a patch against a new upstream revision.
- `release.py` plans the release, prepares pinned sources, verifies the APK, packages complete source and publishes through a draft. `run_e2e.py` runs the pinned Xray-Panel fixture against the patched Core and a checksum-verified Xray binary. `.personal/work/` and `.personal/dist/` are generated paths. Put changes in the maintained patches or scripts so fresh checkouts receive them.
- From the repository root, run the offline checks with Python 3.11+ and Git.

  ```bash
  python3 -m unittest discover -s .personal -p 'test_*.py' -v
  git apply --reverse --check .personal/app.patch
  ```

- To reproduce source preparation in a fresh clone, use an authenticated GitHub CLI and run `python3 .personal/release.py prepare`. It reads public release metadata and, when a build is needed, creates `.personal/work/source` and writes the pinned app/Core revisions and tool versions to `plan.json`. Use those versions for Go, Flutter and NDK, plus JDK 17 and Node 24. The workflow contains the Core test package list and wrapper commands. The Xray loopback test needs Linux and the fixture checkout at the commit named in the workflow.
- In the prepared source tree, run `flutter pub get`, `flutter analyze --no-fatal-infos`, and `flutter test test/common/personal_update_test.dart test/core/protocol_contract_test.dart` for the app boundary. The release job runs the broader suite in its temporary tree with the desktop setup hook disabled for testing, then restores the build configuration for Android packaging.

### CI and signed releases

`Personal Android` checks every six hours and accepts manual runs on `main`. Pushes changing the maintenance scripts, patches or workflow also run it. Pull requests touching the personal build inputs or mirrored app changes run the offline checks with read-only repository permissions. The release job compares the official stable commit and maintenance-input digest against the latest personal manifest before fetching upstream Git objects or installing build tools. Inputs that match the last published release finish at that step. Python unittest changes still run the offline checks and do not change the APK build fingerprint.

Only `Chen017/FlClash` on `main` can publish. Build secrets are `ANDROID_KEYSTORE_BASE64` and `ANDROID_KEYSTORE_PASSWORD`. The `ANDROID_CERT_SHA256` repository variable holds the full SHA-256 of the permanent signing certificate. Restore the original key from the private backup if signing fails, since a different key prevents existing installations from updating. The workflow removes the key and local Gradle properties before packaging.

The package gate verifies the signer, package ID, Android version name and code, and the arm64 native library set. Published assets include `manifest.json`, `SHA256SUMS`, the APK and `complete-source.tar.gz` with the patched submodule source and its licenses. GitHub's generated tag archives omit submodule contents. The release stays a draft until every expected asset is present at its verified size.

- On patch conflicts, inspect the named patch and upstream revision, regenerate against the new base if necessary, and rerun the focused tests. Retry preparation after an upstream tag moves during a run.
- On build or packaging failure, inspect the Actions step and the short-lived failure artifact for the plan and available APK. A failed draft can leave a tag behind. The next successful attempt uses a higher build number, preserving Android upgrade order.
- If scheduled runs stop appearing, check whether GitHub suspended the fork's schedule and start a manual run on `main`.

### Regression map

| Personal behavior | Verification |
| --- | --- |
| Same app version with a newer Core build offers an update exactly once | `test/common/personal_update_test.dart` checks the version and build comparison. |
| The personal Android package has a separate signing identity and keeps the native plugin channel namespace | `test/core/protocol_contract_test.dart` checks the Dart/native namespace. The APK verifier checks package and signing identity. |
| Provider-scoped dialers use current proxy objects, respect global names and reject cycles | `component/proxydialer`, `adapter/provider` and `config` tests in `core.patch`. |
| Global XHTTP upload and download dependencies reject missing names and cycles before dialing | `config/personal_xhttp_dialer_test.go` in `core.patch` covers self and indirect cycles, missing names, explicit direct and valid routes. The connection-level path guard alone cannot see cycles across XHTTP's separate request contexts. |
| Upload/download can take separate routes, with explicit direct download and independent HTTP/2 receive windows | `adapter/outbound` and `transport/xhttp` tests in `core.patch`, plus the Xray loopback fixture. |
| A failed resumed handshake clears only the ticket it used, allowing a new handshake after a server restart | `transport/vless/encryption` tests in `core.patch`, plus the Xray loopback fixture. |
| Delay tests retain a valid measurement when the warm retry fails | `adapter` and `hub/route` tests in `core.patch`. |
| Android random-encrypted TCP splits the first write in both cold and resumed connections | `adapter/outbound` and `transport/vless/encryption` tests in `core.patch`. The Xray loopback fixture opts in to fragmentation on the build host. |

VPN permission and revoke, carrier IPv6, and device battery restrictions still require physical Android verification.

### Android NAT encrypted entry compatibility

On Android, raw TCP VLESS `random` encryption without TLS splits its first encrypted write into one byte and the remainder, with no fixed delay. This applies to both a cold handshake and the first application write on a resumed zero-RTT session; encryption, keys and server configuration stay unchanged. Other transports and desktop defaults are unchanged. A proxy can explicitly override this with `encryption-fragment: false` (disable) or `true` (enable). The override takes effect when the profile/provider reloads.

This addresses an observed access-path stall where TCP connects but an unsplit random first flight times out. It does not claim to identify the network device responsible. Only the first write of each new encrypted TCP connection is split. The initial 50 ms diagnostic gap was unnecessary in repeated direct-handshake tests and is not part of the implementation.
