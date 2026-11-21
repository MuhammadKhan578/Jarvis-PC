# Jarvis PC v2.4.4 release notes

Adds a **free local Asterisk voice line** — Twilio jaisa call-and-command flow,
lekin bina Twilio account, bina per-minute charge.

## New in v2.4.4

- **One-command setup:** `asterisk\setup_asterisk.ps1` WSL Ubuntu me free Asterisk
  install karta hai, random SIP password aur AMI secret banata hai, config files
  likhta hai, Asterisk restart karta hai, aur exact settings print karta hai.
  Windows `jarvis_data/asterisk/sounds/jarvis` ka WSL symlink bhi ban jata hai.
- **Free softphone extension:** SIP extension `1001` aapke softphone (PC/Android)
  ke liye, `1002` Jarvis ke liye. `1002` dial karo ya bolo
  `mujhe asterisk se call karo` — AMI `Originate` se `1001` ring hota hai.
  Success sirf tab bola jata hai jab AMI `Response: Success` de.
- **FastAGI voice loop:** ANSWER → consent ("Ye call recording ki ja rahi hai")
  → "Boliye, apna command dein" → RECORD → Google Web Speech STT → same guarded
  `command_hook` → male-voice reply → HANGUP. STT fail hone par koi command nahi
  chalega; honest "Samajh nahi aaya, dobara boliye" aayega.
- **Safety aur privacy:** AMI secret DPAPI-protected config me, kabhi repo me
  nahi. Outbound call ke liye explicit opt-in (`confirmed=True`). Recording se
  pehle consent. Har call ka JSONL transcript local `jarvis_data/` me. Female
  voice nahi, Secret/Sex mode nahi, fixed latency claim nahi.
- **WSL bridge:** `RECORD FILE` path automatically `C:\...` → `/mnt/c/...` ho
  jata hai; Python recording ko Windows path se padhta hai. Custom drive ke liye
  `asterisk_line.wsl_recordings_dir` config option.

## Commands

`asterisk line status`, `asterisk line start`, `asterisk line stop`,
`asterisk setup <host> <user> <secret> [extension]`,
`mujhe asterisk se call karo` / `asterisk call me`, `asterisk call <target>`.

## Honest limits

- Ye **local extension** hai. Real SIM/PSTN number ke liye SIP trunk ya GSM
  gateway chahiye — wo aam taur par paid hota hai. Koi free phone number nahi.
- STT ke liye internet chahiye (free Google Web Speech endpoint). TTS local
  SAPI5 (pyttsx3) se hai.
- Is PC par WSL distro install nahi tha, isliye **live Asterisk call nahi chalai
  gayi**. Adapter ke 12 offline tests, compile aur setup-script syntax verify
  kiye gaye. Pele call par koi dikkat aaye to exact error bhejein.
- Device Link (v2.4.3) aur Twilio line (v2.4.2) bilkul waise hi hain; ye naya
  line unko replace nahi karta.

## Verification

- `python -m compileall -q -f .` — exit 0.
- `python -m unittest discover -s tests -q` — **81 tests passed**
  (69 pehle + 12 naye Asterisk tests).
- `python -m unittest tests.test_asterisk_line -v` — **12 tests OK**.
- `python -m pip check` — clean.
- `asterisk/setup_asterisk.ps1` — PowerShell parser syntax OK.
- Setup: `docs/ASTERISK_LINE.md`.
