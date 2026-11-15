# V2 manifest signing setup (staged, no publication)

This branch introduces an isolated manifest signing helper and a manual verification workflow. No release workflow or production server is changed.

- `tools/sign_manifest_env.py` reads `MANIFEST_SIGNING_KEY` from its process environment, rejects missing/non-RSA-4096 keys and noncanonical JSON, refuses to overwrite a signature, signs RSA-PKCS1v15/SHA256 and verifies the detached signature against a pinned public key.
- `manifest-signing-check.yml` runs only on `main`, uses the `manifest-signing` environment, and does not publish artifacts or releases.
- Tests generate ephemeral RSA keys and use no real secrets.

**Состояние (2026-11-15):** окружение `manifest-signing` создано и ограничено веткой `main`, секрет `MANIFEST_SIGNING_KEY` (новый RSA-4096) загружен, публичная часть закреплена в `client/config/update_public.pem` (SHA-256 DER `280770e34e420e87bc44c7d8018efd2127690027afc290c020cec9c9d37d97dd`). Ручные одобрения не требуются по решению владельца. Проверка соответствия секрета и публичного ключа: workflow «Verify manifest signing».

**Security caveat:** The private key is made available to the GitHub-hosted runner as a process environment variable during verification. It is not written as a PEM file, but it exists in runner memory and in the job environment. This is different from the older offline-only signing policy in `docs/release.md`, and принято владельцем (окружение только для ветки `main`, без ручных одобрений). GitHub Actions cannot securely create and then persist its own secret with only the default `GITHUB_TOKEN`.

**Integration not yet done:** The production publishing workflow still does not create or sign `update.json`. Do not claim automatic update signing or publish a release until the key is provisioned, the public key is pinned, and the publishing workflow has been reviewed and integrated. Run `python -m unittest discover -s tools/tests -p test_manifest_env_signing.py -v` and existing release tests before merging.
