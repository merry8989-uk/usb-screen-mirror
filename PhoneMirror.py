#!/usr/bin/env python3
"""
PhoneMirror  -  Screen Mirror for Android, powered by scrcpy.

Ek Windows + Python GUI jo scrcpy ko wrap karta hai.
Features:
  * USB ya Wi-Fi (TCP/IP) connection
  * Multi-device: ek saath do ya zyada phone (har ek ka apna session)
  * Screen recording: session ko mp4 file me save
  * Camera mirroring: phone ka camera PC par (scrcpy 2.2+)
  * Low-latency presets, clear audio (Opus), input control
  * Auto-reconnect per device
  * Diagnostics: structured event logging (ProGallery Logging Spec v1.0) +
    logs export (.txt/.md/.json/.jsonl/.csv/.xlsx), email compose (pre-filled),
    copy, refresh, clean. On/off setting (default ON).

Yeh scrcpy ka engine use karta hai (hardware encode + USB transport).

Sirf Python 3 + scrcpy + adb chahiye. Tkinter Python ke saath aata hai.
(.xlsx export ke liye optional: pip install openpyxl)

Run:  python PhoneMirror.py
"""

import os
import re
import sys
import csv
import json
import time
import random
import hashlib
import shutil
import platform
import datetime
import subprocess
import threading
import queue
import webbrowser
import traceback
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from urllib.parse import quote

APP_TITLE = "PhoneMirror  -  Screen Mirror (scrcpy wrapper)"
APP_VERSION = "1.5.0"
DIAG_EMAIL = "br19shc39@gmail.com"

IS_WINDOWS = (os.name == "nt")
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".phonemirror")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


# --------------------------------------------------------------------------- #
#  Config persistence (diagnostics on/off yaad rakhne ke liye)
# --------------------------------------------------------------------------- #
def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
#  Structured logging  -  ProGallery Logging Spec v1.0
#  (common envelope, log levels, sampling, retention, PII redaction)
# --------------------------------------------------------------------------- #
LOG_SCHEMA_VERSION = "1.0.0"
LOG_MAX_EVENTS = 5000           # retention: memory/export me max events
LOG_RETENTION_DAYS = 7          # retention: isse purane events drop
LOG_SAMPLE_INFO_RATE = 1.0      # info/debug sample rate (errors/warn always 100%)
LOG_RELEASE_CHANNEL = "production"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_WINPATH_RE = re.compile(r"[A-Za-z]:\\[^\s\"]+")
_POSIXPATH_RE = re.compile(r"(?<![\w:])/(?:Users|home|tmp|var|mnt|media|sdcard|opt)/[^\s\"]*")


def redact(text):
    """PII redaction - app aur web ke liye identical rules.
    Emails aur file paths hataata hai (spec Part F)."""
    if text is None:
        return ""
    s = str(text)
    s = _EMAIL_RE.sub("<email>", s)
    s = _WINPATH_RE.sub("<path>", s)
    s = _POSIXPATH_RE.sub("<path>", s)
    return s


def salted_hash(value, salt):
    """user_id / device id sirf salted hash ke roop me (raw identifier nahi)."""
    if not value:
        return ""
    return "id_" + hashlib.sha256((salt + str(value)).encode("utf-8")).hexdigest()[:12]


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rand_hex(n=16):
    return "".join(random.choice("0123456789abcdef") for _ in range(n))


def _platform_enum():
    s = platform.system().lower()
    if s.startswith("win"):
        return "windows"
    if s == "darwin":
        return "macos"
    return s or "unknown"


def _env_os():
    return "%s %s" % (platform.system(), platform.release())


def _device_model():
    return platform.machine() or platform.node() or "unknown"


def make_event(event_name, log_level, screen_or_route, session_id,
               attempt_id=None, user_id=None, network_type=None, props=None):
    """ProGallery common event envelope (Part B)."""
    ev = {
        "event_name": event_name,
        "schema_version": LOG_SCHEMA_VERSION,
        "timestamp": utc_now(),
        "session_id": session_id,
        "platform": _platform_enum(),
        "app_version": APP_VERSION,
        "os": _env_os(),
        "device_model": _device_model(),
        "screen_or_route": screen_or_route,
        "log_level": log_level,
        "release_channel": LOG_RELEASE_CHANNEL,
    }
    if attempt_id:
        ev["attempt_id"] = attempt_id
    if user_id:
        ev["user_id"] = user_id
    if network_type:
        ev["network_type"] = network_type
    if props:
        for k, v in props.items():
            ev[k] = redact(v) if isinstance(v, str) else v
    return ev


class StructuredLogger:
    """Event envelope + log levels + sampling + retention."""

    def __init__(self, session_id, user_id=""):
        self.session_id = session_id
        self.user_id = user_id
        self.events = []
        self.attempt_seq = 0

    def new_attempt_id(self, prefix="att"):
        self.attempt_seq += 1
        return "%s_%04d" % (prefix, self.attempt_seq)

    def log(self, event_name, log_level, screen_or_route,
            attempt_id=None, props=None, network_type=None):
        # sampling: errors/warn hamesha 100%, info/debug sampled
        if log_level in ("debug", "info") and LOG_SAMPLE_INFO_RATE < 1.0:
            if random.random() > LOG_SAMPLE_INFO_RATE:
                return None
        ev = make_event(event_name, log_level, screen_or_route, self.session_id,
                        attempt_id=attempt_id, user_id=self.user_id,
                        network_type=network_type, props=props)
        self.events.append(ev)
        self._enforce_retention()
        return ev

    def _enforce_retention(self):
        if len(self.events) > LOG_MAX_EVENTS:
            del self.events[:len(self.events) - LOG_MAX_EVENTS]
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=LOG_RETENTION_DAYS)
        keep = []
        for e in self.events:
            try:
                ts = datetime.datetime.strptime(e["timestamp"], "%Y-%m-%dT%H:%M:%SZ")
                ts = ts.replace(tzinfo=datetime.timezone.utc)
                if ts >= cutoff:
                    keep.append(e)
            except Exception:  # noqa: BLE001
                keep.append(e)
        self.events = keep

    def to_jsonl(self):
        return "\n".join(json.dumps(e, ensure_ascii=False) for e in self.events)


def sample_events(session_id="sess_sample"):
    """CI validation ke liye sample events (schema ke against check hote hain)."""
    lg = StructuredLogger(session_id)
    lg.log("session_start", "info", "Main", props={"start_type": "cold"})
    lg.log("screen_view", "info", "Diagnostics", props={"screen_name": "Diagnostics", "previous_screen": "Main"})
    lg.log("device_state_resolved", "info", "Main", props={"state": "authorized", "device_count": 1})
    lg.log("mirror_requested", "info", "Main", attempt_id="att_0001", props={"device_count": 1, "video_source": "display"})
    lg.log("mirror_result", "info", "Main", attempt_id="att_0001", props={"outcome": "success"})
    lg.log("adb_command", "debug", "Main", props={"command": "adb devices", "outcome": "success", "latency_ms": 12})
    lg.log("error_state_shown", "error", "Main", props={"error_code": "scrcpy_missing", "message_key": "scrcpy_not_found"})
    lg.log("export_saved", "info", "Diagnostics", props={"format": "jsonl", "outcome": "success"})
    return lg.events


# --------------------------------------------------------------------------- #
#  Executable / device discovery
# --------------------------------------------------------------------------- #
def find_executable(name):
    """PATH aur common install locations me exe dhoondo."""
    found = shutil.which(name)
    if found:
        return found
    candidates = []
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        profile = os.environ.get("USERPROFILE", "")
        candidates += [
            os.path.join(local, "Microsoft", "WinGet", "Links", name + ".exe"),
            os.path.join(profile, "scoop", "shims", name + ".exe"),
            os.path.join(profile, "chocolatey", "bin", name + ".exe"),
            r"C:\scrcpy\%s.exe" % name,
            r"C:\Program Files\scrcpy\%s.exe" % name,
            r"C:\Program Files (x86)\scrcpy\%s.exe" % name,
        ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def run_adb(adb_path, args, timeout=20):
    """adb command chalao. Returns (ok, output_text)."""
    try:
        proc = subprocess.run(
            [adb_path] + args, capture_output=True, text=True,
            timeout=timeout, creationflags=CREATE_NO_WINDOW,
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, out


def list_devices(adb_path):
    """adb devices -l se device list nikalo. Returns (list, error)."""
    try:
        proc = subprocess.run(
            [adb_path, "devices", "-l"],
            capture_output=True, text=True, timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        return [], "adb nahi mila."
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)

    if proc.returncode != 0:
        return [], (proc.stderr or "adb devices fail hua.").strip()

    devices = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        model = ""
        for token in parts[2:]:
            if token.startswith("model:"):
                model = token.split(":", 1)[1].replace("_", " ")
        label = serial
        if model:
            label = "%s  (%s)" % (model, serial)
        if state != "device":
            label += "   [%s]" % state
        devices.append({"serial": serial, "state": state, "model": model, "label": label})
    return devices, None


def detect_phone_ip(adb_path, serial):
    """USB se jude phone ka Wi-Fi IP nikalo. Returns ip string or None."""
    base = ["-s", serial] if serial else []
    ok, out = run_adb(adb_path, base + ["shell", "ip", "route"])
    if ok:
        m = re.search(r"src\s+(\d+\.\d+\.\d+\.\d+)", out)
        if m:
            return m.group(1)
    ok2, out2 = run_adb(adb_path, base + ["shell", "ip", "-f", "inet", "addr", "show", "wlan0"])
    if ok2:
        m2 = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", out2)
        if m2:
            return m2.group(1)
    return None


# --------------------------------------------------------------------------- #
#  Presets
# --------------------------------------------------------------------------- #
PRESETS = {
    "Low Latency": {
        "max_size": 1024, "bitrate": "8M", "max_fps": 60, "codec": "h264",
        "audio": True, "audio_codec": "opus", "audio_bitrate": "128K", "audio_buffer": 25,
        "desc": "Sabse tez. 1024px, 8 Mbps, 60fps, audio 128K. Gaming / interactive.",
    },
    "Low Phone Load": {
        "max_size": 800, "bitrate": "4M", "max_fps": 30, "codec": "h264",
        "audio": True, "audio_codec": "opus", "audio_bitrate": "96K", "audio_buffer": 50,
        "desc": "Phone par sabse kam load + kam heat. 800px, 4 Mbps, 30fps.",
    },
    "Balanced": {
        "max_size": 1280, "bitrate": "8M", "max_fps": 60, "codec": "h264",
        "audio": True, "audio_codec": "opus", "audio_bitrate": "128K", "audio_buffer": 50,
        "desc": "Rozana kaam. 1280px, 8 Mbps, 60fps, clear audio.",
    },
    "High Quality": {
        "max_size": 1920, "bitrate": "16M", "max_fps": 60, "codec": "h265",
        "audio": True, "audio_codec": "opus", "audio_bitrate": "256K", "audio_buffer": 100,
        "desc": "Sharp picture + best audio. 1920px, 16 Mbps, 256K audio.",
    },
}


def build_command(scrcpy_path, serial, s):
    """Settings dict se scrcpy command line banao."""
    cmd = [scrcpy_path]
    if serial:
        cmd += ["--serial", serial]
        cmd += ["--window-title", "PhoneMirror - %s" % serial]

    src = s.get("video_source", "display")
    if src == "camera":
        cmd += ["--video-source", "camera"]
        cmd += ["--camera-facing", s.get("camera_facing", "back")]
        cmd += ["--camera-size", s.get("camera_size", "1280x720")]
        cmd += ["--camera-fps", str(s.get("camera_fps", 30))]
    else:
        cmd += ["--max-size", str(s["max_size"])]

    cmd += ["--video-bit-rate", s["bitrate"]]
    cmd += ["--max-fps", str(s["max_fps"])]
    cmd += ["--video-codec", s["codec"]]
    cmd += ["--video-buffer", "0", "--display-buffer", "0"]
    cmd += ["--render-driver", "opengl"]

    if s.get("audio"):
        cmd += ["--audio-codec", s.get("audio_codec", "opus")]
        cmd += ["--audio-bit-rate", s.get("audio_bitrate", "128K")]
        cmd += ["--audio-buffer", str(s.get("audio_buffer", 50))]
    else:
        cmd += ["--no-audio"]

    if s.get("record") and s.get("record_path"):
        cmd += ["--record", s["record_path"]]

    if s.get("no_control"):
        cmd += ["--no-control"]
    else:
        kb = s.get("keyboard_mode", "default")
        if kb and kb != "default":
            cmd += ["--keyboard", kb]

    if s.get("turn_screen_off"):
        cmd += ["--turn-screen-off"]
    if s.get("stay_awake"):
        cmd += ["--stay-awake"]
    if s.get("always_on_top"):
        cmd += ["--always-on-top"]
    if s.get("print_fps"):
        cmd += ["--print-fps"]
    return cmd


# --------------------------------------------------------------------------- #
#  Diagnostics report rendering
# --------------------------------------------------------------------------- #
def _event_lines(rep, limit=200):
    evs = rep.get("events", [])
    out = []
    for e in evs[-limit:]:
        out.append("  %s  %-5s  %-22s  %s" % (
            e.get("timestamp", ""), e.get("log_level", ""),
            e.get("event_name", ""), e.get("screen_or_route", "")))
    return out


def render_txt(rep):
    L = []
    L.append("PhoneMirror diagnostics report")
    L.append("Generated: %s" % rep["generated_at"])
    L.append("App: %s v%s" % (rep["app"]["name"], rep["app"]["version"]))
    L.append("Diagnostics collection: %s" % ("ON" if rep["diagnostics_enabled"] else "OFF"))
    L.append("Log schema: %s" % rep.get("logging", {}).get("schema_version", ""))
    L.append("")
    L.append("== Environment ==")
    for k, v in rep["environment"].items():
        L.append("  %-10s %s" % (k + ":", v))
    L.append("")
    L.append("== Tools ==")
    for k, v in rep["tools"].items():
        L.append("  %-16s %s" % (k + ":", v))
    L.append("")
    L.append("== Devices (%d) ==" % len(rep["devices"]))
    for d in rep["devices"]:
        L.append("  %s   [%s]   %s" % (d["serial"], d["state"], d["model"]))
    L.append("")
    L.append("== Settings ==")
    for k, v in rep["settings"].items():
        L.append("  %-18s %s" % (k + ":", v))
    L.append("")
    L.append("== Structured events (%d) ==" % len(rep.get("events", [])))
    if not rep.get("events"):
        L.append("  (kuch nahi - diagnostics OFF ho sakta hai)")
    L.extend(_event_lines(rep))
    L.append("")
    L.append("== Log (%d lines) ==" % len(rep["log"]))
    for e in rep["log"]:
        pref = ("[%s] " % e["serial"]) if e.get("serial") else ""
        L.append("  %s  %s%s" % (e["time"], pref, e["text"]))
    return "\n".join(L)


def render_md(rep):
    L = []
    L.append("# PhoneMirror diagnostics report")
    L.append("")
    L.append("- **Generated:** %s" % rep["generated_at"])
    L.append("- **App:** %s v%s" % (rep["app"]["name"], rep["app"]["version"]))
    L.append("- **Diagnostics:** %s" % ("ON" if rep["diagnostics_enabled"] else "OFF"))
    L.append("- **Log schema:** %s" % rep.get("logging", {}).get("schema_version", ""))
    L.append("")
    L.append("## Environment")
    L.append("")
    L.append("| Key | Value |")
    L.append("|---|---|")
    for k, v in rep["environment"].items():
        L.append("| %s | %s |" % (k, v))
    L.append("")
    L.append("## Tools")
    L.append("")
    L.append("| Key | Value |")
    L.append("|---|---|")
    for k, v in rep["tools"].items():
        L.append("| %s | %s |" % (k, str(v).replace("|", "/")))
    L.append("")
    L.append("## Devices (%d)" % len(rep["devices"]))
    L.append("")
    L.append("| Serial | State | Model |")
    L.append("|---|---|---|")
    for d in rep["devices"]:
        L.append("| %s | %s | %s |" % (d["serial"], d["state"], d["model"]))
    L.append("")
    L.append("## Settings")
    L.append("")
    L.append("| Setting | Value |")
    L.append("|---|---|")
    for k, v in rep["settings"].items():
        L.append("| %s | %s |" % (k, v))
    L.append("")
    L.append("## Structured events (%d)" % len(rep.get("events", [])))
    L.append("")
    L.append("| timestamp | level | event_name | screen_or_route |")
    L.append("|---|---|---|---|")
    for e in rep.get("events", [])[-200:]:
        L.append("| %s | %s | %s | %s |" % (e.get("timestamp", ""), e.get("log_level", ""),
                                            e.get("event_name", ""), e.get("screen_or_route", "")))
    L.append("")
    L.append("## Log (%d lines)" % len(rep["log"]))
    L.append("")
    L.append("```")
    for e in rep["log"]:
        pref = ("[%s] " % e["serial"]) if e.get("serial") else ""
        L.append("%s  %s%s" % (e["time"], pref, e["text"]))
    L.append("```")
    return "\n".join(L)


def render_email_body(rep, attach_path, max_lines=40, limit=1800):
    lines = [
        "PhoneMirror diagnostics report",
        "Generated: %s" % rep["generated_at"],
        "App: %s v%s" % (rep["app"]["name"], rep["app"]["version"]),
        "Diagnostics: %s" % ("ON" if rep["diagnostics_enabled"] else "OFF"),
        "Log schema: %s" % rep.get("logging", {}).get("schema_version", ""),
        "",
        "OS: %s" % rep["environment"].get("os", ""),
        "Python: %s" % rep["environment"].get("python", ""),
        "scrcpy: %s" % rep["tools"].get("scrcpy_version", ""),
        "adb: %s" % rep["tools"].get("adb_version", ""),
        "Devices: %d" % len(rep["devices"]),
        "Structured events: %d" % len(rep.get("events", [])),
        "",
        "--- Log (last %d lines) ---" % max_lines,
    ]
    for e in rep["log"][-max_lines:]:
        pref = ("[%s] " % e["serial"]) if e.get("serial") else ""
        lines.append("%s %s%s" % (e["time"], pref, e["text"]))
    lines.append("")
    lines.append("(Poora report file attach kiya gaya hai: %s)" % os.path.basename(attach_path))
    body = "\n".join(lines)
    if len(body) > limit:
        body = body[:limit] + "\n...(truncated - poora report file me hai)"
    return body


def write_xlsx(rep, path):
    """xlsx likho. openpyxl chahiye. Raises ImportError agar nahi hai."""
    from openpyxl import Workbook  # noqa: WPS433
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Field", "Value"])
    ws.append(["Generated", rep["generated_at"]])
    ws.append(["App", "%s v%s" % (rep["app"]["name"], rep["app"]["version"])])
    ws.append(["Diagnostics", "ON" if rep["diagnostics_enabled"] else "OFF"])
    ws.append(["Log schema", rep.get("logging", {}).get("schema_version", "")])
    for k, v in rep["environment"].items():
        ws.append(["env." + k, str(v)])
    for k, v in rep["tools"].items():
        ws.append(["tool." + k, str(v)])

    dev = wb.create_sheet("Devices")
    dev.append(["Serial", "State", "Model"])
    for d in rep["devices"]:
        dev.append([d["serial"], d["state"], d["model"]])

    st = wb.create_sheet("Settings")
    st.append(["Setting", "Value"])
    for k, v in rep["settings"].items():
        st.append([k, str(v)])

    ev = wb.create_sheet("Events")
    ev.append(["timestamp", "log_level", "event_name", "screen_or_route", "attempt_id", "session_id"])
    for e in rep.get("events", []):
        ev.append([e.get("timestamp", ""), e.get("log_level", ""), e.get("event_name", ""),
                   e.get("screen_or_route", ""), e.get("attempt_id", ""), e.get("session_id", "")])

    lg = wb.create_sheet("Log")
    lg.append(["Time", "Serial", "Message"])
    for e in rep["log"]:
        lg.append([e["time"], e.get("serial", ""), e["text"]])

    wb.save(path)


def write_csv(rep, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "serial", "message"])
        for e in rep["log"]:
            w.writerow([e["time"], e.get("serial", ""), e["text"]])


def write_jsonl(rep, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(json.dumps(e, ensure_ascii=False) for e in rep.get("events", [])))


# --------------------------------------------------------------------------- #
#  Session
# --------------------------------------------------------------------------- #
class Session:
    """Ek device ka mirroring session."""

    def __init__(self, serial, label=""):
        self.serial = serial
        self.label = label or serial
        self.proc = None
        self.start_time = 0.0
        self.reconnect_attempts = 0
        self.user_stopped = False
        self.running_intent = False

    def active(self):
        return self.running_intent or self.proc is not None


# --------------------------------------------------------------------------- #
#  Diagnostics window
# --------------------------------------------------------------------------- #
class DiagnosticsWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Diagnostics  -  PhoneMirror")
        self.minsize(780, 620)
        self._last_path = None

        pad = {"padx": 8, "pady": 4}

        top = ttk.LabelFrame(self, text="Settings")
        top.pack(fill="x", **pad)
        ttk.Checkbutton(top, text="Collect diagnostics (logs + technical data)  -  default ON",
                        variable=app.diag_enabled, command=self._toggle).grid(
            row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Label(top, text="Off karne par app koi data collect nahi karegi (export sirf summary dega). "
                            "Structured events ProGallery Logging Spec v1.0 ke hisaab se hain.",
                  foreground="#666").grid(row=1, column=0, sticky="w", padx=8, pady=(0, 6))

        self.preview = tk.Text(self, height=18, wrap="none", bg="#111", fg="#d0d0d0",
                               insertbackground="#d0d0d0", font=("Consolas", 9))
        self.preview.pack(fill="both", expand=True, padx=8, pady=4)
        self.preview.configure(state="disabled")

        bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="left", padx=3)
        ttk.Button(bar, text="Clean", command=self.clean).pack(side="left", padx=3)
        ttk.Button(bar, text="Copy report", command=self.copy).pack(side="left", padx=3)

        ttk.Label(bar, text="Format:").pack(side="left", padx=(16, 4))
        self.fmt = tk.StringVar(value="txt")
        ttk.Combobox(bar, textvariable=self.fmt, state="readonly", width=8,
                     values=["txt", "md", "json", "jsonl", "csv", "xlsx"]).pack(side="left")
        ttk.Button(bar, text="Save as...", command=self.save_as).pack(side="left", padx=6)

        bar2 = ttk.Frame(self)
        bar2.pack(fill="x", **pad)
        ttk.Button(bar2, text="\u2709  Email (Gmail compose)", command=lambda: self.email(True)).pack(side="left", padx=3)
        ttk.Button(bar2, text="\u2709  Email (mail app)", command=lambda: self.email(False)).pack(side="left", padx=3)
        ttk.Button(bar2, text="Open folder", command=self.open_folder).pack(side="left", padx=3)
        ttk.Label(bar2, text="Email: %s" % DIAG_EMAIL, foreground="#666").pack(side="right", padx=6)

        self.status = ttk.Label(self, text="", anchor="w", relief="sunken")
        self.status.pack(fill="x", side="bottom")

        self.refresh()

    def _toggle(self):
        self.app.set_diag_enabled(self.app.diag_enabled.get())
        self.status.configure(text="Diagnostics %s." % ("ON" if self.app.diag_enabled.get() else "OFF"))
        self.refresh()

    def _render(self):
        rep = self.app.build_report()
        return render_txt(rep), rep

    def refresh(self):
        text, _ = self._render()
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("end", text)
        self.preview.configure(state="disabled")
        self.status.configure(text="Report refreshed - %d log lines, %d events."
                              % (len(self.app.diag), len(self.app.logger.events)))

    def clean(self):
        if not messagebox.askyesno("Clean", "Diagnostics log aur collected data clear kar dun?"):
            return
        self.app.clean_diagnostics()
        self.refresh()
        self.status.configure(text="Diagnostics data clear ho gaya.")

    def copy(self):
        text, _ = self._render()
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(text)
        self.status.configure(text="Poora report clipboard me copy ho gaya.")

    def save_as(self):
        fmt = self.fmt.get()
        ext = "." + fmt
        path = filedialog.asksaveasfilename(
            title="Diagnostics report save karo", defaultextension=ext,
            initialfile="PhoneMirror_diagnostics_%s%s" % (time.strftime("%Y%m%d_%H%M%S"), ext),
            filetypes=[(fmt.upper(), "*" + ext), ("All", "*.*")])
        if not path:
            return
        _, rep = self._render()
        try:
            self.app.save_report(rep, path, fmt)
            self._last_path = path
            self.status.configure(text="Saved: %s" % path)
            self.app._log(None, "[i] Diagnostics saved: %s" % path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save fail", str(exc))

    def email(self, gmail):
        try:
            path = self.app.email_report(gmail)
            self._last_path = path
            self.status.configure(text="Email compose khula. Report: %s" % path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Email fail", str(exc))

    def open_folder(self):
        d = self.app.diagnostics_dir()
        try:
            if IS_WINDOWS:
                os.startfile(d)  # noqa: S606
            else:
                webbrowser.open("file://" + d)
        except Exception:  # noqa: BLE001
            messagebox.showinfo("Folder", d)


# --------------------------------------------------------------------------- #
#  Main app
# --------------------------------------------------------------------------- #
class PhoneMirrorApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.minsize(880, 820)

        cfg = load_config()
        salt = cfg.get("salt") or _rand_hex(32)
        if cfg.get("salt") != salt:
            cfg["salt"] = salt
            save_config(cfg)
        self._salt = salt

        self.log_q = queue.Queue()
        self.devices = []
        self.sessions = {}
        self.diag = []                      # collected human-readable log entries
        self._diag_win = None
        self._launch_attempt = None
        self.session_id = "sess_" + _rand_hex(12)
        self.logger = StructuredLogger(self.session_id)
        self.scrcpy_path = tk.StringVar(value=find_executable("scrcpy") or "")
        self.adb_path = tk.StringVar(value=find_executable("adb") or "")

        self.diag_enabled = tk.BooleanVar(value=bool(cfg.get("diagnostics_enabled", True)))

        self.connection_mode = tk.StringVar(value="usb")
        self.wifi_ip = tk.StringVar(value="")
        self.wifi_port = tk.IntVar(value=5555)

        self.video_source = tk.StringVar(value="display")
        self.max_size = tk.IntVar(value=1024)
        self.bitrate = tk.StringVar(value="8M")
        self.max_fps = tk.IntVar(value=60)
        self.codec = tk.StringVar(value="h264")
        self.camera_facing = tk.StringVar(value="back")
        self.camera_size = tk.StringVar(value="1280x720")
        self.camera_fps = tk.IntVar(value=30)

        self.audio = tk.BooleanVar(value=True)
        self.audio_codec = tk.StringVar(value="opus")
        self.audio_bitrate = tk.StringVar(value="128K")
        self.audio_buffer = tk.IntVar(value=50)

        self.record = tk.BooleanVar(value=False)
        self.record_path = tk.StringVar(value="")

        self.no_control = tk.BooleanVar(value=False)
        self.keyboard_mode = tk.StringVar(value="default")

        self.turn_screen_off = tk.BooleanVar(value=False)
        self.stay_awake = tk.BooleanVar(value=True)
        self.always_on_top = tk.BooleanVar(value=False)
        self.print_fps = tk.BooleanVar(value=False)

        self.auto_reconnect = tk.BooleanVar(value=True)
        self.reconnect_delay = tk.IntVar(value=3)
        self.reconnect_max = tk.IntVar(value=0)

        self._build_ui()
        self._poll_log()
        self._ev("session_start", "info", "Main", props={"start_type": "cold"})
        self.refresh_devices()

    # ---------------- structured events ----------------
    def _ev(self, event_name, log_level, screen_or_route, attempt_id=None, props=None):
        """Structured event log (sirf diagnostics ON hone par)."""
        if not self.diag_enabled.get():
            return None
        return self.logger.log(event_name, log_level, screen_or_route,
                               attempt_id=attempt_id, props=props)

    def _dev_pseudonym(self, serial):
        return salted_hash(serial, self._salt)

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 3}

        paths = ttk.LabelFrame(self.root, text="1. Tools (scrcpy / adb)")
        paths.pack(fill="x", **pad)
        ttk.Label(paths, text="scrcpy:").grid(row=0, column=0, sticky="w", padx=6, pady=3)
        ttk.Entry(paths, textvariable=self.scrcpy_path, width=52).grid(row=0, column=1, sticky="we", pady=3)
        ttk.Button(paths, text="Browse", command=self._browse_scrcpy).grid(row=0, column=2, padx=6)
        ttk.Label(paths, text="adb:").grid(row=1, column=0, sticky="w", padx=6, pady=3)
        ttk.Entry(paths, textvariable=self.adb_path, width=52).grid(row=1, column=1, sticky="we", pady=3)
        ttk.Button(paths, text="Browse", command=self._browse_adb).grid(row=1, column=2, padx=6)
        paths.columnconfigure(1, weight=1)

        dev = ttk.LabelFrame(self.root, text="2. Device  (multi-select: Ctrl / Shift + click)")
        dev.pack(fill="x", **pad)
        self.device_list = tk.Listbox(dev, selectmode="extended", height=4, exportselection=False)
        self.device_list.grid(row=0, column=0, sticky="we", padx=6, pady=6)
        sb = ttk.Scrollbar(dev, orient="vertical", command=self.device_list.yview)
        sb.grid(row=0, column=1, sticky="ns", pady=6)
        self.device_list.configure(yscrollcommand=sb.set)
        ttk.Button(dev, text="Refresh", command=self.refresh_devices).grid(row=0, column=2, padx=6, sticky="n")
        self.device_status = ttk.Label(dev, text="", foreground="#666")
        self.device_status.grid(row=1, column=0, columnspan=3, sticky="w", padx=8)
        dev.columnconfigure(0, weight=1)

        conn = ttk.LabelFrame(self.root, text="3. Connection (USB / Wi-Fi)")
        conn.pack(fill="x", **pad)
        ttk.Radiobutton(conn, text="USB cable  (lowest latency)", value="usb",
                        variable=self.connection_mode).grid(row=0, column=0, columnspan=5, sticky="w", padx=6)
        ttk.Radiobutton(conn, text="Wi-Fi / TCP-IP  (no cable)", value="wifi",
                        variable=self.connection_mode).grid(row=1, column=0, columnspan=5, sticky="w", padx=6)
        ttk.Label(conn, text="Phone IP:").grid(row=2, column=0, sticky="e", padx=(16, 4), pady=4)
        ttk.Entry(conn, textvariable=self.wifi_ip, width=15).grid(row=2, column=1, sticky="w")
        ttk.Label(conn, text="Port:").grid(row=2, column=2, sticky="e", padx=(12, 4))
        ttk.Entry(conn, textvariable=self.wifi_port, width=7).grid(row=2, column=3, sticky="w")
        ttk.Button(conn, text="Auto-detect IP", command=self.detect_ip).grid(row=2, column=4, padx=8)
        ttk.Button(conn, text="Enable Wi-Fi", command=self.enable_wifi).grid(row=3, column=0, padx=6, pady=(0, 4), sticky="w")
        ttk.Button(conn, text="Connect", command=self.connect_wifi).grid(row=3, column=1, padx=6, pady=(0, 4), sticky="w")
        ttk.Button(conn, text="Disconnect", command=self.disconnect_wifi).grid(row=3, column=2, padx=6, pady=(0, 4), sticky="w")

        pre = ttk.LabelFrame(self.root, text="4. Preset")
        pre.pack(fill="x", **pad)
        for i, name in enumerate(PRESETS):
            ttk.Button(pre, text=name, command=lambda n=name: self.apply_preset(n)).grid(
                row=0, column=i, padx=6, pady=4, sticky="we")
            pre.columnconfigure(i, weight=1)
        self.preset_desc = ttk.Label(pre, text=PRESETS["Low Latency"]["desc"],
                                     wraplength=800, foreground="#444")
        self.preset_desc.grid(row=1, column=0, columnspan=len(PRESETS), sticky="w", padx=8, pady=(0, 4))

        tun = ttk.LabelFrame(self.root, text="5. Video")
        tun.pack(fill="x", **pad)
        srcrow = ttk.Frame(tun)
        srcrow.grid(row=0, column=0, columnspan=4, sticky="w", padx=6, pady=(4, 0))
        ttk.Label(srcrow, text="Source:").pack(side="left")
        ttk.Radiobutton(srcrow, text="Display", value="display", variable=self.video_source,
                        command=self._on_source).pack(side="left", padx=(8, 0))
        ttk.Radiobutton(srcrow, text="Camera", value="camera", variable=self.video_source,
                        command=self._on_source).pack(side="left", padx=(8, 0))
        ttk.Label(tun, text="Max size (px):").grid(row=1, column=0, sticky="w", padx=6, pady=3)
        self.size_scale = ttk.Scale(tun, from_=480, to=2560, variable=self.max_size,
                                    orient="horizontal", command=self._on_size)
        self.size_scale.grid(row=1, column=1, sticky="we", padx=6)
        self.size_lbl = ttk.Label(tun, text="1024", width=6)
        self.size_lbl.grid(row=1, column=2, sticky="w")
        ttk.Label(tun, text="Bitrate:").grid(row=2, column=0, sticky="w", padx=6, pady=3)
        ttk.Combobox(tun, textvariable=self.bitrate, state="readonly", width=10,
                     values=["2M", "4M", "6M", "8M", "12M", "16M", "24M"]).grid(row=2, column=1, sticky="w", padx=6)
        ttk.Label(tun, text="Max FPS:").grid(row=3, column=0, sticky="w", padx=6, pady=3)
        ttk.Combobox(tun, textvariable=self.max_fps, state="readonly", width=10,
                     values=[15, 30, 45, 60, 90, 120]).grid(row=3, column=1, sticky="w", padx=6)
        ttk.Label(tun, text="Codec:").grid(row=4, column=0, sticky="w", padx=6, pady=3)
        ttk.Combobox(tun, textvariable=self.codec, state="readonly", width=10,
                     values=["h264", "h265", "av1"]).grid(row=4, column=1, sticky="w", padx=6)
        cam = ttk.Frame(tun)
        cam.grid(row=1, column=3, rowspan=2, sticky="nw", padx=16)
        ttk.Label(cam, text="Camera facing:").grid(row=0, column=0, sticky="e", padx=(0, 4))
        ttk.Combobox(cam, textvariable=self.camera_facing, state="readonly", width=9,
                     values=["back", "front", "external"]).grid(row=0, column=1, sticky="w")
        ttk.Label(cam, text="Camera size:").grid(row=1, column=0, sticky="e", padx=(0, 4), pady=(4, 0))
        ttk.Combobox(cam, textvariable=self.camera_size, state="readonly", width=11,
                     values=["1920x1080", "1280x720", "640x480", "2560x1440"]).grid(row=1, column=1, sticky="w", pady=(4, 0))
        ttk.Label(cam, text="Camera FPS:").grid(row=2, column=0, sticky="e", padx=(0, 4), pady=(4, 0))
        ttk.Combobox(cam, textvariable=self.camera_fps, state="readonly", width=9,
                     values=[15, 24, 30, 60]).grid(row=2, column=1, sticky="w", pady=(4, 0))
        vopts = ttk.Frame(tun)
        vopts.grid(row=3, column=3, rowspan=2, sticky="nw", padx=16)
        ttk.Checkbutton(vopts, text="Turn phone screen off", variable=self.turn_screen_off).pack(anchor="w")
        ttk.Checkbutton(vopts, text="Stay awake", variable=self.stay_awake).pack(anchor="w")
        ttk.Checkbutton(vopts, text="Always on top", variable=self.always_on_top).pack(anchor="w")
        ttk.Checkbutton(vopts, text="Print FPS (debug)", variable=self.print_fps).pack(anchor="w")
        tun.columnconfigure(1, weight=1)

        aud = ttk.LabelFrame(self.root, text="6. Audio")
        aud.pack(fill="x", **pad)
        ttk.Checkbutton(aud, text="Audio on (clear)", variable=self.audio).grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Label(aud, text="Codec:").grid(row=0, column=1, sticky="e", padx=(16, 4))
        ttk.Combobox(aud, textvariable=self.audio_codec, state="readonly", width=8,
                     values=["opus", "aac", "flac", "raw"]).grid(row=0, column=2, sticky="w")
        ttk.Label(aud, text="Bitrate:").grid(row=0, column=3, sticky="e", padx=(16, 4))
        ttk.Combobox(aud, textvariable=self.audio_bitrate, state="readonly", width=8,
                     values=["64K", "96K", "128K", "192K", "256K", "320K"]).grid(row=0, column=4, sticky="w")
        ttk.Label(aud, text="Buffer (ms):").grid(row=0, column=5, sticky="e", padx=(16, 4))
        ttk.Combobox(aud, textvariable=self.audio_buffer, state="readonly", width=6,
                     values=[0, 25, 50, 100, 150, 200]).grid(row=0, column=6, sticky="w", padx=(0, 6))

        rec = ttk.LabelFrame(self.root, text="7. Recording")
        rec.pack(fill="x", **pad)
        ttk.Checkbutton(rec, text="Record session to file", variable=self.record).grid(
            row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(rec, textvariable=self.record_path, width=52).grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(rec, text="Save as...", command=self._browse_record).grid(row=0, column=2, padx=6)
        rec.columnconfigure(1, weight=1)

        rc = ttk.LabelFrame(self.root, text="8. Auto-reconnect (per device)")
        rc.pack(fill="x", **pad)
        ttk.Checkbutton(rc, text="Auto-reconnect on disconnect", variable=self.auto_reconnect).grid(
            row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Label(rc, text="Retry delay (s):").grid(row=0, column=1, sticky="e", padx=(16, 4))
        ttk.Spinbox(rc, from_=1, to=60, textvariable=self.reconnect_delay, width=5).grid(row=0, column=2, sticky="w")
        ttk.Label(rc, text="Max attempts (0 = unlimited):").grid(row=0, column=3, sticky="e", padx=(16, 4))
        ttk.Spinbox(rc, from_=0, to=1000, textvariable=self.reconnect_max, width=6).grid(row=0, column=4, sticky="w", padx=(0, 6))

        ctl = ttk.LabelFrame(self.root, text="9. Input control (PC se phone chalao)")
        ctl.pack(fill="x", **pad)
        ttk.Checkbutton(ctl, text="No control (sirf dekho)", variable=self.no_control).grid(
            row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Label(ctl, text="Keyboard mode:").grid(row=0, column=1, sticky="e", padx=(16, 4))
        ttk.Combobox(ctl, textvariable=self.keyboard_mode, state="readonly", width=10,
                     values=["default", "uhid", "sdk", "disabled"]).grid(row=0, column=2, sticky="w")

        act = ttk.Frame(self.root)
        act.pack(fill="x", **pad)
        self.launch_btn = ttk.Button(act, text="\u25b6  Start Mirroring", command=self.launch)
        self.launch_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(act, text="\u25a0  Stop All", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        ttk.Button(act, text="Copy command(s)", command=self.copy_command).pack(side="left", padx=4)
        ttk.Button(act, text="\u2699  Diagnostics", command=self.open_diagnostics).pack(side="right", padx=4)

        logf = ttk.LabelFrame(self.root, text="Log")
        logf.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(logf, height=8, wrap="word", bg="#111", fg="#d0d0d0",
                           insertbackground="#d0d0d0", font=("Consolas", 9))
        self.log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        lsb = ttk.Scrollbar(logf, command=self.log.yview)
        lsb.pack(side="right", fill="y", pady=6, padx=(0, 6))
        self.log.configure(yscrollcommand=lsb.set, state="disabled")

        self.status = ttk.Label(self.root, text="Ready.", anchor="w", relief="sunken")
        self.status.pack(fill="x", side="bottom")

    # ---------------- small helpers ----------------
    def _on_size(self, _val):
        self.size_lbl.configure(text=str(int(float(self.max_size.get()))))

    def _on_source(self):
        cam = (self.video_source.get() == "camera")
        self.size_scale.configure(state="disabled" if cam else "normal")

    def _browse_scrcpy(self):
        p = filedialog.askopenfilename(title="scrcpy.exe chuno",
                                       filetypes=[("scrcpy", "scrcpy*"), ("All", "*.*")])
        if p:
            self.scrcpy_path.set(p)

    def _browse_adb(self):
        p = filedialog.askopenfilename(title="adb.exe chuno",
                                       filetypes=[("adb", "adb*"), ("All", "*.*")])
        if p:
            self.adb_path.set(p)

    def _browse_record(self):
        p = filedialog.asksaveasfilename(title="Recording kahan save karein",
                                         defaultextension=".mp4",
                                         filetypes=[("MP4 video", "*.mp4"), ("MKV video", "*.mkv")])
        if p:
            self.record_path.set(p)
            self.record.set(True)

    def _log(self, serial, text):
        prefix = ("[%s] " % serial) if serial else ""
        self.log.configure(state="normal")
        self.log.insert("end", prefix + text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        if self.diag_enabled.get():
            self.diag.append({
                "time": datetime.datetime.now().strftime("%H:%M:%S"),
                "serial": serial or "",
                "text": redact(text),
            })
            if len(self.diag) > 5000:
                del self.diag[:1000]

    def _adb(self):
        adb = self.adb_path.get().strip()
        if not adb or not os.path.exists(adb):
            adb = find_executable("adb")
            if adb:
                self.adb_path.set(adb)
        return adb

    def _run_adb_logged(self, adb, args, screen="Main"):
        t0 = time.time()
        ok, out = run_adb(adb, args)
        self._ev("adb_command", "debug", screen, props={
            "command": "adb " + " ".join(args),
            "outcome": "success" if ok else "failed",
            "latency_ms": int((time.time() - t0) * 1000),
        })
        return ok, out

    # ---------------- diagnostics ----------------
    def set_diag_enabled(self, value):
        self.diag_enabled.set(bool(value))
        cfg = load_config()
        cfg["diagnostics_enabled"] = bool(value)
        save_config(cfg)

    def clean_diagnostics(self):
        self.diag = []
        self.logger.events = []
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def diagnostics_dir(self):
        home = os.path.expanduser("~")
        docs = os.path.join(home, "Documents")
        d = os.path.join(docs, "PhoneMirror") if os.path.isdir(docs) else os.path.join(home, "PhoneMirror")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:  # noqa: BLE001
            d = home
        return d

    def build_report(self):
        scrcpy = self._resolve_scrcpy()
        scrcpy_ver = ""
        if scrcpy:
            try:
                out = subprocess.run([scrcpy, "--version"], capture_output=True, text=True,
                                     timeout=10, creationflags=CREATE_NO_WINDOW).stdout.strip()
                scrcpy_ver = out.splitlines()[0] if out else ""
            except Exception as exc:  # noqa: BLE001
                scrcpy_ver = "error: %s" % exc

        adb = self._adb()
        adb_ver = ""
        devices = []
        if adb:
            ok, out = run_adb(adb, ["version"])
            adb_ver = out.splitlines()[0] if out else ""
            devs, _ = list_devices(adb)
            devices = [{"serial": d["serial"], "state": d["state"], "model": d["model"]} for d in devs]

        return {
            "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "app": {"name": "PhoneMirror", "version": APP_VERSION},
            "diagnostics_enabled": bool(self.diag_enabled.get()),
            "logging": {
                "schema_version": LOG_SCHEMA_VERSION,
                "session_id": self.session_id,
                "retention_days": LOG_RETENTION_DAYS,
                "sample_info_rate": LOG_SAMPLE_INFO_RATE,
                "release_channel": LOG_RELEASE_CHANNEL,
            },
            "environment": {
                "os": platform.platform(),
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": sys.version.split()[0],
            },
            "tools": {
                "scrcpy_path": scrcpy or "",
                "scrcpy_version": scrcpy_ver,
                "adb_path": adb or "",
                "adb_version": adb_ver,
            },
            "devices": devices,
            "settings": self.current_settings(),
            "events": list(self.logger.events),
            "log": list(self.diag),
        }

    def save_report(self, rep, path, fmt):
        fmt = (fmt or "txt").lower().lstrip(".")
        try:
            if fmt == "txt":
                with open(path, "w", encoding="utf-8") as f:
                    f.write(render_txt(rep))
            elif fmt == "md":
                with open(path, "w", encoding="utf-8") as f:
                    f.write(render_md(rep))
            elif fmt == "json":
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(rep, f, indent=2, ensure_ascii=False)
            elif fmt == "jsonl":
                write_jsonl(rep, path)
            elif fmt == "csv":
                write_csv(rep, path)
            elif fmt == "xlsx":
                try:
                    write_xlsx(rep, path)
                except ImportError:
                    raise RuntimeError("xlsx ke liye openpyxl chahiye.\n\nInstall: pip install openpyxl\n"
                                       "(ya CSV/TXT/JSONL format use karo)")
            else:
                raise RuntimeError("Unknown format: %s" % fmt)
        except RuntimeError:
            self._ev("export_saved", "error", "Diagnostics",
                     props={"format": fmt, "outcome": "failed", "error_code": "export_failed"})
            raise
        except Exception as exc:  # noqa: BLE001
            self._ev("export_saved", "error", "Diagnostics",
                     props={"format": fmt, "outcome": "failed", "error_code": "export_error"})
            raise
        self._ev("export_saved", "info", "Diagnostics",
                 props={"format": fmt, "outcome": "success"})

    def email_report(self, gmail=True):
        rep = self.build_report()
        d = self.diagnostics_dir()
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(d, "PhoneMirror_diagnostics_%s.md" % ts)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(render_md(rep))
        except Exception as exc:  # noqa: BLE001
            self._ev("email_compose", "error", "Diagnostics",
                     props={"outcome": "failed", "error_code": "report_save_failed"})
            raise RuntimeError("Report save nahi hui: %s" % exc)

        body = render_email_body(rep, path)
        subj = "PhoneMirror diagnostics report - %s" % rep["generated_at"]

        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(render_txt(rep))
        except Exception:  # noqa: BLE001
            pass

        if gmail:
            url = ("https://mail.google.com/mail/?view=cm&fs=1&to=%s&su=%s&body=%s"
                   % (quote(DIAG_EMAIL), quote(subj), quote(body)))
        else:
            url = "mailto:%s?subject=%s&body=%s" % (DIAG_EMAIL, quote(subj), quote(body))
        webbrowser.open(url)

        self._ev("email_compose", "info", "Diagnostics",
                 props={"outcome": "success", "channel": "gmail" if gmail else "mailto"})
        self._log(None, "[i] Email compose khula -> %s (report: %s)" % (DIAG_EMAIL, path))
        self.status.configure(text="Email compose khula. Report file: %s" % path)
        return path

    def open_diagnostics(self):
        self._ev("screen_view", "info", "Diagnostics",
                 props={"screen_name": "Diagnostics", "previous_screen": "Main"})
        if self._diag_win is not None and self._diag_win.winfo_exists():
            self._diag_win.lift()
            self._diag_win.refresh()
            return
        self._diag_win = DiagnosticsWindow(self)

    def _tk_exception(self, exc, val, tb):
        """Tkinter callback me uncaught exception -> crash event (raw stack nahi)."""
        tb_text = "".join(traceback.format_exception(exc, val, tb))
        self._ev("crash", "error", "Main", props={
            "fatal": False,
            "exception_type": getattr(exc, "__name__", str(exc)),
            "stack_trace_hash": hashlib.sha256(tb_text.encode("utf-8")).hexdigest()[:16],
        })
        self._log(None, "[!] Unhandled error: %s: %s" % (getattr(exc, "__name__", exc), val))

    # ---------------- presets / settings ----------------
    def apply_preset(self, name):
        p = PRESETS[name]
        self.max_size.set(p["max_size"])
        self._on_size(None)
        self.bitrate.set(p["bitrate"])
        self.max_fps.set(p["max_fps"])
        self.codec.set(p["codec"])
        self.audio.set(p["audio"])
        self.audio_codec.set(p["audio_codec"])
        self.audio_bitrate.set(p["audio_bitrate"])
        self.audio_buffer.set(p["audio_buffer"])
        self.preset_desc.configure(text="[%s]  %s" % (name, p["desc"]))
        self.status.configure(text="Preset lagaya: %s" % name)

    def current_settings(self):
        return {
            "video_source": self.video_source.get(),
            "max_size": int(float(self.max_size.get())),
            "bitrate": self.bitrate.get(),
            "max_fps": int(self.max_fps.get()),
            "codec": self.codec.get(),
            "camera_facing": self.camera_facing.get(),
            "camera_size": self.camera_size.get(),
            "camera_fps": int(self.camera_fps.get()),
            "audio": self.audio.get(),
            "audio_codec": self.audio_codec.get(),
            "audio_bitrate": self.audio_bitrate.get(),
            "audio_buffer": int(self.audio_buffer.get()),
            "record": self.record.get(),
            "record_path": redact(self.record_path.get()),
            "no_control": self.no_control.get(),
            "keyboard_mode": self.keyboard_mode.get(),
            "turn_screen_off": self.turn_screen_off.get(),
            "stay_awake": self.stay_awake.get(),
            "always_on_top": self.always_on_top.get(),
            "print_fps": self.print_fps.get(),
            "auto_reconnect": self.auto_reconnect.get(),
            "reconnect_delay": int(self.reconnect_delay.get()),
            "reconnect_max": int(self.reconnect_max.get()),
            "connection_mode": self.connection_mode.get(),
        }

    def selected_serials(self):
        out = []
        for i in self.device_list.curselection():
            if i < len(self.devices):
                out.append(self.devices[i]["serial"])
        return out

    def primary_serial(self):
        s = self.selected_serials()
        return s[0] if s else None

    def record_path_for(self, serial):
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", serial or "device")
        ts = time.strftime("%Y%m%d_%H%M%S")
        base = self.record_path.get().strip()
        if base:
            root_, ext = os.path.splitext(base)
            ext = ext or ".mp4"
            if len(self.selected_serials()) > 1:
                return "%s_%s%s" % (root_, safe, ext)
            return base
        vids = os.path.join(os.path.expanduser("~"), "Videos")
        if not os.path.isdir(vids):
            vids = os.path.expanduser("~")
        return os.path.join(vids, "PhoneMirror_%s_%s.mp4" % (safe, ts))

    # ---------------- Wi-Fi helpers ----------------
    def detect_ip(self):
        adb = self._adb()
        if not adb:
            self._log(None, "[!] adb nahi mila.")
            self._ev("error_state_shown", "error", "Main",
                     props={"error_code": "adb_missing", "message_key": "adb_not_found"})
            return
        ip = detect_phone_ip(adb, self.primary_serial())
        if ip:
            self.wifi_ip.set(ip)
            self._log(None, "[i] Phone IP: %s" % ip)
            self.status.configure(text="Phone IP: %s" % ip)
        else:
            self._log(None, "[!] IP detect nahi hua.")
            self._ev("error_state_shown", "error", "Main",
                     props={"error_code": "ip_not_found", "message_key": "ip_not_detected"})
            messagebox.showwarning("IP nahi mila", "Phone Wi-Fi se juda hai aur USB se connected hai?")

    def enable_wifi(self):
        adb = self._adb()
        if not adb:
            self._log(None, "[!] adb nahi mila.")
            return
        serial = self.primary_serial()
        if not serial:
            self._ev("error_state_shown", "warn", "Main",
                     props={"error_code": "no_device", "message_key": "no_device_selected"})
            messagebox.showwarning("Device nahi", "Pehle USB se phone jodo aur Refresh dabao.")
            return
        port = int(self.wifi_port.get())
        ok, out = self._run_adb_logged(adb, ["-s", serial, "tcpip", str(port)])
        self._log(None, "[i] adb tcpip %d -> %s" % (port, "OK" if ok else out))
        if ok:
            self.status.configure(text="Wi-Fi mode on. Cable nikaalo aur 'Connect' dabao.")
        else:
            self._ev("error_state_shown", "error", "Main",
                     props={"error_code": "tcpip_failed", "message_key": "enable_wifi_failed"})
            messagebox.showerror("Enable Wi-Fi fail", out or "adb tcpip fail hua.")

    def connect_wifi(self):
        adb = self._adb()
        if not adb:
            self._log(None, "[!] adb nahi mila.")
            return
        ip = self.wifi_ip.get().strip()
        if not ip:
            self._ev("error_state_shown", "warn", "Main",
                     props={"error_code": "no_ip", "message_key": "ip_missing"})
            messagebox.showwarning("IP nahi", "Phone IP daalo ya 'Auto-detect IP' dabao.")
            return
        target = "%s:%d" % (ip, int(self.wifi_port.get()))
        ok, out = self._run_adb_logged(adb, ["connect", target])
        self._log(None, "[i] adb connect %s -> %s" % (target, out))
        self.refresh_devices()
        self.status.configure(text="Connect try kiya. Device list check karo.")

    def disconnect_wifi(self):
        adb = self._adb()
        ip = self.wifi_ip.get().strip()
        if adb and ip:
            target = "%s:%d" % (ip, int(self.wifi_port.get()))
            ok, out = self._run_adb_logged(adb, ["disconnect", target])
            self._log(None, "[i] adb disconnect %s -> %s" % (target, out))
            self.refresh_devices()

    # ---------------- devices ----------------
    def refresh_devices(self):
        adb = self._adb()
        if not adb:
            self.device_status.configure(text="adb nahi mila. Upar path set karo.", foreground="#b00")
            self._log(None, "[!] adb nahi mila.")
            self._ev("device_state_resolved", "error", "Main",
                     props={"state": "unknown", "device_count": 0, "error_code": "adb_missing"})
            return

        prev = set()
        for i in self.device_list.curselection():
            if i < len(self.devices):
                prev.add(self.devices[i]["serial"])

        newdevs, err = list_devices(adb)
        if err:
            self.device_status.configure(text="Device list error: %s" % err, foreground="#b00")
            self._log(None, "[!] %s" % err)
            self._ev("device_refresh_result", "error", "Main",
                     props={"outcome": "failed", "error_code": "list_failed"})
            return

        self.devices = newdevs
        self.device_list.delete(0, "end")
        for d in self.devices:
            self.device_list.insert("end", d["label"])

        restored = False
        for i, d in enumerate(self.devices):
            if d["serial"] in prev:
                self.device_list.selection_set(i)
                restored = True
        if not restored and self.devices:
            self.device_list.selection_set(0)

        ready = [d for d in self.devices if d["state"] == "device"]
        if ready:
            self.device_status.configure(text="%d device ready. Multi-select kar sakte ho." % len(ready),
                                         foreground="#080")
        elif self.devices:
            self.device_status.configure(text="Device unauthorized/offline. USB debugging allow karo.",
                                         foreground="#b60")
        else:
            self.device_status.configure(text="Koi device nahi mila.", foreground="#b60")
        self._log(None, "[i] Devices refresh: %d mile." % len(self.devices))

        if ready:
            state = "authorized"
        elif self.devices:
            state = "unauthorized"
        else:
            state = "none"
        self._ev("device_state_resolved", "info", "Main",
                 props={"state": state, "device_count": len(self.devices), "ready_count": len(ready)})
        self._ev("device_refresh_result", "info", "Main",
                 props={"outcome": "success", "device_count": len(self.devices), "ready_count": len(ready)})

    # ---------------- run ----------------
    def copy_command(self):
        scrcpy = self.scrcpy_path.get().strip() or "scrcpy"
        serials = self.selected_serials()
        if not serials:
            self.status.configure(text="Pehle device select karo.")
            return
        lines = []
        for serial in serials:
            s = self.current_settings()
            if s.get("record"):
                s["record_path"] = self.record_path_for(serial)
            cmd = build_command(scrcpy, serial, s)
            lines.append(" ".join('"%s"' % c if " " in c else c for c in cmd))
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(lines))
        self.status.configure(text="%d command clipboard me copy hue." % len(lines))

    def _resolve_scrcpy(self):
        scrcpy = self.scrcpy_path.get().strip()
        if not scrcpy or not os.path.exists(scrcpy):
            scrcpy = find_executable("scrcpy")
            if scrcpy:
                self.scrcpy_path.set(scrcpy)
        return scrcpy

    def launch(self):
        scrcpy = self._resolve_scrcpy()
        if not scrcpy:
            self._ev("error_state_shown", "error", "Main",
                     props={"error_code": "scrcpy_missing", "message_key": "scrcpy_not_found"})
            messagebox.showerror("scrcpy nahi mila",
                                 "scrcpy.exe ka path set karo.\n\nInstall: winget install Genymobile.scrcpy")
            return
        serials = self.selected_serials()
        if not serials:
            self._ev("error_state_shown", "warn", "Main",
                     props={"error_code": "no_device", "message_key": "no_device_selected"})
            messagebox.showwarning("Device nahi", "Pehle device select karo (Ctrl/Shift + click).")
            return

        self._launch_attempt = self.logger.new_attempt_id()
        self._ev("mirror_requested", "info", "Main", attempt_id=self._launch_attempt,
                 props={"device_count": len(serials), "video_source": self.video_source.get(),
                        "connection_mode": self.connection_mode.get()})
        for serial in serials:
            sess = self.sessions.get(serial) or Session(serial)
            self.sessions[serial] = sess
            sess.user_stopped = False
            sess.reconnect_attempts = 0
            self._start_session(serial)
        self.status.configure(text="%d session start ho raha hai..." % len(serials))
        self._refresh_buttons()

    def _start_session(self, serial):
        sess = self.sessions.get(serial) or Session(serial)
        self.sessions[serial] = sess

        scrcpy = self._resolve_scrcpy()
        if not scrcpy:
            self._log(serial, "[!] scrcpy nahi mila, rok raha hoon.")
            self._ev("mirror_result", "error", "Main", attempt_id=self._launch_attempt,
                     props={"outcome": "failed", "error_code": "scrcpy_missing",
                            "device": self._dev_pseudonym(serial)})
            sess.running_intent = False
            self._refresh_buttons()
            return

        s = self.current_settings()
        if s.get("record"):
            s["record_path"] = self.record_path_for(serial)
        cmd = build_command(scrcpy, serial, s)
        self._log(serial, "$ " + " ".join(cmd))

        try:
            sess.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=CREATE_NO_WINDOW,
            )
        except Exception as exc:  # noqa: BLE001
            self._log(serial, "[!] Launch fail: %s" % exc)
            self._ev("mirror_result", "error", "Main", attempt_id=self._launch_attempt,
                     props={"outcome": "failed", "error_code": "launch_failed",
                            "device": self._dev_pseudonym(serial)})
            sess.proc = None
            sess.running_intent = False
            self._refresh_buttons()
            return

        sess.start_time = time.time()
        sess.running_intent = True
        self._ev("mirror_result", "info", "Main", attempt_id=self._launch_attempt,
                 props={"outcome": "success", "device": self._dev_pseudonym(serial)})
        threading.Thread(target=self._reader, args=(serial, sess.proc), daemon=True).start()
        self._refresh_buttons()

    def _reader(self, serial, proc):
        try:
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break
                self.log_q.put(("line", serial, line.rstrip()))
        finally:
            self.log_q.put(("end", serial))

    def _poll_log(self):
        try:
            while True:
                item = self.log_q.get_nowait()
                if item[0] == "line":
                    self._log(item[1], item[2])
                elif item[0] == "end":
                    self._on_session_end(item[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log)

    def _on_session_end(self, serial):
        sess = self.sessions.get(serial)
        if sess is None:
            return
        if sess.proc is not None:
            elapsed = time.time() - sess.start_time
            self._log(serial, "[i] band ho gaya (%.0f s)." % elapsed)
            sess.proc = None
            if elapsed >= 15:
                sess.reconnect_attempts = 0

        if sess.running_intent and not sess.user_stopped and self.auto_reconnect.get():
            delay = int(self.reconnect_delay.get())
            self._log(serial, "[i] Auto-reconnect %d s me..." % delay)
            self.root.after(delay * 1000, lambda: self._attempt_reconnect(serial))
        else:
            sess.running_intent = False
        self._refresh_buttons()

    def _attempt_reconnect(self, serial):
        sess = self.sessions.get(serial)
        if sess is None or not sess.running_intent or sess.user_stopped or not self.auto_reconnect.get():
            return
        maxa = int(self.reconnect_max.get())
        if maxa and sess.reconnect_attempts >= maxa:
            self._log(serial, "[!] Max attempts (%d) pura." % maxa)
            sess.running_intent = False
            self._refresh_buttons()
            return

        adb = self._adb()
        present = False
        if adb:
            devs, _ = list_devices(adb)
            present = any(d["serial"] == serial and d["state"] == "device" for d in devs)

        if present:
            sess.reconnect_attempts += 1
            self._log(serial, "[i] Reconnect attempt #%d" % sess.reconnect_attempts)
            att = self.logger.new_attempt_id("rc")
            self._ev("reconnect_attempt", "info", "Main", attempt_id=att,
                     props={"attempt_number": sess.reconnect_attempts,
                            "device": self._dev_pseudonym(serial)})
            # user-friendliness signal: reconnect_loop
            if sess.reconnect_attempts >= 3:
                self._ev("reconnect_loop", "warn", "Main", attempt_id=att,
                         props={"attempt_count": sess.reconnect_attempts,
                                "device": self._dev_pseudonym(serial)})
            self._start_session(serial)
            self._ev("reconnect_result", "info", "Main", attempt_id=att, props={"outcome": "success"})
        else:
            delay = int(self.reconnect_delay.get())
            self._log(serial, "[i] Device nahi mila, %d s baad try..." % delay)
            self.root.after(delay * 1000, lambda: self._attempt_reconnect(serial))

    def _refresh_buttons(self):
        active = any(s.active() for s in self.sessions.values())
        self.launch_btn.configure(state="disabled" if active else "normal")
        self.stop_btn.configure(state="normal" if active else "disabled")

    def stop(self):
        for sess in self.sessions.values():
            sess.user_stopped = True
            sess.running_intent = False
            if sess.proc is not None:
                try:
                    sess.proc.terminate()
                except Exception:  # noqa: BLE001
                    pass
        self._log(None, "[i] Stop dabaya, sab sessions band ho rahe hain.")
        self.status.configure(text="Ruk raha hai...")

    def on_close(self):
        for sess in self.sessions.values():
            sess.user_stopped = True
            sess.running_intent = False
            if sess.proc is not None:
                try:
                    sess.proc.terminate()
                except Exception:  # noqa: BLE001
                    pass
        self._ev("session_end", "info", "Main", props={"reason": "user_close"})
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista" if IS_WINDOWS else "clam")
    except tk.TclError:
        pass
    app = PhoneMirrorApp(root)
    root.report_callback_exception = app._tk_exception
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
