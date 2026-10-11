# PhoneMirror

> [!WARNING]
> **🚧 `PhoneMirrorServer.apk` (Mode B) filhaal download ya use na karein.**
> Yeh ek **experimental prototype** hai aur kisi asli device par test nahi hua.
> Sirf experiment/seekhne ke liye rakha gaya hai.
> Screen mirroring ke liye **Mode A** (`PhoneMirror.py` / `PhoneMirror.exe`) use karein.

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
| Status | Production-quality | **Prototype — filhaal use na karein** |

**Zyadatar logon ke liye Mode A better hai.** Mode B abhi experimental hai.

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

- **Device** list me ek se zyada phone chuno: **Ctrl + click** ya **Shift + click**.
- **Start Mirroring** dabao — har device ke liye alag scrcpy window khulti hai.
- Har device ka apna **auto-reconnect**; log me har line `[serial]` prefix ke saath.
- **Stop All** sab sessions band kar deta hai.

## Screen recording

- **7. Recording** me "Record session to file" on karo.
- "Save as..." se path chuno, ya khali chhodo — phir `~/Videos` me
  `PhoneMirror_<serial>_<timestamp>.mp4` ban jaati hai.
- Multi-device par file naam me serial khud jud jaata hai.

## Camera mirroring

- **5. Video** → Source: **Camera** chuno (scrcpy 2.2+ chahiye).
- Facing: `back` / `front` / `external`; size aur fps alag se.
- Camera mode me `Max size` slider disable ho jaata hai (`--camera-size` lagta hai).

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

Disconnect hone par app khud `adb` se check karke us device ka scrcpy dobara
launch kar deta hai. Retry delay aur max attempts tunable.

---

# Mode B — Standalone (APK + receiver)

> [!WARNING]
> **🚧 Filhaal download ya use na karein.**
> Yeh ek **experimental prototype** hai jo kisi asli device par test nahi hua.
> Iska APK (`PhoneMirrorServer.apk`) sirf development/experiment ke liye hai.
> Screen mirroring ke liye **Mode A** use karein.

Apna engine: phone screen capture karta hai aur PC ko stream bhejta hai.
Yeh scrcpy se alag, ghar-ka-bana engine hai — sirf video, ek client, aur app
foreground me rehni chahiye.

## (Reference) APK + receiver kaise chalega

1. `PhoneMirrorServer.apk` phone par install → app kholo → **Start server** → capture permission.
2. App jo IP dikhaye, wo PC par `PhoneMirrorReceiver.py` me daalo (port 27183) → **Connect & Play**.
3. ffmpeg chahiye PC par: `winget install Gyan.FFmpeg`.

Phone aur PC same Wi-Fi par hone chahiye.

## Andar se kaise kaam karta hai

1. **Capture** — `MediaProjection` + `VirtualDisplay` → Surface.
2. **Encode** — `MediaCodec` hardware H.264, 8 Mbps, 30 fps, max 1280px.
3. **Bitstream** — AVCC → Annex-B convert.
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
- Multi-device me ek window nahi khuli — Refresh karo.

**Mode B** (filhaal use na karein — sirf reference)
- Receiver connect nahi — same Wi-Fi? app chalu? firewall port 27183?
- ffplay window nahi khulti — ffmpeg install hai? `ffplay -version`.

---

## Aage kya

Mode A: clipboard sync, settings save/load.
Mode B: pehle device par test, phir audio (AudioPlaybackCapture + Opus).
