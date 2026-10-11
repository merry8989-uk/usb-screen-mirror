# PhoneMirror — USB Screen Mirror (Windows + Python)

Ek chhota GUI app jo aapke Android phone ki screen ko **USB cable** ke through
Windows PC par mirror karta hai — **kam latency**, **phone par kam load**,
**clear audio**, aur **auto-reconnect** ke saath.

Yeh app khud video encode nahi karta. Yeh **scrcpy** (open-source, Genymobile) ke
engine ko wrap karta hai, aur uske sahi low-latency flags ek click me lagata hai.
Isliye aapko proven, tested quality milti hai bina engine dobara banane ke.

---

## Ek zaroori baat: USB vs internet

USB mirroring **internet use hi nahi karti**. Video/audio data `adb` ke USB socket
par jaata hai (aapke cable ke andar). Matlab:

- Aapka internet down ho, slow ho, ya router restart ho — mirroring par **koi asar nahi**.
- Mirroring aapke internet ko bhi affect nahi karti.
- Isliye "connection stable" USB mode me khud-ba-khud guaranteed hai — WiFi
  mirroring jaisa packet loss / jitter / latency spike nahi hota.

(Agar aapko WiFi/TCP-IP mirroring chahiye — bina cable — to wo alag mode hai,
batayein to add kar dun. Lekin low latency ke liye USB hi best hai.)

---

## Yeh low latency aur kam hang kaise deta hai?

1. **Hardware encode (MediaCodec).** Phone apni GPU ka dedicated H.264/HEVC
   encoder use karta hai, software encoder nahi. Isse CPU par load kam padta hai,
   heat kam hota hai, aur phone kam hang karta hai.
2. **USB transport, WiFi nahi.** `adb` local socket par, koi packet loss/jitter
   nahi — latency typically **30–70 ms**.
3. **Zero video buffering.** `--video-buffer 0 --display-buffer 0` — frames turant render.

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

> Audio forwarding ke liye **scrcpy 2.0+** chahiye. `scrcpy --version` se check kar lo.

---

## App kaise use karein

1. **Tools** — scrcpy aur adb ka path (auto-detect ho jaata hai).
2. **Device** — "Refresh" dabao, phone list me aa jayega.
3. **Preset** — apne use ke hisaab se chuno (neeche dekho).
4. **Video / Audio / Auto-reconnect** — zaroorat pade to tweak karo.
5. **Start Mirroring** dabao.
6. **Copy command** — actual scrcpy command clipboard me copy ho jaati hai.

---

## Presets

| Preset | Size | Bitrate | FPS | Audio | Kab use karein |
|---|---|---|---|---|---|
| **Low Latency** | 1024 | 8M | 60 | 128K | Gaming / interactive — sabse tez feel |
| **Low Phone Load** | 800 | 4M | 30 | 96K | Phone garam ho raha ho / purana phone |
| **Balanced** | 1280 | 8M | 60 | 128K | Rozana kaam |
| **High Quality** | 1920 | 16M | 60 | 256K | Sharp picture + best audio (h265) |

**Tuning ka rule:**
- **Latency kam** → bitrate kam, `max-fps 60`, resolution kam.
- **Phone par load kam** → `max-size` aur `max-fps` dono kam karo
  (encode load ≈ resolution × fps). Audio ka load na ke barabar hota hai.
- **Audio clear** → Opus codec, 128K+ bitrate, aur buffer 50–100 ms
  (buffer badhane se crackle kam hota hai, latency thodi badhti hai).

---

## Audio clear kaise rakhein

- **Codec:** `opus` (best quality-per-bit, default). `aac` compatibility ke liye,
  `flac` lossless par zyada bandwidth.
- **Bitrate:** 128K theek hai; 192K/256K studio-jaisa clear.
- **Buffer (ms):** `0` = lowest latency par crackle ho sakta hai; `50` default;
  `100` = smoothest, clear (chhoti si latency trade-off). Clear audio chahiye to
  **50–100** rakho.

---

## Auto-reconnect kaise kaam karta hai

Jab scrcpy process bina aapke khehne band ho jaaye (cable hila, phone disconnect,
USB debugging toggle), app:

1. Process band hone par wait karta hai (**Retry delay**, default 3 s),
2. `adb` se check karta hai ki aapka device wapas juda hai ya nahi,
3. Judte hi **khud scrcpy dobara launch** kar deta hai — aapko kuch nahi karna padta.

- **Max attempts:** 0 = unlimited (jab tak aap Stop na dabao), ya ek limit set karo.
- Agar session 15+ second chala ho, counter reset ho jaata hai — matlab ek achhi
  session ke baad galti se ek disconnect aaye to attempts dobara zero se ginte hain.
- **Stop** dabane par reconnect band ho jaata hai.
- Bonus: agar aapne cable nikaal liya ho, app har delay ke baad phone ka intezaar
  karta rehta hai — wapas lagane par khud jud jaata hai.

---

## Samajhne ke liye: scrcpy flags jo app use karta hai

```
scrcpy --serial <SERIAL> \
       --max-size 1024 --video-bit-rate 8M --max-fps 60 --video-codec h264 \
       --video-buffer 0 --display-buffer 0 --render-driver opengl \
       --audio-codec opus --audio-bit-rate 128K --audio-buffer 50 \
       --stay-awake
```

- `--max-size` — encode se pehle resolution ghatata hai → encode + USB bandwidth bachta hai.
- `--video-bit-rate` — 8M USB ke liye smooth; kam karne se latency girti hai.
- `--max-fps` — 30 karne se phone par encode load lagbhag aadha.
- `--video-codec h264` — har phone me hardware-accelerated + sabse compatible.
- `--video-buffer 0 --display-buffer 0` — koi buffering nahi = minimum latency.
- `--render-driver opengl` — low-latency rendering.
- `--audio-codec opus --audio-bit-rate 128K` — clear, efficient audio.
- `--audio-buffer 50` — crackle se bachne ke liye chhota buffer.
- `--stay-awake` — mirror karte waqt phone so nahi.
- `--turn-screen-off` (optional) — phone screen band, mirroring chalu (battery bachti hai).

---

## Latency aur load khud naapo

- FPS: Settings me **Print FPS** on karo — log me real-time fps.
- End-to-end latency: phone par stopwatch app kholo, PC window se compare karo.
- Phone load/heat: mirroring ke dauraan phone ka temperature/CPU monitor dekho —
  `max-size`/`max-fps` kam karne se turant farak dikhega.

---

## Isko ek .exe bana lena (optional)

```
pip install pyinstaller
pyinstaller --onefile --noconsole --name PhoneMirror PhoneMirror.py
```

`dist/PhoneMirror.exe` ban jayegi. scrcpy/adb alag se install rehne chahiye.

---

## Common problems

- **"unauthorized" device** — phone par "Allow" popup accept karo, ya
  `adb kill-server` phir `adb devices`.
- **Audio nahi aa raha** — scrcpy 2.0+ chahiye; "Audio on" checkbox on rakho.
- **Audio me crackle** — Audio buffer 100–150 ms kar do, ya bitrate badhao.
- **Lag zyada** — bitrate/max-size kam karo, `--no-audio` off rakho ya USB 3.0 port (blue) use karo.
- **Baar-baar disconnect** — Auto-reconnect on rakho; delay 3–5 s theek hai.
- **Phone garam** — **Low Phone Load** preset.

---

## Aage kya (agar khud ka engine banana ho)

scrcpy ko wrap karna seekhne aur personal use ke liye best hai. Apna engine zero
se banana ho to wahi architecture: Android par `MediaProjection` + `VirtualDisplay`
→ `MediaCodec` (hardware H.264) → USB socket (adb reverse) → PC par FFmpeg decode +
render. Audio ke liye `AudioPlaybackCapture` + Opus. Wahi teen concepts, bas sab
khud likhna padta hai.
