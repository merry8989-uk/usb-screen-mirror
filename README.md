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

## Reliability notes

- Saare `adb` / `scrcpy` calls **background threads** me chalte hain (result main thread par queue se aata hai) —
  UI kabhi freeze nahi hoti, chahe adb slow ya hang ho.
- Numeric fields (port, retry delay, max attempts, size, fps) me galat text daalo to **crash nahi** —
  safe default + range clamp lagta hai.
- Startup crash ho to `logs/startup-crash.log` me likha jaata hai aur ek error dialog dikhta hai
  (silent death nahi).
- Log files ke handles **open rehte hain** (per-line open/close nahi) — high-frequency logging smooth,
  aur daily rotate par purane handles band hoke naye khul jaate hain.
- Report banana ab **non-blocking** hai (scrcpy/adb version background me cache hote hain).
- **Settings yaad rehti hain** — saari settings (preset, video/audio, recording, auto-reconnect,
  Wi-Fi IP/port, tool paths) aur last device selection `~/.phonemirror/config.json` me save hoti hain
  aur app dobara kholne par wapas lag jaati hain.
- **Device auto-refresh** — har 5 second background me quiet scan (Device frame me checkbox se on/off).
  Naya phone lagao to khud list me aa jaata hai; jab kuch na badle to UI/log churn nahi hota.
- **Toast notifications** — warning/error ab chhota non-modal toast dikhata hai (flow block nahi hota).
  Sirf destructive confirm (Clean) aur startup crash modal rehte hain.

## Diagnostics (logs export + email)

App me **⚙ Diagnostics** button hai (neeche daayein). Yeh ek alag window kholta hai jahan se:

- **On/Off setting** — "Collect diagnostics" checkbox. **Default ON**. Off karne par app
  koi log/technical data collect nahi karti (setting yaad rehti hai).
- **Preview** — current report (environment, scrcpy/adb version, devices, settings, log).
- **Refresh** — report dobara banao. **Clean** — collected data + log clear karo.
- **Copy report** — poora report clipboard me.
- **Save as...** — format chuno: **txt, md, json, jsonl, csv, xlsx, zip**. Default jagah
  `~/Documents/PhoneMirror/`. **zip** ek poora bundle hai (report.md / report.txt / report.json /
  events.jsonl + saare device logs).
- **Share bundle** — zip bundle banata hai, uska path clipboard me copy karta hai, aur folder khol deta hai;
  phir kisi bhi app (WhatsApp / Telegram / email) me paste ya attach kar do.
- **Email (Gmail)** / **Email (mail app)** — **`br19shc39@gmail.com`** par
  compose khulta hai, To/Subject/Body pehle se bhare hue (summary + last 40 log lines).
  Poora zip bundle file me save hoke clipboard me bhi copy ho jaata hai — bas usse attach kar dena.
- **Open exports** / **Open logs** — exports ya logs ki folder kholo.

### Logs device par continuously save hote hain

Diagnostics ON hone par app logs **disk par continuously** likhti rehti hai:
`~/Documents/PhoneMirror/logs/`

- `events-YYYYMMDD.jsonl` — structured events (ek per line, schema-compliant)
- `phonemirror-YYYYMMDD.log` — human-readable log
- **Daily rotate** + **retention** (7 din se purani files auto-delete).
- **Clean** dabane par in-memory data + on-disk logs dono clear ho jaate hain.
- Diagnostics off karne par app naya kuch collect ya likhti nahi (purani files rah jaati hain).

`.xlsx` ke liye `openpyxl` chahiye (`pip install openpyxl`); na ho to CSV/TXT/MD/JSONL use karo.

### Structured logging (ProGallery spec + log taxonomy)

Diagnostics ke andar ek **structured event log** chalta hai, jo shared ProGallery standard aur
log taxonomy follow karta hai (dekho [`docs/ProGallery_Logging_Spec.md`](docs/ProGallery_Logging_Spec.md)
+ [`docs/Log_Types_and_Severity.md`](docs/Log_Types_and_Severity.md)):

- **Common envelope** — har event me `event_name`, `schema_version`, `timestamp` (ISO 8601 UTC),
  `session_id`, `app_id`, `app_version`, `environment`, `platform`, `os`, `device_model`,
  `screen_or_route`, `log_level`, `severity`, `category`, `message`, aur zaroorat par
  `attempt_id` / `request_id` / `network_type` / `release_channel`.
- **Correlation ids** — `session_id` (har app launch par naya) aur `attempt_id`
  (launch / reconnect jaise actions ko intent→outcome se jodta hai).
- **Categories (12)** — `application`, `error`, `security`, `performance`, `user_activity`,
  `infrastructure`, `api_network`, `database`, `audit`, `analytics`, `background_job`, `debug_trace`.
  App in me se **10 applicable** categories emit karti hai (`database` / `analytics` is app me nahi).
- **Severities (6)** — `trace` / `debug` / `info` / `warn` / `error` / `fatal`, deliberately.
- **Sampling** — warn/error/fatal 100%, trace/debug/info sampled (rate configurable).
- **Retention** — max events + 7 din (auto-purge).
- **PII redaction** — email aur raw file paths log me kabhi nahi jaate (app + web ke liye same rules).
- **Events** — `session_start`, `environment_snapshot`, `screen_view`, `preset_applied`,
  `device_state_resolved`, `device_refresh_result`, `device_authorization_failed` (security),
  `mirror_requested` / `mirror_result`, `reconnect_attempt` / `reconnect_result` / `reconnect_loop`,
  `adb_command`, `performance_marker`, `settings_changed`, `diagnostics_toggled`,
  `diagnostics_cleaned`, `export_saved`, `email_compose`, `share_bundle`, `tool_probe`,
  `error_state_shown`, `crash`, `queue_drain`, `session_end`.
- **CI validation** — `logschema/validate_events.py --selftest` har build par events ko schema ke
  against check karta hai; fail hone par build ruk jaata hai.
- **Export** — `.jsonl` (ek event per line) ya `.json` (poore report me `events`), aur `.xlsx` me
  alag "Events" sheet.

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
