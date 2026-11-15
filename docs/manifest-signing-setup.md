# V2 manifest signing setup (staged, no publication)

This branch introduces an isolated manifest signing helper and a manual verification workflow. No release workflow or production server is changed.

- `tools/sign_manifest_env.py` reads `MANIFEST_SIGNING_KEY` from its process environment, rejects missing/non-RSA-4096 keys and noncanonical JSON, refuses to overwrite a signature, signs RSA-PKCS1v15/SHA256 and verifies the detached signature against a pinned public key.
- `manifest-signing-check.yml` runs only on `main`, uses the `manifest-signing` environment, and does not publish artifacts or releases.
- Tests generate ephemeral RSA keys and use no real secrets.

**Blocked prerequisites:** GitHub API currently returns 403 when attempting environment configuration. The new environment was created manually and restricted to `main`, but `MANIFEST_SIGNING_KEY` is not uploaded. The public key is not pinned in `client/config/update_public.pem`. The workflow is expected to fail closed until both are provisioned.

**Security caveat:** The private key is made available to the GitHub-hosted runner as a process environment variable during verification. It is not written as a PEM file, but it exists in runner memory and in the job environment. This is different from the older offline-only signing policy in `docs/release.md`, and requires owner approval and an explicit policy update before production use. GitHub Actions cannot securely create and then persist its own secret with only the default `GITHUB_TOKEN`.

**Integration not yet done:** The production publishing workflow still does not create or sign `update.json`. Do not claim automatic update signing or publish a release until the key is provisioned, the public key is pinned, and the publishing workflow has been reviewed and integrated. Run `python -m unittest discover -s tools/tests -p test_manifest_env_signing.py -v` and existing release tests before merging.
