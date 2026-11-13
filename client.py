"""Bounded, read-only adapter for the Mac app's existing local HTTP contract."""

from datetime import date
from http.client import HTTPConnection
import json
import math
import re


MAX_RESPONSE_BYTES = 65536
FIELDS = {
    "steps": ("value", "baseline_7d", "delta_vs_baseline"),
    "sleep": ("hours", "baseline_7d", "delta_vs_baseline"),
    "workouts": ("count", "total_minutes"),
    "heart_rate": ("average", "resting", "resting_baseline_7d", "resting_delta_vs_baseline"),
    "hrv": ("value", "baseline_7d", "delta_vs_baseline"),
}
UNITS = {
    "steps": "steps", "sleep": "hours",
    "workouts": {"count": "workouts", "total_minutes": "minutes"},
    "heart_rate": "beats/minute", "hrv": "milliseconds (SDNN)",
}


class AdapterError(Exception):
    """A safe fixed message; never includes server content, headers or credentials."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _read_local(path, token=None):
    # Literal loopback and HTTPConnection avoid DNS, proxy variables and automatic
    # redirects. Neither tool arguments nor settings can supply a URL or port.
    conn = HTTPConnection("127.0.0.1", 8765, timeout=5)
    try:
        headers = {"Accept": "application/json", "Connection": "close"}
        if token is not None:
            headers["X-Health-Analyzer-Token"] = token
        conn.request("GET", path, headers=headers)
        response = conn.getresponse()
        if response.status in (401, 403):
            raise AdapterError("unauthorized", "Check the local API token in Hermes plugin secret settings; never paste it into chat.")
        if response.status != 200:
            raise AdapterError("api_error", "The local app refused the request. Redirects are not followed.")
        if response.getheader("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise AdapterError("invalid_response", "The local app did not return JSON.")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise AdapterError("response_too_large", "The local response exceeded the summary size limit.")
        payload = json.loads(body)
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise AdapterError("dataset_unavailable", "The app could not supply a summary. Check the selected integration dataset in the app.")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise AdapterError("invalid_response", "The local app returned an invalid summary.")
        return data
    finally:
        conn.close()


def _numeric_groups(data, metrics):
    selected = {}
    for metric in metrics:
        source = data.get(metric)
        if source is None:
            source = {}
        if not isinstance(source, dict):
            raise AdapterError("invalid_response", "A requested metric group has an invalid shape.")
        values = {}
        for key in FIELDS[metric]:
            value = source.get(key)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise AdapterError("invalid_response", "A requested metric is not a finite number or null.")
            values[key] = value
        selected[metric] = {"units": UNITS[metric], **values}
    return selected


def _get_token():
    # Public profile-scoped API; never read credential stores or process environment.
    from agent.secret_scope import get_secret

    return get_secret("APPLE_HEALTH_ANALYZER_TOKEN")


class HealthTools:
    def __init__(self, ctx):
        self.ctx = ctx

    def _run(self, action, args):
        try:
            # Read on every call: revoked consent takes effect without a restart.
            if self.ctx.get_config("allow_health_access", default=False) is not True:
                raise AdapterError(
                    "consent_required",
                    "Health access is off. The user must opt in in this plugin's settings after reviewing model-provider sharing and chat-history retention. Do not enable it on their behalf.",
                )
            return json.dumps({"ok": True, "data": action(args)}, allow_nan=False)
        except AdapterError as error:
            return json.dumps({"ok": False, "error": {"code": error.code, "message": str(error)}})
        except Exception:
            # Network/parser/config exceptions can contain response bodies or a token.
            return json.dumps({"ok": False, "error": {
                "code": "request_failed",
                "message": "Could not read the local app. Check that it is running on this Mac with Local API enabled. No response content is included in this error.",
            }})

    def status(self, args, **kwargs):
        return self._run(self._status, args)

    def _status(self, args):
        if not isinstance(args, dict) or args:
            raise AdapterError("invalid_arguments", "Status accepts no arguments.")
        data = _read_local("/openclaw/status")
        if data.get("app") != "Health Data AI Analyzer" or type(data.get("dataset_loaded")) is not bool:
            raise AdapterError("invalid_response", "The local service did not identify as Health Data AI Analyzer.")
        version = data.get("app_version")
        if not isinstance(version, str) or not re.fullmatch(r"[0-9A-Za-z.+_-]{1,32}", version):
            version = "unknown"
        return {"app": "Health Data AI Analyzer", "app_version": version, "dataset_loaded": data["dataset_loaded"]}

    def daily_metrics(self, args, **kwargs):
        return self._run(self._daily_metrics, args)

    def _daily_metrics(self, args):
        if not isinstance(args, dict) or set(args) != {"date", "metrics"} or not _valid_date(args.get("date")):
            raise AdapterError("invalid_arguments", "Provide exactly date (YYYY-MM-DD) and metrics.")
        metrics = args["metrics"]
        if (
            not isinstance(metrics, list) or not 1 <= len(metrics) <= len(FIELDS)
            or any(not isinstance(m, str) or m not in FIELDS for m in metrics)
            or len(set(metrics)) != len(metrics)
        ):
            raise AdapterError("invalid_arguments", "Choose one or more distinct groups: steps, sleep, workouts, heart_rate, hrv.")
        token = _get_token()
        if not isinstance(token, str) or not token.strip():
            raise AdapterError("token_required", "The user must enter the Mac local API token in Hermes plugin secret settings, never in chat.")
        token = token.strip()
        if len(token) > 512 or not re.fullmatch(r"[A-Za-z0-9._~-]+", token):
            raise AdapterError("invalid_token", "The configured local API token has an invalid format.")
        data = _read_local("/openclaw/daily-brief?date=" + args["date"], token)
        # The app can fall back to the latest day when a date is absent.
        if data.get("date") != args["date"]:
            raise AdapterError("date_unavailable", "The app returned a different date. No health values were shared; choose a date present in your integration dataset.")
        return {
            "date": args["date"],
            "source": "User-selected Mac integration dataset; not live HealthKit data",
            "metrics": _numeric_groups(data, metrics),
            "notice": "Recorded summaries only; not medical advice. Null means unavailable. Tool results may be sent to your configured model provider and retained in Hermes conversation history.",
        }
