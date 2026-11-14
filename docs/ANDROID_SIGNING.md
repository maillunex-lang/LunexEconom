# Android signed APK: isolated release-candidate pipeline

Workflow: `.github/workflows/android-signed-candidate.yml`.

**Safety:** manual `workflow_dispatch` only, job restricted to `chatgpt/accounts-infra`, no VPS deployment, no GitHub Release, no `main` modification. The workflow **fails closed** if secrets are missing.

## One-time signing key setup

Create one permanent Android release signing keystore **locally in a trusted environment**, with a strong random password. Never reuse the debug keystore. The same keystore and alias must be kept for all subsequent updates of the installed Android app with package ID `ru.lunex.bashkiriahoneyoil`. Store an encrypted offline backup; loss of the signing key may prevent updating existing installations.

Use a PKCS12/JKS keystore with the **same password for the store and key** (this workflow explicitly checks equality). Example in a trusted terminal (do not paste actual passwords into commands or chat):

```sh
keytool -genkeypair -v -keystore lunexeconom-release.jks -alias lunexeconom-release -keyalg RSA -keysize 3072 -validity 10000 -storetype PKCS12
base64 -w0 lunexeconom-release.jks > lunexeconom-release.base64
```

Keep both files out of the repository. Upload the **single-line base64 contents** and passwords using the GitHub repository Settings → Secrets and variables → Actions UI, not chat or commit history.

Required GitHub Actions secrets:

| Name | Value |
| --- | --- |
| `LUNEX_ANDROID_KEYSTORE_BASE64` | Base64 of the release keystore |
| `LUNEX_ANDROID_KEYSTORE_PASSWORD` | Keystore password |
| `LUNEX_ANDROID_KEY_ALIAS` | Alias, e.g. `lunexeconom-release` |
| `LUNEX_ANDROID_KEY_PASSWORD` | Key password, identical to keystore password |

**Do not send secrets to ChatGPT or Termalin output.** For safety, avoid untrusted pull requests and third-party actions with write permissions. The workflow has `contents: read` only and never uploads the keystore.

## Running

GitHub → Actions → Android signed release candidate (isolated branch) → Run workflow → select `chatgpt/accounts-infra`. Download artifact `lunexeconom-signed-release-candidate`. Verify SHA256 and install on a physical Android phone; check landscape, safe area, login, building and world synchronization.

This workflow does not automatically publish or deploy the APK. Do not merge into main while Claude is working. Existing debug APKs may use a different signing certificate and cannot be upgraded in place with this release key; uninstalling a debug app can erase its local data. Confirm signing certificate migration before distributing broadly.

## Current status

Pipeline is configured but **no production signing key has been supplied** and **no signed release artifact has been generated or device-tested**.
