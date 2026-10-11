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

Yeh scrcpy ka engine use karta hai (hardware encode + USB transport).

Sirf Python 3 + scrcpy + adb chahiye. Tkinter Python ke saath aata hai.

Run:  python PhoneMirror.py
"""

import os
import re
import sys
import time
import shutil
import subprocess
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

APP_TITLE = "PhoneMirror  -  Screen Mirror (scrcpy wrapper)"
IS_WINDOWS = (os.name == "nt")
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


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

    # --- video source ---
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

    # --- audio ---
    if s.get("audio"):
        cmd += ["--audio-codec", s.get("audio_codec", "opus")]
        cmd += ["--audio-bit-rate", s.get("audio_bitrate", "128K")]
        cmd += ["--audio-buffer", str(s.get("audio_buffer", 50))]
    else:
        cmd += ["--no-audio"]

    # --- recording ---
    if s.get("record") and s.get("record_path"):
        cmd += ["--record", s["record_path"]]

    # --- input control ---
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
#  GUI
# --------------------------------------------------------------------------- #
class PhoneMirrorApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.minsize(880, 820)

        self.log_q = queue.Queue()
        self.devices = []
        self.sessions = {}   # serial -> Session
        self.scrcpy_path = tk.StringVar(value=find_executable("scrcpy") or "")
        self.adb_path = tk.StringVar(value=find_executable("adb") or "")

        # connection
        self.connection_mode = tk.StringVar(value="usb")
        self.wifi_ip = tk.StringVar(value="")
        self.wifi_port = tk.IntVar(value=5555)

        # video
        self.video_source = tk.StringVar(value="display")
        self.max_size = tk.IntVar(value=1024)
        self.bitrate = tk.StringVar(value="8M")
        self.max_fps = tk.IntVar(value=60)
        self.codec = tk.StringVar(value="h264")
        self.camera_facing = tk.StringVar(value="back")
        self.camera_size = tk.StringVar(value="1280x720")
        self.camera_fps = tk.IntVar(value=30)

        # audio
        self.audio = tk.BooleanVar(value=True)
        self.audio_codec = tk.StringVar(value="opus")
        self.audio_bitrate = tk.StringVar(value="128K")
        self.audio_buffer = tk.IntVar(value=50)

        # recording
        self.record = tk.BooleanVar(value=False)
        self.record_path = tk.StringVar(value="")

        # input
        self.no_control = tk.BooleanVar(value=False)
        self.keyboard_mode = tk.StringVar(value="default")

        # misc
        self.turn_screen_off = tk.BooleanVar(value=False)
        self.stay_awake = tk.BooleanVar(value=True)
        self.always_on_top = tk.BooleanVar(value=False)
        self.print_fps = tk.BooleanVar(value=False)

        # auto-reconnect
        self.auto_reconnect = tk.BooleanVar(value=True)
        self.reconnect_delay = tk.IntVar(value=3)
        self.reconnect_max = tk.IntVar(value=0)

        self._build_ui()
        self._poll_log()
        self.refresh_devices()

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 3}

        # 1. Tools
        paths = ttk.LabelFrame(self.root, text="1. Tools (scrcpy / adb)")
        paths.pack(fill="x", **pad)
        ttk.Label(paths, text="scrcpy:").grid(row=0, column=0, sticky="w", padx=6, pady=3)
        ttk.Entry(paths, textvariable=self.scrcpy_path, width=52).grid(row=0, column=1, sticky="we", pady=3)
        ttk.Button(paths, text="Browse", command=self._browse_scrcpy).grid(row=0, column=2, padx=6)
        ttk.Label(paths, text="adb:").grid(row=1, column=0, sticky="w", padx=6, pady=3)
        ttk.Entry(paths, textvariable=self.adb_path, width=52).grid(row=1, column=1, sticky="we", pady=3)
        ttk.Button(paths, text="Browse", command=self._browse_adb).grid(row=1, column=2, padx=6)
        paths.columnconfigure(1, weight=1)

        # 2. Device (multi-select)
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

        # 3. Connection
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
        ttk.Label(conn, text="Wi-Fi: USB se jodo -> 'Enable Wi-Fi' -> cable nikaalo -> 'Connect'.",
                  foreground="#666").grid(row=4, column=0, columnspan=5, sticky="w", padx=8, pady=(0, 4))

        # 4. Preset
        pre = ttk.LabelFrame(self.root, text="4. Preset")
        pre.pack(fill="x", **pad)
        for i, name in enumerate(PRESETS):
            ttk.Button(pre, text=name, command=lambda n=name: self.apply_preset(n)).grid(
                row=0, column=i, padx=6, pady=4, sticky="we")
            pre.columnconfigure(i, weight=1)
        self.preset_desc = ttk.Label(pre, text=PRESETS["Low Latency"]["desc"],
                                     wraplength=800, foreground="#444")
        self.preset_desc.grid(row=1, column=0, columnspan=len(PRESETS), sticky="w", padx=8, pady=(0, 4))

        # 5. Video
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

        # camera options
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

        # 6. Audio
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

        # 7. Recording
        rec = ttk.LabelFrame(self.root, text="7. Recording")
        rec.pack(fill="x", **pad)
        ttk.Checkbutton(rec, text="Record session to file", variable=self.record).grid(
            row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(rec, textvariable=self.record_path, width=52).grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(rec, text="Save as...", command=self._browse_record).grid(row=0, column=2, padx=6)
        rec.columnconfigure(1, weight=1)
        ttk.Label(rec, text="Khali chhodne par ~/Videos me PhoneMirror_<serial>_<time>.mp4 banegi. "
                            "Multi-device par file naam me serial khud jud jaata hai.",
                  foreground="#666").grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 4))

        # 8. Auto-reconnect
        rc = ttk.LabelFrame(self.root, text="8. Auto-reconnect (per device)")
        rc.pack(fill="x", **pad)
        ttk.Checkbutton(rc, text="Auto-reconnect on disconnect", variable=self.auto_reconnect).grid(
            row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Label(rc, text="Retry delay (s):").grid(row=0, column=1, sticky="e", padx=(16, 4))
        ttk.Spinbox(rc, from_=1, to=60, textvariable=self.reconnect_delay, width=5).grid(row=0, column=2, sticky="w")
        ttk.Label(rc, text="Max attempts (0 = unlimited):").grid(row=0, column=3, sticky="e", padx=(16, 4))
        ttk.Spinbox(rc, from_=0, to=1000, textvariable=self.reconnect_max, width=6).grid(row=0, column=4, sticky="w", padx=(0, 6))

        # 9. Input control
        ctl = ttk.LabelFrame(self.root, text="9. Input control (PC se phone chalao)")
        ctl.pack(fill="x", **pad)
        ttk.Checkbutton(ctl, text="No control (sirf dekho)", variable=self.no_control).grid(
            row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Label(ctl, text="Keyboard mode:").grid(row=0, column=1, sticky="e", padx=(16, 4))
        ttk.Combobox(ctl, textvariable=self.keyboard_mode, state="readonly", width=10,
                     values=["default", "uhid", "sdk", "disabled"]).grid(row=0, column=2, sticky="w")
        ttk.Label(ctl, text="Mouse = touch, keyboard = typing (default on). uhid = Android 11+ best.",
                  foreground="#666").grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 4))

        # actions
        act = ttk.Frame(self.root)
        act.pack(fill="x", **pad)
        self.launch_btn = ttk.Button(act, text="\u25b6  Start Mirroring", command=self.launch)
        self.launch_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(act, text="\u25a0  Stop All", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        ttk.Button(act, text="Copy command(s)", command=self.copy_command).pack(side="right", padx=4)

        # log
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
        state = "normal" if not cam else "disabled"
        self.size_scale.configure(state=state)

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

    def _adb(self):
        adb = self.adb_path.get().strip()
        if not adb or not os.path.exists(adb):
            adb = find_executable("adb")
            if adb:
                self.adb_path.set(adb)
        return adb

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
            "no_control": self.no_control.get(),
            "keyboard_mode": self.keyboard_mode.get(),
            "turn_screen_off": self.turn_screen_off.get(),
            "stay_awake": self.stay_awake.get(),
            "always_on_top": self.always_on_top.get(),
            "print_fps": self.print_fps.get(),
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
            return
        ip = detect_phone_ip(adb, self.primary_serial())
        if ip:
            self.wifi_ip.set(ip)
            self._log(None, "[i] Phone IP: %s" % ip)
            self.status.configure(text="Phone IP: %s" % ip)
        else:
            self._log(None, "[!] IP detect nahi hua.")
            messagebox.showwarning("IP nahi mila", "Phone Wi-Fi se juda hai aur USB se connected hai?")

    def enable_wifi(self):
        adb = self._adb()
        if not adb:
            self._log(None, "[!] adb nahi mila.")
            return
        serial = self.primary_serial()
        if not serial:
            messagebox.showwarning("Device nahi", "Pehle USB se phone jodo aur Refresh dabao.")
            return
        port = int(self.wifi_port.get())
        ok, out = run_adb(adb, ["-s", serial, "tcpip", str(port)])
        self._log(None, "[i] adb tcpip %d -> %s" % (port, "OK" if ok else out))
        if ok:
            self.status.configure(text="Wi-Fi mode on. Cable nikaalo aur 'Connect' dabao.")
        else:
            messagebox.showerror("Enable Wi-Fi fail", out or "adb tcpip fail hua.")

    def connect_wifi(self):
        adb = self._adb()
        if not adb:
            self._log(None, "[!] adb nahi mila.")
            return
        ip = self.wifi_ip.get().strip()
        if not ip:
            messagebox.showwarning("IP nahi", "Phone IP daalo ya 'Auto-detect IP' dabao.")
            return
        target = "%s:%d" % (ip, int(self.wifi_port.get()))
        ok, out = run_adb(adb, ["connect", target])
        self._log(None, "[i] adb connect %s -> %s" % (target, out))
        self.refresh_devices()
        self.status.configure(text="Connect try kiya. Device list check karo.")

    def disconnect_wifi(self):
        adb = self._adb()
        ip = self.wifi_ip.get().strip()
        if adb and ip:
            target = "%s:%d" % (ip, int(self.wifi_port.get()))
            ok, out = run_adb(adb, ["disconnect", target])
            self._log(None, "[i] adb disconnect %s -> %s" % (target, out))
            self.refresh_devices()

    # ---------------- devices ----------------
    def refresh_devices(self):
        adb = self._adb()
        if not adb:
            self.device_status.configure(text="adb nahi mila. Upar path set karo.",
                                         foreground="#b00")
            self._log(None, "[!] adb nahi mila.")
            return

        prev = set()
        for i in self.device_list.curselection():
            if i < len(self.devices):
                prev.add(self.devices[i]["serial"])

        newdevs, err = list_devices(adb)
        if err:
            self.device_status.configure(text="Device list error: %s" % err, foreground="#b00")
            self._log(None, "[!] %s" % err)
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
            self.device_status.configure(text="Device unauthorized/offline. Phone par USB debugging allow karo.",
                                         foreground="#b60")
        else:
            self.device_status.configure(text="Koi device nahi mila.", foreground="#b60")
        self._log(None, "[i] Devices refresh: %d mile." % len(self.devices))

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
            messagebox.showerror("scrcpy nahi mila",
                                 "scrcpy.exe ka path set karo.\n\nInstall: winget install Genymobile.scrcpy")
            return
        serials = self.selected_serials()
        if not serials:
            messagebox.showwarning("Device nahi", "Pehle device select karo (Ctrl/Shift + click).")
            return

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
            sess.proc = None
            sess.running_intent = False
            self._refresh_buttons()
            return

        sess.start_time = time.time()
        sess.running_intent = True
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
            self._start_session(serial)
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
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista" if IS_WINDOWS else "clam")
    except tk.TclError:
        pass
    app = PhoneMirrorApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
