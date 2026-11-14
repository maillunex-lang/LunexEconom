# Mail.ru SMTP setup (LunexEconom)

Sender: `lunexeconomy@mail.ru`. Mail.ru official settings: `smtp.mail.ru:465`, implicit TLS, SMTP authentication. Use a **separate application password** with **send-only** access. Do not use the mailbox's main password.

## Prepare a secret on the VPS (manual step)

The game service must NOT be restarted while Claude works on `main`. These commands are for an authorized administrator, **after** confirming the service account and deploy plan. Run in a trusted interactive SSH terminal; **never paste the password into ChatGPT, a shell command argument, GitHub, logs or screenshots**.

```sh
sudo install -d -m 0750 -o root -g gamedev /etc/lunexeconom
sudo install -m 0600 -o gamedev -g gamedev /dev/null /etc/lunexeconom/mailru-app-password
sudo nano /etc/lunexeconom/mailru-app-password
```

Enter only the app password in the editor. The file must be readable by the game service account; replace `gamedev` with that account if different. The directory permits traversal only to root and the `gamedev` group. Prefer systemd LoadCredential when integrating with the production service.

## Non-secret configuration

```ini
LUNEX_SMTP_HOST=smtp.mail.ru
LUNEX_SMTP_PORT=465
LUNEX_SMTP_FROM=lunexeconomy@mail.ru
LUNEX_SMTP_USER=lunexeconomy@mail.ru
LUNEX_SMTP_PASSWORD_FILE=/etc/lunexeconom/mailru-app-password
```

The configuration is intentionally not enabled on the running service. A dedicated `EnvironmentFile` may contain only the non-secret values. The password file must not be copied to source, containers or build artifacts.

## Acceptance checks

1. Verify that the game service account can read the password file without printing its contents.
2. Confirm TLS certificate verification and network access to `smtp.mail.ru:465`.
3. Run an isolated email send with a test account and a recipient explicitly approved by the user.
4. Confirm delivery in inbox, inspect spam folder if necessary, and test one-time verification and password reset.
5. Only after approval and compatibility checks, enable the non-secret environment variables in the game service; never modify the active service during parallel Claude development.

If SMTP is not configured or mail delivery fails, the API responds with `email_unavailable` and does not return the code to the client.
