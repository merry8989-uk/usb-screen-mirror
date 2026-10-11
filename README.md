# PhoneMirror

Android screen mirroring tools for Windows. Is repo me **do tarike** hain:

| | **Mode A — scrcpy wrapper** | **Mode B — Standalone** |
|---|---|---|
| Phone par kya chahiye | Kuch install nahi (adb server push karta hai) | **APK** install karo |
| PC par kya | `PhoneMirror.py` | `PhoneMirrorReceiver.py` |
| Engine | scrcpy (proven, polished) | Apna (MediaProjection + MediaCodec) |
| Transport | USB (best) ya Wi-Fi | Wi-Fi / TCP |
| Audio | Haan (clear, Opus) | Nahi (abhi sirf video) |
| Multi-device | Haan | Nahi |
| Recording | Haan (mp4) | Nahi |
| Camera mirroring | Haan (scrcpy 2.2+) | Nahi |
| Status | Production-quality | **Prototype** |

**Zyadatar logon ke liye Mode A better hai.** Mode B seekhne/experiment ke liye.

---

## Repo layout

```
PhoneMirror.py            # Mode A: scrcpy wrapper GUI (multi-device, recording, camera)
PhoneMirrorReceiver.py    # Mode B: PC receiver (ffplay low-latency playback)
android/                  # Mode B: Android app (Kotlin, MediaProjection + MediaCodec)
.github/workflows/
  build.yml               # Mode A ka Windows .exe build
  build-apk.yml           # Mode B ka Android APK build
requirements.txt
```

---

# Mode A — scrcpy wrapper (recommended)

Low-latency USB/Wi-Fi mirroring, clear audio, input control, auto-reconnect,
**multi-device**, **screen recording**, aur **camera mirroring**.
Phone par kuch install nahi hota.

## Setup

1. Python 3 (Tkinter built-in).
2. scrcpy + adb: `winget install Genymobile.scrcpy`
3. Phone par **USB debugging** on karo → USB se jodo → "Allow" dabao.
4. `python PhoneMirror.py`

## Multi-device

- **Device** list me ek se zyada phone chuno: **Ctrl + click** (ek-ek jodne ke liye)
  ya **Shift + click** (range ke liye).
- **Start Mirroring** dabao — har device ke liye alag scrcpy window khulti hai.
- Har device ka apna **auto-reconnect** chalta hai; log me har line `[serial]` prefix
  ke saath aati hai.
- **Stop All** sab sessions band kar deta hai.
- Wi-Fi helpers (Enable/Connect/detect IP) primary (pehle chune gaye) device par chalte hain.

## Screen recording

- **7. Recording** me "Record session to file" on karo.
- "Save as..." se path chuno, ya khali chhodo — phir `~/Videos` me
  `PhoneMirror_<serial>_<timestamp>.mp4` ban jaati hai.
- Multi-device par file naam me serial khud jud jaata hai (jaise `sess_A.mp4`, `sess_B.mp4`).
- Format extension se decide hota hai (`.mp4` ya `.mkv`).

## Camera mirroring

- **5. Video** → Source: **Camera** chuno (scrcpy 2.2+ chahiye).
- Facing: `back` / `front` / `external`; Camera size: `1920x1080` / `1280x720` / etc.
- Camera FPS alag se set hota hai.
- Camera mode me `Max size` slider disable ho jaata hai (uski jagah `--camera-size` lagta hai).

## USB vs Wi-Fi

- **USB** — lowest latency (30–70 ms), sabse stable. Internet use hi nahi karta.
- **Wi-Fi** — cable-free. Setup: USB se jodo → **Enable Wi-Fi** → cable nikaalo → **Connect**.

## Presets

| Preset | Size | Bitrate | FPS | Audio |
|---|---|---|---|---|
| Low Latency | 1024 | 8M | 60 | 128K |
| Low Phone Load | 800 | 4M | 30 | 96K |
| Balanced | 1280 | 8M | 60 | 128K |
| High Quality | 1920 | 16M | 60 | 256K |

## Input control

Mouse = touch, keyboard = typing (scrcpy me default on). App se:
`No control` toggle, aur keyboard mode `default` / `uhid` (Android 11+) / `sdk` / `disabled`.

## Auto-reconnect (per device)

Disconnect hone par (cable hila, phone drop) app khud `adb` se check karke us device
ka scrcpy dobara launch kar deta hai. Retry delay aur max attempts tunable.

---

# Mode B — Standalone (APK + receiver)

Apna engine: phone screen capture karta hai aur PC ko stream bhejta hai.

> **Prototype:** sirf video, ek client, app foreground me rehni chahiye. Audio abhi nahi.

## APK install karo (phone)

1. Release se `PhoneMirrorServer.apk` download karo → install karo.
2. App kholo → **Start server** → screen capture permission do.
3. App jo **IP** aur port (**27183**) dikhaye, wo note karo.

## PC receiver chalao

1. ffmpeg install karo: `winget install Gyan.FFmpeg`
2. `python PhoneMirrorReceiver.py`
3. Phone ka IP daalo (port 27183) → **Connect & Play**.

Phone aur PC same Wi-Fi par hone chahiye. Windows Firewall pehli baar pooch sakta hai.

## Andar se kaise kaam karta hai

1. **Capture** — `MediaProjection` + `VirtualDisplay` → Surface.
2. **Encode** — `MediaCodec` hardware H.264, 8 Mbps, 30 fps, max 1280px.
3. **Bitstream** — AVCC → Annex-B convert (ffplay raw H.264 Annex-B maangta hai).
4. **Transport** — TCP port 27183.
5. **Decode** — PC par ffplay.

---

## Build (CI)

Har push par GitHub Actions dono build karta hai: `.exe` (Windows) aur `.apk` (Ubuntu).
Tag (`v*`) par dono release me attach ho jaate hain.

Local build:
```
pip install pyinstaller && pyinstaller --onefile --noconsole --name PhoneMirror PhoneMirror.py
cd android && gradle assembleDebug
```

---

## Common problems

**Mode A**
- "unauthorized" device — phone par "Allow" accept karo, ya `adb kill-server`.
- Wi-Fi connect nahi — same Wi-Fi? `adb tcpip 5555` chalaya? firewall port 5555?
- Camera nahi chala — scrcpy 2.2+ chahiye (`scrcpy --version`).
- Recording file nahi bani — folder ka path valid hai? disk space hai?
- Multi-device me ek window nahi khuli — us device ka serial galat/stale? Refresh karo.

**Mode B**
- Receiver connect nahi — same Wi-Fi? app chalu? firewall port 27183?
- ffplay window nahi khulti — ffmpeg install hai? `ffplay -version`.
- Stream ruk jaata hai — phone par app foreground me rakho.

---

## Aage kya

Mode A: clipboard sync, settings save/load, audio-only mode.
Mode B: audio (AudioPlaybackCapture + Opus), foreground service, input reverse channel.
