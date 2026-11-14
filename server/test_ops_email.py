"""Offline SMTP integration and SQLite mail-throttling regression."""
import os
import socketserver
import threading
import unittest
from unittest import mock

import ops_email
import sqlite_util


class FakeSmtpHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b"220 localhost fake SMTP\r\n")
        data_mode = False
        lines = []
        while True:
            line = self.rfile.readline()
            if not line:
                break
            if data_mode:
                if line == b".\r\n":
                    self.server.messages.append(b"".join(lines).decode("utf-8", "replace"))
                    lines.clear()
                    data_mode = False
                    self.wfile.write(b"250 accepted\r\n")
                else:
                    lines.append(line)
                continue
            command = line.upper().split(b" ", 1)[0].strip()
            if command in (b"EHLO", b"HELO"):
                self.wfile.write(b"250-localhost\r\n250 HELP\r\n")
            elif command in (b"MAIL", b"RCPT", b"RSET", b"NOOP"):
                self.wfile.write(b"250 OK\r\n")
            elif command == b"DATA":
                self.wfile.write(b"354 send message\r\n")
                data_mode = True
            elif command == b"QUIT":
                self.wfile.write(b"221 Bye\r\n")
                break
            else:
                self.wfile.write(b"502 not supported\r\n")


class SmtpTests(unittest.TestCase):
    def test_local_fake_server_receives_plain_text_without_external_network(self):
        with socketserver.TCPServer(("127.0.0.1", 0), FakeSmtpHandler) as server:
            server.messages = []
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            settings = {
                "LUNEX_SMTP_HOST": "127.0.0.1",
                "LUNEX_SMTP_PORT": str(server.server_address[1]),
                "LUNEX_SMTP_FROM": "noreply@example.test",
                "LUNEX_SMTP_TLS": "off",
            }
            try:
                with mock.patch.dict(os.environ, settings, clear=True):
                    self.assertTrue(ops_email.send_smtp("recipient@example.test", "Test code", "Code: TEST123"))
                self.assertEqual(len(server.messages), 1)
                message = server.messages[0]
                self.assertIn("Content-Type: text/plain", message)
                self.assertIn("Subject: Test code", message)
                self.assertNotIn("text/html", message)
            finally:
                server.shutdown()
                thread.join(timeout=2)

    def test_disabled_without_configuration(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ops_email.send_smtp("recipient@example.test", "Test", "Code"))

    def test_plaintext_remote_refused(self):
        with mock.patch.dict(os.environ, {
            "LUNEX_SMTP_HOST": "smtp.example.test",
            "LUNEX_SMTP_FROM": "noreply@example.test",
            "LUNEX_SMTP_TLS": "off",
            "LUNEX_SMTP_PASSWORD": "placeholder",
            "LUNEX_SMTP_USER": "noreply@example.test",
        }, clear=True):
            self.assertFalse(ops_email.send_smtp("recipient@example.test", "Test", "Code"))


class ThrottleTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite_util.open_db(":memory:")

    def tearDown(self):
        self.db.close()

    def test_address_cooldown_and_hourly_cap(self):
        now = 1_800_000_000
        self.assertTrue(ops_email.reserve(self.db, "?", "some@example.test", "one", now))
        self.assertFalse(ops_email.reserve(self.db, "?", "some@example.test", "two", now + 59))
        self.assertTrue(ops_email.reserve(self.db, "?", "some@example.test", "two", now + 60))
        for i in range(3):
            self.assertTrue(ops_email.reserve(self.db, "?", "some@example.test", "u" + str(i), now + 121 + 61 * i))
        self.assertFalse(ops_email.reserve(self.db, "?", "some@example.test", "another", now + 500))
        self.assertTrue(ops_email.reserve(self.db, "?", "some@example.test", "another", now + 3601))

    def test_ip_limit_across_distinct_addresses(self):
        now = 1_800_000_000
        for i in range(20):
            self.assertTrue(ops_email.reserve(self.db, "?", "user%d@example.test" % i, "shared", now))
        self.assertFalse(ops_email.reserve(self.db, "?", "new@example.test", "shared", now + 1))

    def test_reservations_store_only_address_hashes(self):
        self.assertTrue(ops_email.reserve(self.db, "?", "private@example.test", "private-ip", 12345))
        rows = self.db.execute("SELECT key FROM ops_email_throttle").fetchall()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(len(row[0]), 64)
            self.assertNotIn("private", row[0])


if __name__ == "__main__":
    unittest.main()
