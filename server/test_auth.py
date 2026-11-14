"""Isolated account API unit tests; no live database or user accounts touched."""
import os
import tempfile
import unittest
from unittest.mock import patch

class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"LUNEX_AUTH_DB": os.path.join(self.temp.name, "auth.sqlite3")})
        self.env.start()
        import auth
        self.auth = auth
        self.previous_db_path = auth.DB_PATH
        auth.DB_PATH = os.path.join(self.temp.name, "auth.sqlite3")
        self.auth._attempts.clear()

    def tearDown(self):
        self.auth.DB_PATH = self.previous_db_path
        self.env.stop()
        self.temp.cleanup()

    def test_register_login_profile_logout(self):
        code, data = self.auth.register({"username":"FarmOwner", "email":"owner@example.test", "password":"safe-test-password"}, "client-a")
        self.assertEqual(code, 200)
        token = data["token"]
        self.assertEqual(self.auth.profile(token)[0], 200)
        self.assertEqual(self.auth.login({"identifier":"owner@example.test", "password":"safe-test-password"}, "client-b")[0], 200)
        self.assertEqual(self.auth.login({"identifier":"FarmOwner", "password":"incorrect"}, "client-c")[0], 401)
        self.assertEqual(self.auth.logout(token)[0], 200)
        self.assertEqual(self.auth.profile(token)[0], 401)

    def test_four_character_password(self):
        payload = {"username":"ShortPass","email":"short@example.test","password":"abcd"}
        status, result = self.auth.register(payload,"client-short")
        self.assertEqual(status,200)
        self.assertEqual(self.auth.login({"identifier":"ShortPass","password":"abcd"},"client-login")[0],200)
        self.assertEqual(self.auth.register({"username":"TooShort","email":"short2@example.test","password":"abc"},"client-short2")[0],400)

    def test_rate_limit_survives_memory_reset_and_process_restart(self):
        payload = {"identifier": "missing", "password": "bad"}
        for _ in range(12):
            self.assertEqual(self.auth.login(payload, "persistent-client")[0], 401)
        self.auth._attempts.clear()
        self.assertEqual(self.auth.login(payload, "persistent-client")[0], 429)
        with self.auth._db() as db:
            row = db.execute(
                "SELECT attempts FROM auth_attempts WHERE attempt_key=?",
                ("login:persistent-client",),
            ).fetchone()
            self.assertEqual(row[0], 13)

    def test_rate_limit_window_resets(self):
        payload = {"identifier": "missing", "password": "bad"}
        with patch.object(self.auth.time, "time", return_value=1_800_000_000):
            for _ in range(13):
                result = self.auth.login(payload, "window-client")[0]
            self.assertEqual(result, 429)
        with patch.object(self.auth.time, "time", return_value=1_800_000_601):
            self.assertEqual(self.auth.login(payload, "window-client")[0], 401)

    def test_rotate_and_logout_all(self):
        status, data = self.auth.register({"username":"RotateUser","email":"rotate@example.test","password":"abcd"},"r")
        self.assertEqual(status, 200)
        old = data["token"]
        other = self.auth.login({"identifier":"RotateUser","password":"abcd"},"r2")[1]["token"]
        status, rotated = self.auth.rotate_token(old)
        self.assertEqual(status, 200)
        self.assertEqual(self.auth.profile(old)[0], 401)
        self.assertEqual(self.auth.profile(rotated["token"])[0], 200)
        self.assertEqual(self.auth.logout_all(rotated["token"])[0], 200)
        self.assertEqual(self.auth.profile(other)[0], 401)
        self.assertEqual(self.auth.profile(rotated["token"])[0], 401)

    def test_email_verification_and_password_reset(self):
        from unittest.mock import patch
        status, data = self.auth.register({"username":"EmailUser","email":"email@example.test","password":"abcd"},"email-register")
        self.assertEqual(status, 200)
        old_token = data["token"]
        delivered = []
        def fake_email(_address, _subject, message):
            delivered.append(message.split(": ")[-1])
            return True
        with patch.object(self.auth, "_send_account_email", side_effect=fake_email):
            self.assertEqual(self.auth.request_verification({"email":"email@example.test"},"verify-client")[0], 200)
            verify_token = delivered.pop()
            self.assertEqual(self.auth.confirm_email({"token":verify_token},"confirm-client")[0], 200)
            self.assertEqual(self.auth.confirm_email({"token":verify_token},"confirm-client")[0], 400)
            self.assertEqual(self.auth.request_password_reset({"email":"email@example.test"},"reset-client")[0], 200)
            reset_token = delivered.pop()
        self.assertEqual(self.auth.reset_password({"token":reset_token,"password":"new4"},"reset-confirm")[0], 200)
        self.assertEqual(self.auth.profile(old_token)[0], 401)
        self.assertEqual(self.auth.login({"identifier":"EmailUser","password":"abcd"},"old")[0], 401)
        self.assertEqual(self.auth.login({"identifier":"EmailUser","password":"new4"},"new")[0], 200)
        self.assertEqual(self.auth.reset_password({"token":reset_token,"password":"abcd"},"replay")[0], 400)

    def test_email_fails_closed_without_delivery(self):
        from unittest.mock import patch
        self.auth.register({"username":"NoMail","email":"nomail@example.test","password":"abcd"},"create")
        with patch.object(self.auth, "_send_account_email", return_value=False):
            self.assertEqual(self.auth.request_password_reset({"email":"nomail@example.test"},"mail-fail")[0], 503)
        with self.auth._db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM auth_tokens").fetchone()[0], 0)

    def test_mailru_tls465_uses_secret_file_and_authentication(self):
        import tempfile
        from unittest.mock import patch, MagicMock
        with tempfile.TemporaryDirectory() as directory:
            secret = os.path.join(directory, "app-password")
            with open(secret, "w", encoding="utf-8") as handle:
                handle.write("test-only-password\\n")
            settings = {
                "LUNEX_SMTP_HOST": "smtp.mail.ru",
                "LUNEX_SMTP_PORT": "465",
                "LUNEX_SMTP_FROM": "lunexeconomy@mail.ru",
                "LUNEX_SMTP_USER": "lunexeconomy@mail.ru",
                "LUNEX_SMTP_PASSWORD_FILE": secret,
            }
            smtp = MagicMock()
            with patch.dict(os.environ, settings), patch.object(self.auth.smtplib, "SMTP_SSL") as connect:
                connect.return_value.__enter__.return_value = smtp
                self.assertTrue(self.auth._send_account_email("recipient@example.test", "Verification", "test code"))
                connect.assert_called_once()
                self.assertEqual(connect.call_args.args[:2], ("smtp.mail.ru", 465))
                smtp.login.assert_called_once_with("lunexeconomy@mail.ru", "test-only-password")
                smtp.send_message.assert_called_once()

    def test_mailru_missing_secret_fails_closed(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {
            "LUNEX_SMTP_HOST": "smtp.mail.ru",
            "LUNEX_SMTP_FROM": "lunexeconomy@mail.ru",
            "LUNEX_SMTP_USER": "lunexeconomy@mail.ru",
            "LUNEX_SMTP_PASSWORD_FILE": "/nonexistent/lunexeconom/mail-password",
        }):
            self.assertFalse(self.auth._send_account_email("recipient@example.test", "Test", "Code"))

    def test_duplicate_and_validation(self):
        payload = {"username":"Farmer123","email":"farmer@example.test","password":"safe-test-password"}
        self.assertEqual(self.auth.register(payload,"client-a")[0],200)
        self.assertEqual(self.auth.register(payload,"client-b")[0],409)
        self.assertEqual(self.auth.register({**payload,"username":"a"},"client-c")[0],400)

if __name__ == "__main__":
    unittest.main()
