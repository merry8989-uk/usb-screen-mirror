# PhoneMirrorServer (Android) — EXPERIMENTAL

> [!WARNING]
> **Filhaal download ya use na karein.**
> Yeh app kisi asli device par **test nahi hui**. Isse build hone wala APK
> (`PhoneMirrorServer.apk`) sirf development/experiment ke liye rakha gaya hai.
> Kisi ko bhi ise install karne ke liye na kahein.

Yeh repo ka **Mode B** (standalone) hissa hai — apna engine:

1. `MediaProjection` + `VirtualDisplay` se screen capture
2. `MediaCodec` (hardware H.264) se encode
3. Raw stream TCP port 27183 par
4. PC par `PhoneMirrorReceiver.py` (ffplay) se playback

Screen mirroring ke liye repo ka **Mode A** (scrcpy wrapper: `PhoneMirror.py`) use karein —
wo proven, tested aur feature-rich hai.

## Status

- Sirf video (audio nahi)
- Ek client
- App foreground me rehni chahiye
- Kisi device par runtime test nahi hua
