# PhoneMirror

Android screen mirroring tools for Windows. Is repo me **do tarike** hain:

| | **Mode A — scrcpy wrapper** | **Mode B — Standalone** |
|---|---|---|
| Phone par kya chahiye | Kuch install nahi (adb server push karta hai) | **APK** install karo |
| PC par kya | `PhoneMirror.py` | `PhoneMirrorReceiver.py` |
| Engine | scrcpy (proven, polished) | Apna (MediaProjection + MediaCodec) |
| Transport | USB (best) ya Wi-Fi | Wi-Fi / TCP |
| Audio | Haan (clear, Opus) | Nahi (abhi sirf video) |
| Status | Production-quality | **Prototype** |

**Zyadatar logon ke liye Mode A better hai** — koi APK nahi chahiye, latency kam,
audio clear. Mode B tab chuno jab aapko phone par ek asli installable app chahiye
ho (ya seekhne ke liye ki engine andar se kaise kaam karta hai).

---

## Repo layout

```
PhoneMirror.py            # Mode A: scrcpy wrapper GUI (USB / Wi-Fi)
PhoneMirrorReceiver.py    # Mode B: PC receiver (ffplay low-latency playback)
android/                  # Mode B: Android app (Kotlin, MediaProjection + MediaCodec)
.github/workflows/
  build.yml               # Mode A ka Windows .exe build
  build-apk.yml           # Mode B ka Android APK build
requirements.txt
```

---

# Mode A — scrcpy wrapper (recommended)

Low-latency, USB ya Wi-Fi, clear audio, input control, auto-reconnect.
**Phone par kuch install nahi hota** — scrcpy ka server adb khud push karta hai.

## Setup

1. Python 3 (Tkinter built-in).
2. scrcpy + adb: `winget install Genymobile.scrcpy`
3. Phone par **USB debugging** on karo → USB se jodo → "Allow" dabao.
4. `python PhoneMirror.py`

## USB vs Wi-Fi

- **USB** — lowest latency (30–70 ms), sabse stable. Internet use hi nahi karta.
- **Wi-Fi** — cable-free. Setup: USB se jodo → **Enable Wi-Fi** → cable nikaalo →
  **Connect**. Latency zyada (100–250 ms); bitrate 4M, fps 30–45 rakho.

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

## Auto-reconnect

Disconnect hone par (cable hila, phone drop) app khud `adb` se check karke
scrcpy dobara launch kar deta hai. Retry delay aur max attempts tunable.

---

# Mode B — Standalone (APK + receiver)

Apna engine: phone screen capture karta hai aur PC ko stream bhejta hai. scrcpy
ya adb ki zaroorat nahi.

> **Prototype:** sirf video, ek client, app foreground me rehni chahiye.
> Audio abhi nahi. Latency scrcpy se zyada ho sakti hai.

## APK install karo (phone)

1. Release se `PhoneMirrorServer.apk` download karo.
2. Phone par install karo (unknown sources allow karna padega).
3. App kholo → **Start server** → screen capture ki permission do.
4. App screen par apna **IP** aur **port (27183)** dikhayegi — yaad rakho.

## PC receiver chalao

1. ffmpeg install karo: `winget install Gyan.FFmpeg`
2. `python PhoneMirrorReceiver.py`
3. Phone ka IP daalo (port 27183) → **Connect & Play**.

Yeh phone se raw H.264 stream leta hai aur **ffplay** se low-latency playback karta hai
(`-fflags nobuffer -flags low_delay -probesize 32 -frameduration 0 -framedrop`).

Phone aur PC **same Wi-Fi** par hone chahiye. Windows Firewall pehli baar pooch sakta hai.

## Yeh andar se kaise kaam karta hai

1. **Capture** — `MediaProjection` + `VirtualDisplay` screen ko ek Surface par bhejta hai.
2. **Encode** — `MediaCodec` (hardware H.264) us Surface ko encode karta hai,
   8 Mbps, 30 fps, max 1280px.
3. **Bitstream** — MediaCodec AVCC (length-prefixed) deta hai; app use **Annex-B**
   (start codes) me badal ke bhejta hai, kyunki ffplay raw H.264 Annex-B maangta hai.
4. **Transport** — raw stream TCP port 27183 par.
5. **Decode** — PC par ffplay decode + render karta hai.

---

## Build (CI)

Har push par GitHub Actions dono cheezein build karta hai:
- `.exe` (Windows runner, PyInstaller) — `build.yml`
- `.apk` (Ubuntu runner, Gradle) — `build-apk.yml`

Tag (`v*`) push karne par dono files release me attach ho jaate hain.

Local build:
```
# exe
pip install pyinstaller && pyinstaller --onefile --noconsole --name PhoneMirror PhoneMirror.py
# apk
cd android && gradle assembleDebug
```

---

## Common problems

**Mode A**
- "unauthorized" device — phone par "Allow" accept karo, ya `adb kill-server`.
- Wi-Fi connect nahi — same Wi-Fi? `adb tcpip 5555` chalaya? firewall port 5555?
- Audio nahi — scrcpy 2.0+ chahiye.

**Mode B**
- Receiver connect nahi — phone aur PC same Wi-Fi? App chal rahi hai? Firewall port 27183?
- ffplay window nahi khulti — ffmpeg install hai? `ffplay -version` chala ke check karo.
- Stream ruk jaata hai — phone par app foreground me rakho (background me Android capture rok deta hai).
- Audio nahi aata — Mode B abhi video-only hai.

---

## Aage kya

Mode B me add ho sakta hai: audio (AudioPlaybackCapture + Opus), foreground service
(background streaming), touch/input reverse channel, multi-client. Mode A me:
clipboard sync, multi-device.
