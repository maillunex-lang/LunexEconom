"""Public-route checks never contact the external network in these tests."""
import io
import unittest
from unittest import mock
import urllib.error

import check_api_routes as routes


class FakeResponse:
    def __init__(self, status, content_type, data):
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.payload = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.payload[:limit]


class RouteTests(unittest.TestCase):
    def test_discovers_get_and_post_from_source(self):
        found = routes.discover_routes()
        self.assertIn("/health", found["GET"])
        self.assertIn("/city", found["GET"])
        self.assertIn("/auth/register", found["POST"])
        self.assertIn("/contracts/accept", found["POST"])
        self.assertIn("/build", found["POST"])

    def test_nginx_html_404_is_failure(self):
        response = FakeResponse(404, "text/html", b"<!DOCTYPE html><html>nginx 404</html>")
        with mock.patch.object(routes.urllib.request, "urlopen", return_value=response):
            result = routes.probe("https://example.test/api", "GET", "/city")
        self.assertFalse(result["ok"])
        self.assertIn("HTML", result["error"])

    def test_json_404_is_routed(self):
        response = FakeResponse(404, "application/json", b'{"error":"not_found"}')
        with mock.patch.object(routes.urllib.request, "urlopen", return_value=response):
            self.assertTrue(routes.probe("https://example.test/api", "GET", "/missing")["ok"])

    def test_http_error_json_401_is_routed(self):
        error = urllib.error.HTTPError(
            "https://example.test/api/wallet", 401, "Unauthorized",
            {"Content-Type": "application/json"}, io.BytesIO(b'{"error":"unauthorized"}'),
        )
        with mock.patch.object(routes.urllib.request, "urlopen", side_effect=error):
            self.assertTrue(routes.probe("https://example.test/api", "GET", "/wallet")["ok"])

    def test_post_probe_has_no_payload(self):
        def fake_open(request, timeout):
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.data, b"")
            self.assertTrue(request.full_url.endswith("/build"))
            return FakeResponse(400, "application/json", b'{"error":"invalid_body"}')
        with mock.patch.object(routes.urllib.request, "urlopen", side_effect=fake_open):
            self.assertTrue(routes.probe("https://example.test/api", "POST", "/build")["ok"])

    def test_network_failure_is_reported(self):
        with mock.patch.object(routes.urllib.request, "urlopen",
                               side_effect=urllib.error.URLError("offline")):
            self.assertFalse(routes.probe("https://example.test/api", "GET", "/health")["ok"])


if __name__ == "__main__":
    unittest.main()
