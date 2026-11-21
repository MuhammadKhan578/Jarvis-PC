# Jarvis PC - free local Asterisk voice line (no Twilio)

Asterisk khud **free aur open-source** hai. Ye line Twilio jaisi kaam karti hai:
aap Jarvis ko call karke baat/command dete ho, aur Jarvis aapko `call me` par
call karta hai. Lekin **free sirf tab hai jab aap local extension/softphone use
karein**. Real SIM/PSTN number par call ke liye koi SIP trunk ya GSM gateway
chahiye — wo aam taur par paid hota hai. Koi jhootha "free number" nahi hai.

| Mode | Cost | Kya milta hai |
|---|---|---|
| **Local extension (recommended)** | **0 Rs / month** | PC par WSL me Asterisk + softphone (PC/Android). Aap 1002 dial karke Jarvis se baat karte ho; Jarvis 1001 par aapko call karta hai. |
| SIP trunk / GSM gateway | Usually paid | Real phone/SIM number se calls. Adapter same AMI/AGI chalega, bas trunk config aur chahiye. |

## 1) One-command Asterisk setup (WSL)

PC par PowerShell kholo:

```powershell
cd "C:\Users\Shahid\Desktop\Jarvis Github for PC"
powershell -ExecutionPolicy Bypass -File .\asterisk\setup_asterisk.ps1
```

Script:
- WSL Ubuntu install karta hai ( agar pehle se nahi hai; reboot ho sakta hai),
- `asterisk` apt se install karta hai,
- random SIP password aur AMI secret banata hai,
- `extensions.conf`, `pjsip.conf`, `manager.conf` likhta hai,
- Asterisk restart karta hai,
- aur aapko **exact settings print** karta hai.

Agar aapka WSL distro Ubuntu nahi hai to:

```powershell
powershell -ExecutionPolicy Bypass -File .\asterisk\setup_asterisk.ps1 -Distro "Ubuntu-22.04"
```

> WSL install ke baad reboot poocha jaye to reboot karke upar wala command dobara chalayein.
> Ubuntu + Asterisk ke liye roughly 3-4 GB free disk rakhein.
> Script WSL ke Asterisk sounds folder se aapke Windows
> `jarvis_data/asterisk/sounds/jarvis` par symlink bana deta hai, to dono taraf
> same WAV files dikhti hain — alag se copy karne ki zarurat nahi.

## 2) Softphone register karo (free)

PC par **Zoiper, MicroSIP ya Comet** install karo. Ya Android par **Zoiper /
CSipSimple** jaisa SIP app. Setup script jo print kare, wo use karo:

- **Server:** WSL IP `:5060` (Windows par softphone ho to pehle `127.0.0.1:5060` try karo)
- **Extension / Username:** `1001`
- **Password:** setup script wala SIP password
- **Transport:** UDP

Register hone ke baad:

- **1002 dial karo** → Jarvis answer karega.
- Jarvis pehle bolega: *"Ye call recording ki ja rahi hai / This call is being recorded."*
- Phir: *"Boliye, apna command dein."*
- Aap bolo: `time batao`, `insights`, `screen par dikhao`, `device link status` etc.
- Jarvis tool chalayega, asli reply bolega, aur transcript local save hoga.

Android phone par bhi yahi SIP app same Wi‑Fi se 1001 ke liye register karo.
Jarvis Mobile app me koi badlaav nahi chahiye — SIP app hi phone ka "line" hai.

## 3) Jarvis ko setup batao

Setup script jo **AMI secret** print kare, wo yahan daalo. PC Jarvis se bolo/type karo:

```text
asterisk setup 127.0.0.1 jarvis <AMI_SECRET> 1001
asterisk line start
```

Agar `127.0.0.1` se AMI na mile to setup script wala **WSL IP** use karo:

```text
asterisk setup <WSL_IP> jarvis <AMI_SECRET> 1001
```

Secret `jarvis_data/config.json` me protected (DPAPI) store hota hai, repo me nahi.

## 4) "Call me" — Jarvis aapko call kare

Ek baar clear opt-in:

```text
mujhe asterisk se call karo
```

ya

```text
asterisk call me
```

Jarvis AMI `Originate` se **1001** (aapka softphone) ring karega. Aap ne answer
kiya to wahi FastAGI prompt chalega — ab aap command de sakte ho. Sirf real
AMI `Response: Success` par hi "call started" bola jayega; warna honest error.

## 5) Available commands

| Command | Kya karta hai |
|---|---|
| `asterisk line status` | running/stopped, AMI host, AGI port, configured ya nahi |
| `asterisk line start` / `asterisk line stop` | FastAGI listener (port 4573) start/stop |
| `asterisk setup <host> <user> <secret> [extension]` | AMI settings save karta hai |
| `mujhe asterisk se call karo` / `asterisk call me` | configured softphone ko call (explicit opt-in) |
| `asterisk call <target>` | same, with a label for logs |

High-risk commands (`delete`, `payment`, `send`, `shutdown`, etc.) phone par
bhi block rehte hain — Twilio line jaisa hi safety gate.

## 6) Kya real hai aur kya nahi

- **Real:** AMI Originate, FastAGI answer/record, local WAV storage, speech-to-text,
  `command_hook` execution, spoken reply, JSONL transcript, male voice, consent line.
- **Internet needed sirf STT ke liye:** `speech_recognition` ka Google Web Speech
  path use hota hai (free, no account). TTS local SAPI5 (pyttsx3) se hota hai.
  Agar internet na ho to STT fail hoga aur Jarvis honest bolega "samajh nahi aaya".
- **Nahi:** free PSTN/SIM number, incoming-call interception on Android, call
  recording without the spoken consent, female voice, fixed latency guarantee.
- Real number chahiye to SIP trunk/GSM gateway lagana hoga; adapter same hai.

## 7) Data aur privacy

- Call audio: `jarvis_data/asterisk_recordings/`
- Prompts/replies: `jarvis_data/asterisk/sounds/jarvis/` (gitignored)
- Transcripts: `jarvis_data/asterisk_transcripts.jsonl`
- AMI secret: protected config, kabhi repo me nahi.
- Dono folders `.gitignore` me already cover hain (`jarvis_data/`).
- RECORD FILE path auto-convert hota hai `C:\...` → `/mnt/c/...` taake WSL wala
  Asterisk bhi usi file par likhe. Agar aapka repo kisi doosre drive par hai to
  `jarvis_data/config.json` me `asterisk_line.wsl_recordings_dir` manually set karo.

## 8) Troubleshooting

| Problem | Fix |
|---|---|
| `asterisk line status` says stopped | `asterisk line start` |
| AMI login fail | Secret/host galat; setup script se exact secret dobara copy karo |
| Softphone register nahi hota | WSL IP badla hota hai (reboot ke baad); setup script dobara chalao ya softphone me naya WSL IP daalo |
| Call connects par kuch nahi sunai | FastAGI band hai ya AGI host galat; `asterisk line status` aur WSL `asterisk -rx "core show channels"` dekho. Windows Firewall me Python/port 4573 ko private networks par allow karo. |
| STT fail | Internet check karo (Google Web Speech); ya thoda saaf bolkar dobara call karo |
| Port conflict | Default AGI port 4573 hai. Agar any app use kar raha ho to `extensions.conf` me port badlo aur `jarvis_data/config.json` me `asterisk_line.agi_port` bhi wahi karo, phir Jarvis restart karo. |

 Twilio line ab bhi optional hai (`docs/PHONE_LINE.md`) — lekin is free Asterisk
line ke liye **koi Twilio account ya payment nahi chahiye**.
