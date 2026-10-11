#!/usr/bin/env python3
"""
PhoneMirror  -  USB Screen Mirror for Android, powered by scrcpy.

Ek chhota Windows + Python GUI jo scrcpy ko wrap karta hai.
Kaam:
  * USB se jude Android devices detect karta hai (adb ke through)
  * Kam-latency / kam-phone-load ke liye ready-made presets deta hai
  * Clear audio forwarding (Opus) with tunable bitrate/buffer
  * Auto-reconnect: cable hile ya phone disconnect ho to khud wapas judta hai
  * scrcpy ko sahi flags ke saath launch karta hai aur uski output dikhata hai

Yeh scrcpy ka engine use karta hai (hardware H.264/HEVC encode + USB transport),
isliye latency kam rehti hai aur phone par load bhi kam padta hai.

Sirf Python 3 + scrcpy + adb chahiye. Tkinter Python ke saath aata hai.

Run:  python PhoneMirror.py
"""

import os
import sys
import time
import shutil
import subprocess
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

APP_TITLE = "PhoneMirror  -  USB Screen Mirror (scrcpy wrapper)"
IS_WINDOWS = (os.name == "nt")
# Windows par child process ka black console window chhupane ke liye
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


# --------------------------------------------------------------------------- #
#  Executable / device discovery
# --------------------------------------------------------------------------- #
def find_executable(name):
    """PATH aur common install locations me exe/dll dhoondo."""
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


# --------------------------------------------------------------------------- #
#  Presets  -  yahi wo magic hai jo latency / load / audio ko control karta hai
# --------------------------------------------------------------------------- #
PRESETS = {
    "Low Latency": {
        "max_size": 1024, "bitrate": "8M", "max_fps": 60, "codec": "h264",
        "audio": True, "audio_codec": "opus", "audio_bitrate": "128K", "audio_buffer": 25,
        "desc": "Sabse tez. 1024px, 8 Mbps, 60fps, audio 128K. Gaming / interactive kaam ke liye.",
    },
    "Low Phone Load": {
        "max_size": 800, "bitrate": "4M", "max_fps": 30, "codec": "h264",
        "audio": True, "audio_codec": "opus", "audio_bitrate": "96K", "audio_buffer": 50,
        "desc": "Phone par sabse kam load + kam heat. 800px, 4 Mbps, 30fps. Audio load na ke barabar.",
    },
    "Balanced": {
        "max_size": 1280, "bitrate": "8M", "max_fps": 60, "codec": "h264",
        "audio": True, "audio_codec": "opus", "audio_bitrate": "128K", "audio_buffer": 50,
        "desc": "Rozana kaam ke liye theek-thaak. 1280px, 8 Mbps, 60fps, clear audio.",
    },
    "High Quality": {
        "max_size": 1920, "bitrate": "16M", "max_fps": 60, "codec": "h265",
        "audio": True, "audio_codec": "opus", "audio_bitrate": "256K", "audio_buffer": 100,
        "desc": "Sharp picture + best audio. 1920px, 16 Mbps, 256K audio. Zyada bandwidth + load.",
    },
}


def build_command(scrcpy_path, serial, s):
    """Settings dict se scrcpy command line banao."""
    cmd = [scrcpy_path]
    if serial:
        cmd += ["--serial", serial]
    cmd += ["--max-size", str(s["max_size"])]
    cmd += ["--video-bit-rate", s["bitrate"]]
    cmd += ["--max-fps", str(s["max_fps"])]
    cmd += ["--video-codec", s["codec"]]
    # Latency kam karne ke liye video buffering almost zero
    cmd += ["--video-buffer", "0", "--display-buffer", "0"]
    # OpenGL renderer low-latency hota hai (default hi hai, explicit rakha)
    cmd += ["--render-driver", "opengl"]

    # --- audio ---
    if s.get("audio"):
        cmd += ["--audio-codec", s.get("audio_codec", "opus")]
        cmd += ["--audio-bit-rate", s.get("audio_bitrate", "128K")]
        cmd += ["--audio-buffer", str(s.get("audio_buffer", 50))]
    else:
        cmd += ["--no-audio"]

    if s.get("turn_screen_off"):
        cmd += ["--turn-screen-off"]
    if s.get("stay_awake"):
        cmd += ["--stay-awake"]
    if s.get("no_control"):
        cmd += ["--no-control"]
    if s.get("always_on_top"):
        cmd += ["--always-on-top"]
    if s.get("print_fps"):
        cmd += ["--print-fps"]
    return cmd


# --------------------------------------------------------------------------- #
#  GUI
# --------------------------------------------------------------------------- #
class PhoneMirrorApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.minsize(800, 700)

        self.proc = None
        self.log_q = queue.Queue()
        self.devices = []
        self.scrcpy_path = tk.StringVar(value=find_executable("scrcpy") or "")
        self.adb_path = tk.StringVar(value=find_executable("adb") or "")

        # run state (auto-reconnect ke liye)
        self.running_intent = False   # kya hum mirroring chahte hain?
        self.user_stopped = False     # user ne khud stop kiya?
        self.reconnect_attempts = 0
        self._proc_start_time = 0.0

        # video settings
        self.max_size = tk.IntVar(value=1024)
        self.bitrate = tk.StringVar(value="8M")
        self.max_fps = tk.IntVar(value=60)
        self.codec = tk.StringVar(value="h264")
        # audio settings
        self.audio = tk.BooleanVar(value=True)
        self.audio_codec = tk.StringVar(value="opus")
        self.audio_bitrate = tk.StringVar(value="128K")
        self.audio_buffer = tk.IntVar(value=50)
        # other toggles
        self.turn_screen_off = tk.BooleanVar(value=False)
        self.stay_awake = tk.BooleanVar(value=True)
        self.no_control = tk.BooleanVar(value=False)
        self.always_on_top = tk.BooleanVar(value=False)
        self.print_fps = tk.BooleanVar(value=False)
        # auto-reconnect
        self.auto_reconnect = tk.BooleanVar(value=True)
        self.reconnect_delay = tk.IntVar(value=3)
        self.reconnect_max = tk.IntVar(value=0)   # 0 = unlimited

        self._build_ui()
        self._poll_log()
        self.refresh_devices()

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # --- top: executable paths ---
        paths = ttk.LabelFrame(self.root, text="1. Tools (scrcpy / adb)")
        paths.pack(fill="x", **pad)

        ttk.Label(paths, text="scrcpy:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(paths, textvariable=self.scrcpy_path, width=52).grid(row=0, column=1, sticky="we", pady=4)
        ttk.Button(paths, text="Browse", command=self._browse_scrcpy).grid(row=0, column=2, padx=6)

        ttk.Label(paths, text="adb:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(paths, textvariable=self.adb_path, width=52).grid(row=1, column=1, sticky="we", pady=4)
        ttk.Button(paths, text="Browse", command=self._browse_adb).grid(row=1, column=2, padx=6)
        paths.columnconfigure(1, weight=1)

        # --- device ---
        dev = ttk.LabelFrame(self.root, text="2. Device")
        dev.pack(fill="x", **pad)
        self.device_combo = ttk.Combobox(dev, state="readonly", width=56)
        self.device_combo.grid(row=0, column=0, sticky="we", padx=6, pady=6)
        ttk.Button(dev, text="Refresh", command=self.refresh_devices).grid(row=0, column=1, padx=6)
        self.device_status = ttk.Label(dev, text="", foreground="#666")
        self.device_status.grid(row=1, column=0, columnspan=2, sticky="w", padx=8)
        dev.columnconfigure(0, weight=1)

        # --- presets ---
        pre = ttk.LabelFrame(self.root, text="3. Preset")
        pre.pack(fill="x", **pad)
        for i, name in enumerate(PRESETS):
            ttk.Button(pre, text=name, command=lambda n=name: self.apply_preset(n)).grid(
                row=0, column=i, padx=6, pady=6, sticky="we")
            pre.columnconfigure(i, weight=1)
        self.preset_desc = ttk.Label(pre, text=PRESETS["Low Latency"]["desc"],
                                     wraplength=700, foreground="#444")
        self.preset_desc.grid(row=1, column=0, columnspan=len(PRESETS), sticky="w", padx=8, pady=(0, 6))

        # --- video tunables ---
        tun = ttk.LabelFrame(self.root, text="4. Video")
        tun.pack(fill="x", **pad)

        ttk.Label(tun, text="Max size (px):").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.size_scale = ttk.Scale(tun, from_=480, to=2560, variable=self.max_size,
                                    orient="horizontal", command=self._on_size)
        self.size_scale.grid(row=0, column=1, sticky="we", padx=6)
        self.size_lbl = ttk.Label(tun, text="1024", width=6)
        self.size_lbl.grid(row=0, column=2, sticky="w")

        ttk.Label(tun, text="Bitrate:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(tun, textvariable=self.bitrate, state="readonly", width=10,
                     values=["2M", "4M", "6M", "8M", "12M", "16M", "24M"]).grid(row=1, column=1, sticky="w", padx=6)

        ttk.Label(tun, text="Max FPS:").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(tun, textvariable=self.max_fps, state="readonly", width=10,
                     values=[15, 30, 45, 60, 90, 120]).grid(row=2, column=1, sticky="w", padx=6)

        ttk.Label(tun, text="Codec:").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(tun, textvariable=self.codec, state="readonly", width=10,
                     values=["h264", "h265", "av1"]).grid(row=3, column=1, sticky="w", padx=6)

        vopts = ttk.Frame(tun)
        vopts.grid(row=0, column=3, rowspan=4, sticky="nw", padx=16)
        ttk.Checkbutton(vopts, text="Turn phone screen off", variable=self.turn_screen_off).pack(anchor="w")
        ttk.Checkbutton(vopts, text="Stay awake", variable=self.stay_awake).pack(anchor="w")
        ttk.Checkbutton(vopts, text="No control (sirf dekho)", variable=self.no_control).pack(anchor="w")
        ttk.Checkbutton(vopts, text="Always on top", variable=self.always_on_top).pack(anchor="w")
        ttk.Checkbutton(vopts, text="Print FPS (debug)", variable=self.print_fps).pack(anchor="w")
        tun.columnconfigure(1, weight=1)

        # --- audio ---
        aud = ttk.LabelFrame(self.root, text="5. Audio")
        aud.pack(fill="x", **pad)
        ttk.Checkbutton(aud, text="Audio on (clear)", variable=self.audio).grid(
            row=0, column=0, sticky="w", padx=6, pady=6)

        ttk.Label(aud, text="Codec:").grid(row=0, column=1, sticky="e", padx=(16, 4))
        ttk.Combobox(aud, textvariable=self.audio_codec, state="readonly", width=8,
                     values=["opus", "aac", "flac", "raw"]).grid(row=0, column=2, sticky="w")

        ttk.Label(aud, text="Bitrate:").grid(row=0, column=3, sticky="e", padx=(16, 4))
        ttk.Combobox(aud, textvariable=self.audio_bitrate, state="readonly", width=8,
                     values=["64K", "96K", "128K", "192K", "256K", "320K"]).grid(row=0, column=4, sticky="w")

        ttk.Label(aud, text="Buffer (ms):").grid(row=0, column=5, sticky="e", padx=(16, 4))
        ttk.Combobox(aud, textvariable=self.audio_buffer, state="readonly", width=6,
                     values=[0, 25, 50, 100, 150, 200]).grid(row=0, column=6, sticky="w", padx=(0, 6))

        # --- auto-reconnect ---
        rc = ttk.LabelFrame(self.root, text="6. Auto-reconnect")
        rc.pack(fill="x", **pad)
        ttk.Checkbutton(rc, text="Auto-reconnect on disconnect", variable=self.auto_reconnect).grid(
            row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Label(rc, text="Retry delay (s):").grid(row=0, column=1, sticky="e", padx=(16, 4))
        ttk.Spinbox(rc, from_=1, to=60, textvariable=self.reconnect_delay, width=5).grid(row=0, column=2, sticky="w")
        ttk.Label(rc, text="Max attempts (0 = unlimited):").grid(row=0, column=3, sticky="e", padx=(16, 4))
        ttk.Spinbox(rc, from_=0, to=1000, textvariable=self.reconnect_max, width=6).grid(row=0, column=4, sticky="w", padx=(0, 6))

        # --- actions ---
        act = ttk.Frame(self.root)
        act.pack(fill="x", **pad)
        self.launch_btn = ttk.Button(act, text="\u25b6  Start Mirroring", command=self.launch)
        self.launch_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(act, text="\u25a0  Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        ttk.Button(act, text="Copy command", command=self.copy_command).pack(side="right", padx=4)

        # --- log ---
        logf = ttk.LabelFrame(self.root, text="Log")
        logf.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(logf, height=12, wrap="word", bg="#111", fg="#d0d0d0",
                           insertbackground="#d0d0d0", font=("Consolas", 9))
        self.log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        sb.pack(side="right", fill="y", pady=6, padx=(0, 6))
        self.log.configure(yscrollcommand=sb.set, state="disabled")

        self.status = ttk.Label(self.root, text="Ready.", anchor="w", relief="sunken")
        self.status.pack(fill="x", side="bottom")

    # ---------------- helpers ----------------
    def _on_size(self, _val):
        self.size_lbl.configure(text=str(int(float(self.max_size.get()))))

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

    def _append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

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
            "max_size": int(float(self.max_size.get())),
            "bitrate": self.bitrate.get(),
            "max_fps": int(self.max_fps.get()),
            "codec": self.codec.get(),
            "audio": self.audio.get(),
            "audio_codec": self.audio_codec.get(),
            "audio_bitrate": self.audio_bitrate.get(),
            "audio_buffer": int(self.audio_buffer.get()),
            "turn_screen_off": self.turn_screen_off.get(),
            "stay_awake": self.stay_awake.get(),
            "no_control": self.no_control.get(),
            "always_on_top": self.always_on_top.get(),
            "print_fps": self.print_fps.get(),
        }

    def selected_serial(self):
        idx = self.device_combo.current()
        if idx < 0 or idx >= len(self.devices):
            return None
        return self.devices[idx]["serial"]

    # ---------------- devices ----------------
    def refresh_devices(self):
        adb = self.adb_path.get().strip()
        if not adb or not os.path.exists(adb):
            adb = find_executable("adb")
            if adb:
                self.adb_path.set(adb)
        if not adb:
            self.device_status.configure(text="adb nahi mila. Upar path set karo ya platform-tools install karo.",
                                         foreground="#b00")
            self._append_log("[!] adb nahi mila.")
            return

        self.devices, err = list_devices(adb)
        if err:
            self.device_status.configure(text="Device list error: %s" % err, foreground="#b00")
            self._append_log("[!] %s" % err)
            return

        labels = [d["label"] for d in self.devices]
        self.device_combo["values"] = labels
        if labels:
            self.device_combo.current(0)
            ready = [d for d in self.devices if d["state"] == "device"]
            if ready:
                self.device_status.configure(
                    text="%d device mila. Mirror ke liye ready." % len(ready), foreground="#080")
            else:
                self.device_status.configure(
                    text="Device mila par 'unauthorized'/'offline' hai. Phone par USB debugging allow karo.",
                    foreground="#b60")
        else:
            self.device_status.configure(text="Koi device nahi mila. USB cable + USB debugging check karo.",
                                         foreground="#b60")
        self._append_log("[i] Devices refresh: %d mile." % len(self.devices))

    # ---------------- run ----------------
    def copy_command(self):
        scrcpy = self.scrcpy_path.get().strip() or "scrcpy"
        cmd = build_command(scrcpy, self.selected_serial(), self.current_settings())
        text = " ".join('"%s"' % c if " " in c else c for c in cmd)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status.configure(text="Command clipboard me copy ho gaya.")

    def _resolve_scrcpy(self):
        scrcpy = self.scrcpy_path.get().strip()
        if not scrcpy or not os.path.exists(scrcpy):
            scrcpy = find_executable("scrcpy")
            if scrcpy:
                self.scrcpy_path.set(scrcpy)
        return scrcpy

    def launch(self):
        """User ne Start dabaya - naya session shuru."""
        scrcpy = self._resolve_scrcpy()
        if not scrcpy:
            messagebox.showerror("scrcpy nahi mila",
                                 "scrcpy.exe ka path set karo.\n\nInstall: winget install Genymobile.scrcpy")
            return
        if not self.devices:
            messagebox.showwarning("Device nahi", "Pehle Refresh dabao aur phone connect karo.")
            return

        self.user_stopped = False
        self.running_intent = True
        self.reconnect_attempts = 0
        self._start_process()

    def _start_process(self):
        scrcpy = self._resolve_scrcpy()
        if not scrcpy:
            self._append_log("[!] scrcpy nahi mila, reconnect rok raha hoon.")
            self._set_idle()
            return
        serial = self.selected_serial()
        cmd = build_command(scrcpy, serial, self.current_settings())
        self._append_log("$ " + " ".join(cmd))
        self.status.configure(text="Mirroring shuru ho rahi hai...")

        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, creationflags=CREATE_NO_WINDOW,
            )
        except Exception as exc:  # noqa: BLE001
            self._append_log("[!] Launch fail: %s" % exc)
            self._set_idle()
            return

        self._proc_start_time = time.time()
        self.launch_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def _reader(self, proc):
        try:
            for line in iter(proc.stdout.readline, ""):
                if not line:
                    break
                self.log_q.put(line.rstrip())
        finally:
            self.log_q.put(None)

    def _poll_log(self):
        try:
            while True:
                line = self.log_q.get_nowait()
                if line is None:
                    self._on_process_end()
                    continue
                self._append_log(line)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log)

    def _on_process_end(self):
        if self.proc is not None:
            elapsed = time.time() - self._proc_start_time
            self._append_log("[i] scrcpy band ho gaya (%.0f s chalne ke baad)." % elapsed)
            self.proc = None
            # Agar session kaafi der chala, to yeh crash nahi tha - counter reset
            if elapsed >= 15:
                self.reconnect_attempts = 0

        # Auto-reconnect decide
        if self.running_intent and not self.user_stopped and self.auto_reconnect.get():
            delay = int(self.reconnect_delay.get())
            self.status.configure(text="Disconnect — %d s me reconnect try..." % delay)
            self._append_log("[i] Auto-reconnect: %d s baad try karunga." % delay)
            self.root.after(delay * 1000, self._attempt_reconnect)
        else:
            self._set_idle()

    def _attempt_reconnect(self):
        if not self.running_intent or self.user_stopped or not self.auto_reconnect.get():
            return

        maxa = int(self.reconnect_max.get())
        if maxa and self.reconnect_attempts >= maxa:
            self._append_log("[!] Max reconnect attempts (%d) pura. Ruk raha hoon." % maxa)
            self._set_idle()
            return

        # Device abhi juda hua hai ya nahi, wo check karo
        adb = self.adb_path.get().strip() or find_executable("adb")
        serial = self.selected_serial()
        present = False
        if adb:
            devs, _ = list_devices(adb)
            present = any(d["serial"] == serial and d["state"] == "device" for d in devs)

        if present:
            self.reconnect_attempts += 1
            self._append_log("[i] Device wapas mil gaya. Reconnect attempt #%d." % self.reconnect_attempts)
            self._start_process()
        else:
            delay = int(self.reconnect_delay.get())
            self._append_log("[i] Device abhi nahi mila, %d s baad dobara try..." % delay)
            self.root.after(delay * 1000, self._attempt_reconnect)

    def _set_idle(self):
        self.running_intent = False
        self.launch_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status.configure(text="Stopped.")

    def stop(self):
        self.user_stopped = True
        self.running_intent = False
        if self.proc is not None:
            self.status.configure(text="Ruk raha hai...")
            try:
                self.proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        else:
            self._append_log("[i] Stop dabaya, reconnect band.")
            self._set_idle()

    def on_close(self):
        self.user_stopped = True
        self.running_intent = False
        if self.proc is not None:
            try:
                self.proc.terminate()
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
