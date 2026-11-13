"""Synthetic contracts only. No app service, user files or real credentials."""

from contextlib import contextmanager
from http.client import HTTPConnection as RealHTTPConnection
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading
import unittest
from unittest.mock import patch

import client


class Context:
    consent = False

    def get_config(self, key, default=None):
        return self.consent


def brief():
    return {"success": True, "data": {
        "date": "2026-01-02",
        "steps": {"value": 4200, "baseline_7d": 4000.5, "delta_vs_baseline": 199.5},
        "sleep": {"hours": 7.25, "baseline_7d": None, "delta_vs_baseline": None, "bedtime": "PRIVATE"},
        "workouts": {"count": 1, "total_minutes": 30, "types": ["PRIVATE"]},
        "heart_rate": {"average": 70, "resting": 59, "resting_baseline_7d": 60, "resting_delta_vs_baseline": -1},
        "hrv": {"value": 42.5, "baseline_7d": 40, "delta_vs_baseline": 2.5, "recovery_status": "PRIVATE"},
        "signals": ["PRIVATE"], "context_summary": "PRIVATE", "extra": "PRIVATE",
    }}


@contextmanager
def server(payload, status=200, content_type="application/json", headers=None):
    requests = []
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.command, self.path, self.headers.get("X-Health-Analyzer-Token")))
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()

    def connection(host, port, timeout):
        if (host, port, timeout) != ("127.0.0.1", 8765, 5):
            raise AssertionError("Unexpected connection target")
        return RealHTTPConnection("127.0.0.1", httpd.server_port, timeout=5)

    try:
        with patch.object(client, "HTTPConnection", side_effect=connection):
            yield requests
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=2)


class HealthToolsTests(unittest.TestCase):
    def setUp(self):
        self.context = Context()
        self.context.consent = True
        self.tools = client.HealthTools(self.context)
        self.token = patch.object(client, "_get_token", return_value="synthetic-token-only")
        self.token.start()
        self.addCleanup(self.token.stop)

    def daily(self, **overrides):
        return json.loads(self.tools.daily_metrics({"date": "2026-01-02", "metrics": ["steps"], **overrides}))

    def test_default_off_and_revocation_make_no_request(self):
        for consent in (False, "true", 1, None):
            with self.subTest(consent=consent), patch.object(client, "HTTPConnection") as network, patch.object(client, "_get_token") as secret:
                self.context.consent = consent
                self.assertEqual(self.daily()["error"]["code"], "consent_required")
                self.assertEqual(json.loads(self.tools.status({}))["error"]["code"], "consent_required")
                network.assert_not_called()
                secret.assert_not_called()

    def test_status_is_sanitized_and_sends_no_token(self):
        payload = {"success": True, "data": {"app": "Health Data AI Analyzer", "app_version": "2.009", "dataset_loaded": False, "token_path": "PRIVATE", "available_metrics": ["PRIVATE"]}}
        with server(payload) as requests:
            result = json.loads(self.tools.status({}))
        self.assertEqual(result["data"], {"app": "Health Data AI Analyzer", "app_version": "2.009", "dataset_loaded": False})
        self.assertEqual(requests, [("GET", "/openclaw/status", None)])

    def test_selected_metrics_only_and_exact_authenticated_get(self):
        with server(brief()) as requests:
            result = self.daily()
        self.assertTrue(result["ok"])
        self.assertEqual(set(result["data"]["metrics"]), {"steps"})
        self.assertEqual(result["data"]["metrics"]["steps"]["value"], 4200)
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual(requests, [("GET", "/openclaw/daily-brief?date=2026-01-02", "synthetic-token-only")])

    def test_all_supported_groups_keep_units_nulls_and_zero(self):
        payload = brief()
        payload["data"]["steps"]["value"] = 0
        with server(payload):
            result = self.daily(metrics=list(client.FIELDS))
        metrics = result["data"]["metrics"]
        self.assertEqual(metrics["steps"]["value"], 0)
        self.assertIsNone(metrics["sleep"]["baseline_7d"])
        self.assertEqual(metrics["sleep"]["units"], "hours")
        self.assertEqual(metrics["workouts"]["total_minutes"], 30)
        self.assertEqual(metrics["heart_rate"]["resting"], 59)
        self.assertEqual(metrics["hrv"]["units"], "milliseconds (SDNN)")
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_missing_group_is_unknown_not_zero(self):
        payload = brief()
        del payload["data"]["steps"]
        with server(payload):
            self.assertIsNone(self.daily()["data"]["metrics"]["steps"]["value"])

    def test_latest_day_fallback_is_withheld(self):
        payload = brief()
        payload["data"]["date"] = "2026-01-03"
        with server(payload):
            result = self.daily()
        self.assertEqual(result["error"]["code"], "date_unavailable")
        self.assertNotIn("data", result)
        self.assertNotIn("4200", json.dumps(result))

    def test_invalid_arguments_never_connect(self):
        for args in ({"date": "2026-02-30"}, {"date": "20260102"}, {"date": "2026-01-02&url=https://example.invalid"}, {"metrics": []}, {"metrics": ["steps", "steps"]}, {"metrics": ["weight"]}, {"metrics": [None]}, {"metrics": "steps"}, {"url": "https://example.invalid"}):
            with self.subTest(args=args), patch.object(client, "HTTPConnection") as network:
                self.assertEqual(self.daily(**args)["error"]["code"], "invalid_arguments")
                network.assert_not_called()

    def test_missing_and_invalid_token_never_connect(self):
        for token in (None, "", "bad\r\nHeader: value", "x" * 513):
            with self.subTest(token=bool(token)), patch.object(client, "_get_token", return_value=token), patch.object(client, "HTTPConnection") as network:
                self.assertFalse(self.daily()["ok"])
                network.assert_not_called()

    def test_server_failures_do_not_echo_sensitive_body(self):
        for status, expected in ((401, "unauthorized"), (403, "unauthorized"), (500, "api_error"), (302, "api_error")):
            with self.subTest(status=status):
                with server(b"PRIVATE synthetic-token-only", status=status, headers={"Location": "https://example.invalid/collect"}) as requests:
                    result = self.daily()
                    self.assertEqual(len(requests), 1)
                self.assertEqual(result["error"]["code"], expected)
                self.assertNotIn("PRIVATE", json.dumps(result))
                self.assertNotIn("synthetic-token-only", json.dumps(result))

    def test_response_size_malformed_json_and_wrong_type(self):
        for body, content_type in ((b"x" * 65537, "application/json"), (b"PRIVATE not json", "application/json"), (b"{}", "text/html"), (b"[]", "application/json")):
            with self.subTest(size=len(body)):
                with server(body, content_type=content_type):
                    result = self.daily()
                self.assertFalse(result["ok"])
                self.assertNotIn("PRIVATE", json.dumps(result))

    def test_non_numeric_and_non_finite_values_fail_closed(self):
        for value in (True, "PRIVATE", {"secret": "PRIVATE"}, float("nan"), float("inf")):
            payload = brief()
            payload["data"]["steps"]["value"] = value
            with self.subTest(value=type(value).__name__):
                with server(payload):
                    result = self.daily()
                self.assertEqual(result["error"]["code"], "invalid_response")
                self.assertNotIn("PRIVATE", json.dumps(result))

    def test_dataset_error_and_connection_failure_are_actionable(self):
        with server({"success": False, "error": "PRIVATE"}):
            self.assertEqual(self.daily()["error"]["code"], "dataset_unavailable")
        with patch.object(client, "HTTPConnection", side_effect=OSError("PRIVATE synthetic-token-only")):
            result = self.daily()
        self.assertEqual(result["error"]["code"], "request_failed")
        self.assertNotIn("PRIVATE", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
