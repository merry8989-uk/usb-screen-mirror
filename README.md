# PhoneMirror — Screen Mirror for Android (Windows + Python)

Ek chhota GUI app jo aapke Android phone ki screen ko **USB cable ya Wi-Fi** ke
through Windows PC par mirror karta hai — **kam latency**, **phone par kam load**,
**clear audio**, **input control** aur **auto-reconnect** ke saath.

Yeh app khud video encode nahi karta. Yeh **scrcpy** (open-source, Genymobile) ke
engine ko wrap karta hai, aur uske sahi low-latency flags ek click me lagata hai.
Isliye aapko proven, tested quality milti hai bina engine dobara banane ke.

---

## USB vs Wi-Fi — kaunsa use karein

| | USB cable | Wi-Fi (TCP/IP) |
|---|---|---|
| Latency | **Sabse kam (30–70 ms)** | Zyada (100–250 ms), network par depend |
| Cable | Chahiye | Nahi (ek baar setup ke baad) |
| Internet | Use hi nahi karta | Same Wi-Fi par depend karta hai |
| Stability | Best | Router/network par depend |
| Kab use karein | Gaming, low-latency kaam | Cable-free convenience |

**Note:** USB mode internet use hi nahi karta — aapka net down ho ya slow,
mirroring par koi asar nahi. Low latency chahiye to USB hi best hai.

---

## Yeh low latency aur kam hang kaise deta hai?

1. **Hardware encode (MediaCodec).** Phone apni GPU ka dedicated H.264/HEVC
   encoder use karta hai, software encoder nahi. CPU load, heat aur hang kam.
2. **USB transport (ya low-latency Wi-Fi).** `adb` socket par, jitter kam.
3. **Zero video buffering.** `--video-buffer 0 --display-buffer 0`.

---

## Setup (ek baar)

**1. Python 3 install karo** (python.org se). Tkinter isi ke saath aata hai.

**2. scrcpy + adb install karo** (Windows me sabse aasan):

```
winget install Genymobile.scrcpy
```

**3. Phone par USB debugging on karo:**
`Settings → About phone → Build number` par 7 baar tap → Developer options →
**USB debugging** enable → USB se jodo → phone par "Allow" dabao.

**4. App chalao:**

```
python PhoneMirror.py
```

> Audio forwarding aur `--keyboard uhid` ke liye **scrcpy 2.0+** chahiye.
> `scrcpy --version` se check kar lo.

---

## App kaise use karein

1. **Tools** — scrcpy aur adb ka path (auto-detect).
2. **Device** — "Refresh" dabao, phone list me aa jayega.
3. **Connection** — USB ya Wi-Fi chuno (Wi-Fi ke steps neeche).
4. **Preset** — apne use ke hisaab se.
5. **Video / Audio / Auto-reconnect / Input control** — tweak karo.
6. **Start Mirroring** dabao.
7. **Copy command** — actual scrcpy command clipboard me.

---

## Wi-Fi / TCP-IP mode (bina cable)

USB ek baar zaroori hai setup ke liye:

1. Phone ko **USB se jodo** aur Refresh dabao.
2. **Connection** frame me **Wi-Fi / TCP-IP** select karo.
3. **Auto-detect IP** dabao (phone ka Wi-Fi IP khud bhar jayega) — ya manually daalo.
4. **Enable Wi-Fi** dabao — yeh `adb tcpip 5555` chalata hai (phone adbd ko TCP par le aata hai).
5. Ab **USB cable nikaal lo**.
6. **Connect** dabao — yeh `adb connect <ip>:5555` chalata hai.
7. **Device** list me ab `IP:PORT` wala entry dikhega — usse select karke **Start Mirroring**.

- Wi-Fi par latency zyada hoti hai — **bitrate kam** (4M) aur **max-fps 30–45**
  rakhna smooth rehta hai.
- Disconnect ke liye **Disconnect** button (`adb disconnect`).
- Auto-reconnect Wi-Fi mode me bhi kaam karta hai.

---

## Input control (PC se phone chalao)

scrcpy me input control **by default on** hota hai — matlab:

- **Mouse = touch** (click, drag, scroll phone par jaata hai)
- **Keyboard = typing** (PC se type karo, phone me jaata hai)
- Common shortcuts: `Ctrl`+`h` = home, `Ctrl`+`b` = back, `Ctrl`+`s` = app switch,
  `Ctrl`+`p` = power, `Alt`+`f` = fullscreen

App me **8. Input control** frame se:

- **No control (sirf dekho)** — input band, sirf video+audio (kiosk/monitoring ke liye).
- **Keyboard mode:**
  - `default` — scrcpy ka apna default (safe)
  - `uhid` — **Android 11+ me best**, keyboard phone ko real hardware jaisa lagta hai
  - `sdk` — purane Android ke liye
  - `disabled` — keyboard band (video+audio chalu rahega)

---

## Presets

| Preset | Size | Bitrate | FPS | Audio | Kab use karein |
|---|---|---|---|---|---|
| **Low Latency** | 1024 | 8M | 60 | 128K | USB par gaming / interactive |
| **Low Phone Load** | 800 | 4M | 30 | 96K | Phone garam ho raha ho / purana phone |
| **Balanced** | 1280 | 8M | 60 | 128K | Rozana kaam |
| **High Quality** | 1920 | 16M | 60 | 256K | Sharp picture + best audio (h265) |

**Tuning:**
- **Latency kam** → bitrate kam, `max-fps 60`, resolution kam.
- **Phone load kam** → `max-size` + `max-fps` dono kam (encode load ≈ res × fps).
- **Wi-Fi** → bitrate 4M aur fps 30–45 rakho.
- **Audio clear** → Opus, 128K+, buffer 50–100 ms.

---

## Auto-reconnect kaise kaam karta hai

scrcpy process bina aapke khehne band ho jaaye (cable hila, phone disconnect,
USB debugging toggle) to app:

1. Wait karta hai (**Retry delay**, default 3 s),
2. `adb` se check karta hai ki device wapas juda hai ya nahi,
3. Judte hi **khud scrcpy dobara launch** kar deta hai.

- **Max attempts:** 0 = unlimited, ya ek limit set karo.
- Session 15+ second chala ho to counter reset hota hai (achhi session ke baad
  galti se ek disconnect aaye to ginti zero se).
- **Stop** dabane par reconnect band.

---

## Samajhne ke liye: scrcpy flags jo app use karta hai

```
scrcpy --serial <SERIAL> \
       --max-size 1024 --video-bit-rate 8M --max-fps 60 --video-codec h264 \
       --video-buffer 0 --display-buffer 0 --render-driver opengl \
       --audio-codec opus --audio-bit-rate 128K --audio-buffer 50 \
       --keyboard uhid \
       --stay-awake
```

- `--max-size` — encode se pehle resolution ghatata hai → encode + bandwidth bachta hai.
- `--video-bit-rate` — 8M USB ke liye smooth; kam karne se latency girti hai.
- `--max-fps` — 30 karne se phone par encode load lagbhag aadha.
- `--video-buffer 0 --display-buffer 0` — koi buffering nahi = minimum latency.
- `--audio-codec opus --audio-bit-rate 128K` — clear, efficient audio.
- `--keyboard uhid` — PC keyboard ko real hardware jaisa bhejo (Android 11+).
- `--no-control` — input band (jab aapne "No control" chuna ho).

Wi-Fi me `--serial` ki jagah `IP:5555` aa jaata hai.

---

## Latency aur load khud naapo

- FPS: Settings me **Print FPS** on karo — log me real-time fps.
- End-to-end latency: phone par stopwatch app kholo, PC window se compare karo.
- Phone load/heat: `max-size`/`max-fps` kam karne se turant farak.

---

## Isko ek .exe bana lena (optional)

```
pip install pyinstaller
pyinstaller --onefile --noconsole --name PhoneMirror PhoneMirror.py
```

Ya GitHub Actions workflow (`.github/workflows/build.yml`) har push par
`PhoneMirror.exe` khud build kar deta hai.

---

## Common problems

- **"unauthorized" device** — phone par "Allow" accept karo, ya `adb kill-server` phir `adb devices`.
- **Wi-Fi connect nahi ho raha** — phone aur PC same Wi-Fi par? `adb tcpip 5555` chalaya tha?
  Firewall port 5555 block to nahi kar raha? `adb connect <ip>:5555` ka output log me dekho.
- **Wi-Fi par lag** — bitrate 4M, fps 30 karo; 5 GHz Wi-Fi behtar.
- **Audio nahi** — scrcpy 2.0+ chahiye; "Audio on" checkbox on.
- **Keyboard kaam nahi kar raha** — Android 11+ par `uhid`, purane par `sdk` try karo.
- **Baar-baar disconnect** — Auto-reconnect on rakho.
- **Phone garam** — **Low Phone Load** preset.

---

## Aage kya (agar khud ka engine banana ho)

Apna engine zero se: Android par `MediaProjection` + `VirtualDisplay` → `MediaCodec`
(hardware H.264) → USB/Wi-Fi socket (adb reverse / TCP) → PC par FFmpeg decode +
render. Audio ke liye `AudioPlaybackCapture` + Opus. Input ke liye `InputManager`
(uhid jaisa) — wahi concepts, bas sab khud likhna padta hai.
