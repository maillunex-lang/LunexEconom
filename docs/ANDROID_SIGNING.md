# Android signed APK: release-candidate pipeline

Workflow: `.github/workflows/android-signed-candidate.yml`.

**Safety:** manual `workflow_dispatch` only; the job runs from `main` (the former `chatgpt/accounts-infra` restriction was removed after the merge: that branch can be deleted, which would have made the job unrunnable). It uses the GitHub Environment `android-signing` (create it under Settings → Environments, add **required reviewers** and move the four secrets there so only approved runs can read them), has `contents: read`, no VPS deployment, no GitHub Release. The workflow **fails closed** if secrets are missing.

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

GitHub → Actions → Android signed release candidate → Run workflow (branch `main`). Download artifact `lunexeconom-signed-release-candidate`. Verify SHA256 and install on a physical Android phone; check landscape, safe area, login, building and world synchronization.

This workflow does not automatically publish or deploy the APK. Existing debug APKs may use a different signing certificate and cannot be upgraded in place with this release key; uninstalling a debug app can erase its local data. Confirm signing certificate migration before distributing broadly.

## Version numbers
Every CI build (debug and release candidate) is stamped by `ops/stamp_build.py` with a unique, increasing `versionCode` equal to the commit count (`git rev-list --count HEAD`) and `versionName` `0.3.<count>`. The same number is written to `client/build_info.json`, which the in-game updater reads as the installed version (it used to be a hard-coded constant). The workflows fail if `aapt` reports a different `versionCode` than the stamped one.

## Verifying the pipeline without the real key
Run the workflow with **pipeline_check_with_temporary_key = true**. It generates a throw-away key on the runner, builds, signs and verifies the release APK (package ID, ABIs, versionCode, not debug-signed, not debuggable) and uploads an artifact named `lunexeconom-release-pipeline-check-TEST-KEY-NOT-A-RELEASE`. That artifact must never be distributed; it only proves that the pipeline works.

## Current status

Pipeline verified end-to-end in pipeline-check mode (see docs/PROGRESS.md); **no production signing key has been supplied** and **no real signed release artifact has been generated or device-tested**.
