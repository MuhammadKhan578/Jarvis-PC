#!/usr/bin/env bash
# Free local Asterisk for Jarvis PC (WSL Ubuntu). No Twilio, no per-minute fee.
# Usage (inside WSL): bash setup_asterisk_wsl.sh /path/to/copied/conf
set -uo pipefail

SRC="${1:-/tmp/jarvis-asterisk}"
WIN_REPO="${2:-}"
ETC="/etc/asterisk"

if ! command -v asterisk >/dev/null 2>&1; then
  echo "==> Installing Asterisk (free/open-source)"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y asterisk
fi

SIP_SECRET="$(openssl rand -hex 12)"
AMI_SECRET="$(openssl rand -hex 18)"
HOST_IP="$(ip route show default 2>/dev/null | awk '/default/ {print $3; exit}')"
if [ -z "${HOST_IP}" ]; then
  HOST_IP="$(awk '/^nameserver/ {print $2; exit}' /etc/resolv.conf)"
fi
WSL_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

echo "==> Writing Jarvis Asterisk config"
install -d -m 0755 /var/lib/asterisk/sounds/jarvis
install -d -m 0755 /var/spool/asterisk/recording/jarvis
install -d -m 0755 /var/log/asterisk/jarvis

# Jarvis writes WAVs on Windows. Make Asterisk see the SAME folder via a symlink.
if [ -n "${WIN_REPO}" ] && command -v wslpath >/dev/null 2>&1; then
  JARVIS_SOUNDS="$(wslpath "${WIN_REPO}")/jarvis_data/asterisk/sounds/jarvis"
  install -d -m 0755 "${JARVIS_SOUNDS}"
  for sounds_dir in /var/lib/asterisk/sounds /usr/share/asterisk/sounds; do
    if [ -d "${sounds_dir}" ]; then
      ln -sfn "${JARVIS_SOUNDS}" "${sounds_dir}/jarvis"
    fi
  done
fi

sed "s/JARVIS_AGI_HOST/${HOST_IP}/g" "${SRC}/extensions.conf" > "${ETC}/extensions.conf"
sed "s/JARVIS_SIP_PASSWORD/${SIP_SECRET}/g" "${SRC}/pjsip.conf" > "${ETC}/pjsip.conf"
sed "s/JARVIS_AMI_SECRET/${AMI_SECRET}/g" "${SRC}/manager.conf" > "${ETC}/manager.conf"

chmod 0640 "${ETC}/extensions.conf" "${ETC}/pjsip.conf" "${ETC}/manager.conf"
if id asterisk >/dev/null 2>&1; then
  chown root:asterisk "${ETC}/extensions.conf" "${ETC}/pjsip.conf" "${ETC}/manager.conf"
  chown -R asterisk:asterisk /var/lib/asterisk/sounds/jarvis \
    /var/spool/asterisk/recording/jarvis /var/log/asterisk/jarvis
fi

# Make sure FastAGI and AMI modules are loaded in the distro default config.
if [ -f "${ETC}/modules.conf" ]; then
  grep -q '^load => res_agi.so' "${ETC}/modules.conf" || echo 'load => res_agi.so' >> "${ETC}/modules.conf"
  grep -q '^load => manager.so' "${ETC}/modules.conf" || echo 'load => manager.so' >> "${ETC}/modules.conf"
fi

echo "==> Restarting Asterisk"
service asterisk restart >/dev/null 2>&1 || true
asterisk -rx 'core restart now' >/dev/null 2>&1 || true
sleep 3

echo
echo "================ JARVIS ASTERISK READY ================"
echo "Asterisk version : $(asterisk -rx 'core show version' 2>/dev/null | head -n 1)"
echo "WSL IP (softphone server) : ${WSL_IP}"
echo "Windows host IP (AGI)     : ${HOST_IP}"
echo
echo "Softphone / SIP app settings"
echo "  Server   : ${WSL_IP}:5060  (try 127.0.0.1 first if the softphone is on Windows)"
echo "  Extension: 1001"
echo "  Password : ${SIP_SECRET}"
echo "  Dial     : 1002 to reach Jarvis"
echo
echo "Jarvis PC settings (say this out loud or type in chat)"
echo "  asterisk setup 127.0.0.1 jarvis ${AMI_SECRET} 1001"
echo "  asterisk line start"
echo
echo "AMI details"
echo "  Host  : 127.0.0.1 (or ${WSL_IP} if localhost forwarding is off)"
echo "  Port  : 5038"
echo "  User  : jarvis"
echo "  Secret: ${AMI_SECRET}"
echo "======================================================"
echo
echo "NOTE: This is a FREE local extension. To call a real SIM/PSTN number you"
echo "still need a SIP trunk or GSM gateway (usually paid). No fake free number."
