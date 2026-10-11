#!/usr/bin/env python3
"""
PhoneMirror Receiver  -  PC side for the standalone Android app.

Yeh PhoneMirror Server (Android APK) se judta hai: phone se raw H.264 stream
TCP par aati hai, aur yeh use ffplay se low-latency playback karta hai.

Yeh scrcpy wale PhoneMirror.py se ALAG hai:
  * PhoneMirror.py          -> scrcpy wrapper (USB/Wi-Fi, no APK needed)
  * PhoneMirrorReceiver.py  -> standalone engine (Android APK + yeh receiver)

Zaroori: ffplay (ffmpeg) install hona chahiye:
  winget install Gyan.FFmpeg

Run:  python PhoneMirrorReceiver.py
"""

import os
import shutil
import socket
import subprocess
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

IS_WINDOWS = (os.name == "nt")
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


def find_ffplay():
    found = shutil.which("ffplay")
    if found:
        return found
    candidates = []
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        profile = os.environ.get("USERPROFILE", "")
        candidates += [
            os.path.join(local, "Microsoft", "WinGet", "Links", "ffplay.exe"),
            os.path.join(profile, "scoop", "shims", "ffplay.exe"),
            os.path.join(profile, "chocolatey", "bin", "ffplay.exe"),
            r"C:\ffmpeg\bin\ffplay.exe",
            r"C:\Program Files\ffmpeg\bin\ffplay.exe",
        ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def ffplay_command(ffplay, ip, port):
    """Low-latency ffplay command. Stream raw H.264 hai, stdin par aayega."""
    return [
        ffplay,
        "-hide_banner", "-loglevel", "warning",
        "-window_title", "PhoneMirror  -  %s:%d" % (ip, port),
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-probesize", "32",
        "-analyzeduration", "0",
        "-framedrop",
        "-sync", "ext",
        "-f", "h264",
        "-i", "pipe:0",
    ]


class ReceiverApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PhoneMirror Receiver  -  standalone Android stream")
        self.root.minsize(620, 480)

        self.sock = None
        self.ffplay_proc = None
        self.worker = None
        self.log_q = queue.Queue()
        self.running = False

        self.ffplay_path = tk.StringVar(value=find_ffplay() or "")
        self.ip = tk.StringVar(value="")
        self.port = tk.IntVar(value=27183)

        self._build_ui()
        self._poll_log()

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        top = ttk.LabelFrame(self.root, text="1. ffplay (ffmpeg)")
        top.pack(fill="x", **pad)
        ttk.Label(top, text="ffplay:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(top, textvariable=self.ffplay_path, width=48).grid(row=0, column=1, sticky="we", pady=4)
        ttk.Button(top, text="Browse", command=self._browse).grid(row=0, column=2, padx=6)
        top.columnconfigure(1, weight=1)

        conn = ttk.LabelFrame(self.root, text="2. Phone")
        conn.pack(fill="x", **pad)
        ttk.Label(conn, text="Phone IP:").grid(row=0, column=0, sticky="e", padx=(6, 4), pady=6)
        ttk.Entry(conn, textvariable=self.ip, width=18).grid(row=0, column=1, sticky="w")
        ttk.Label(conn, text="Port:").grid(row=0, column=2, sticky="e", padx=(12, 4))
        ttk.Entry(conn, textvariable=self.port, width=8).grid(row=0, column=3, sticky="w")
        ttk.Label(conn, text="(Phone par app khuli rakho - wahi IP dikhati hai.)",
                  foreground="#666").grid(row=1, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 6))

        act = ttk.Frame(self.root)
        act.pack(fill="x", **pad)
        self.start_btn = ttk.Button(act, text="\u25b6  Connect & Play", command=self.start)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(act, text="\u25a0  Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        ttk.Button(act, text="Copy ffplay cmd", command=self.copy_cmd).pack(side="right", padx=4)

        logf = ttk.LabelFrame(self.root, text="Log")
        logf.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(logf, height=10, wrap="word", bg="#111", fg="#d0d0d0",
                           insertbackground="#d0d0d0", font=("Consolas", 9))
        self.log.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        sb.pack(side="right", fill="y", pady=6, padx=(0, 6))
        self.log.configure(yscrollcommand=sb.set, state="disabled")

        self.status = ttk.Label(self.root, text="Ready.", anchor="w", relief="sunken")
        self.status.pack(fill="x", side="bottom")

    def _browse(self):
        p = filedialog.askopenfilename(title="ffplay.exe chuno",
                                       filetypes=[("ffplay", "ffplay*"), ("All", "*.*")])
        if p:
            self.ffplay_path.set(p)

    def _append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll_log(self):
        try:
            while True:
                line = self.log_q.get_nowait()
                if line is None:
                    self._on_end()
                    continue
                self._append_log(line)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log)

    def copy_cmd(self):
        ffplay = self.ffplay_path.get().strip() or "ffplay"
        cmd = ffplay_command(ffplay, self.ip.get() or "IP", int(self.port.get()))
        text = " ".join('"%s"' % c if " " in c else c for c in cmd)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status.configure(text="ffplay command copy ho gaya (stdin par stream pipe hoti hai).")

    def _resolve_ffplay(self):
        ff = self.ffplay_path.get().strip()
        if not ff or not os.path.exists(ff):
            ff = find_ffplay()
            if ff:
                self.ffplay_path.set(ff)
        return ff

    def start(self):
        ffplay = self._resolve_ffplay()
        if not ffplay:
            messagebox.showerror("ffplay nahi mila",
                                 "ffmpeg install karo:\n\nwinget install Gyan.FFmpeg")
            return
        ip = self.ip.get().strip()
        if not ip:
            messagebox.showwarning("IP nahi", "Phone par app khuli hai? Wahan dikha IP daalo.")
            return

        port = int(self.port.get())
        self.running = True
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status.configure(text="Connect ho raha hai %s:%d ..." % (ip, port))

        self.worker = threading.Thread(target=self._run, args=(ffplay, ip, port), daemon=True)
        self.worker.start()

    def _run(self, ffplay, ip, port):
        try:
            self.log_q.put("[i] Connecting to %s:%d ..." % (ip, port))
            sock = socket.create_connection((ip, port), timeout=10)
            sock.settimeout(None)
            self.sock = sock
            self.log_q.put("[i] Connected. ffplay start kar raha hoon...")

            cmd = ffplay_command(ffplay, ip, port)
            self.log_q.put("$ " + " ".join(cmd))
            self.ffplay_proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW,
            )
            self.log_q.put("[i] Streaming... (ffplay window khulni chahiye)")

            while self.running:
                data = sock.recv(65536)
                if not data:
                    self.log_q.put("[i] Phone ne stream band kar di.")
                    break
                try:
                    self.ffplay_proc.stdin.write(data)
                    self.ffplay_proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    self.log_q.put("[!] ffplay band ho gaya (pipe toot gaya).")
                    break
        except socket.timeout:
            self.log_q.put("[!] Connect timeout. Phone par app chalu hai? IP/port sahi hai?")
        except Exception as exc:  # noqa: BLE001
            self.log_q.put("[!] Error: %s" % exc)
        finally:
            self.log_q.put(None)

    def _on_end(self):
        self.running = False
        self.sock = None
        self.ffplay_proc = None
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status.configure(text="Stopped.")

    def stop(self):
        self.running = False
        self.status.configure(text="Ruk raha hai...")
        try:
            if self.sock:
                self.sock.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.ffplay_proc:
                self.ffplay_proc.terminate()
        except Exception:  # noqa: BLE001
            pass

    def on_close(self):
        self.running = False
        try:
            if self.sock:
                self.sock.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.ffplay_proc:
                self.ffplay_proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista" if IS_WINDOWS else "clam")
    except tk.TclError:
        pass
    app = ReceiverApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
