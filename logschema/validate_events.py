#!/usr/bin/env python3
"""
ProGallery logging schema validator (dependency-free).

Yeh events ko ProGallery Logging Spec v1.0 ke common envelope ke against check karta hai:
  * required fields present
  * event_name = object_action snake_case
  * enums (platform, log_level, release_channel, network_type)
  * timestamp ISO 8601 UTC
  * PII leak check (email / raw file paths)

Usage:
  python logging/validate_events.py <file.jsonl>     # ek JSONL file validate karo
  python logging/validate_events.py --selftest       # app ke sample events validate karo (CI)

Exit code 0 = pass, 1 = fail.
"""

import os
import re
import sys
import json

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "event_schema.json")

REQUIRED = [
    "event_name", "schema_version", "timestamp", "session_id",
    "platform", "app_version", "os", "device_model", "screen_or_route", "log_level",
    "severity", "category", "app_id", "environment",
]
SEVERITIES = {"trace", "debug", "info", "warn", "error", "fatal"}
CATEGORIES = {
    "application", "error", "security", "performance", "user_activity",
    "infrastructure", "api_network", "database", "audit", "analytics",
    "background_job", "debug_trace",
}
ENUMS = {
    "platform": {"windows", "linux", "macos", "web", "android", "ios"},
    "log_level": SEVERITIES,
    "severity": SEVERITIES,
    "category": CATEGORIES,
    "environment": {"production", "staging", "development"},
    "release_channel": {"production", "beta", "dev"},
    "network_type": {"wifi", "4g", "5g", "ethernet", "offline", "usb", "unknown"},
}
NAME_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
VER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
TS_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
PII_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
    r"|[A-Za-z]:\\[^\s\"]+"
    r"|(?<![\w:])/(?:Users|home|tmp|var|mnt|media|sdcard|opt)/[^\s\"]*"
)


def validate_event(ev):
    errs = []
    if not isinstance(ev, dict):
        return ["event is not a JSON object"]
    for f in REQUIRED:
        if f not in ev or ev[f] in ("", None):
            errs.append("missing required field: %s" % f)
    if "event_name" in ev and not NAME_RE.match(str(ev["event_name"])):
        errs.append("event_name not object_action snake_case: %r" % ev["event_name"])
    if "schema_version" in ev and not VER_RE.match(str(ev["schema_version"])):
        errs.append("schema_version not semver: %r" % ev["schema_version"])
    for f, allowed in ENUMS.items():
        if f in ev and ev[f] not in allowed:
            errs.append("bad enum %s=%r (allowed: %s)" % (f, ev[f], sorted(allowed)))
    if "timestamp" in ev and not TS_RE.match(str(ev["timestamp"])):
        errs.append("timestamp not ISO 8601 UTC: %r" % ev["timestamp"])
    m = PII_RE.search(json.dumps(ev, ensure_ascii=False))
    if m:
        errs.append("PII leak detected: %r" % m.group(0)[:48])
    return errs


def validate_events(events):
    problems = []
    for i, ev in enumerate(events):
        for e in validate_event(ev):
            problems.append("event[%d] %s: %s" % (i, ev.get("event_name", "?"), e))
    return problems


def _load_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def selftest():
    """App ke sample events validate karo (CI gate)."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import PhoneMirror  # noqa: WPS433
    events = PhoneMirror.sample_events()
    problems = validate_events(events)
    print("selftest: %d sample events validated against schema v%s"
          % (len(events), PhoneMirror.LOG_SCHEMA_VERSION))
    if problems:
        print("FAIL:")
        for p in problems:
            print("  -", p)
        return 1
    print("PASS: all events conform to the ProGallery logging schema")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--selftest":
        return selftest()
    path = argv[0]
    if not os.path.isfile(path):
        print("file not found: %s" % path)
        return 1
    events = _load_jsonl(path)
    problems = validate_events(events)
    print("%d events checked from %s" % (len(events), path))
    if problems:
        print("FAIL:")
        for p in problems:
            print("  -", p)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
