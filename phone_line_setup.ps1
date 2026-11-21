param([int]$Port = 8765)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "== Jarvis PC -> Twilio setup =="
Write-Host "Credentials sirf yahin paste karein; ye isi PC par protected store honge.`n"

$sid = (Read-Host "Twilio Account SID").Trim()
$tokenSecure = Read-Host "Twilio Auth Token" -AsSecureString
$fromNumber = (Read-Host "Twilio voice number (E.164, e.g. +15551234567)").Trim()
$toNumber = (Read-Host "Aapka mobile number for Jarvis callback (E.164)").Trim()

if (-not $sid -or -not $fromNumber -or -not $toNumber) {
    throw "Account SID, Twilio number aur callback number sab chahiye."
}

$token = [System.Net.NetworkCredential]::new("", $tokenSecure).Password
$payload = [ordered]@{
    account_sid = $sid
    auth_token = $token
    from_number = $fromNumber
    to_number = $toNumber
    port = $Port
} | ConvertTo-Json -Compress

$py = @'
import json, sys, urllib.request
from jarvis_core import phone_line

cfg = json.load(sys.stdin)
print(phone_line.phone_line_operation(
    action="configure",
    account_sid=cfg["account_sid"],
    auth_token=cfg["auth_token"],
    from_number=cfg["from_number"],
    to_number=cfg["to_number"],
    enabled=True,
))
print(phone_line.phone_line_operation(action="start", port=int(cfg["port"])))
try:
    with urllib.request.urlopen("http://127.0.0.1:%d/voice/health" % int(cfg["port"]), timeout=5) as r:
        print("Local health OK:", r.read().decode("utf-8", "replace")[:160])
except Exception as exc:
    print("Local health check failed:", exc)
print(phone_line.phone_line_operation("status"))
'@

$payload | python -c $py
if ($LASTEXITCODE -ne 0) { throw "Local configuration failed." }

Write-Host "`n== Ab aage kya karein =="
Write-Host "1) Twilio console me apna mobile verify karein ( agar pehle nahi kiya )."
Write-Host "2) Free HTTPS tunnel chalayein (Windows SSH pehle se hai, koi download nahi):"
Write-Host "   ssh -o StrictHostKeyChecking=accept-new -R 80:localhost:$Port ssh.localhost.run"
Write-Host "   (ya: cloudflared tunnel --url http://localhost:$Port)"
Write-Host "3) Jo https://... URL aaye, usse yahan daalein:"
Write-Host "   powershell -ExecutionPolicy Bypass -File .\phone_line_webhook.ps1 -TunnelUrl https://xxxx.lhr.life"
Write-Host "4) Ab kisi bhi mobile se Twilio number dial karein. Command dene ke liye baat karein."
Write-Host "5) Jarvis ko call karne ke liye bolein: call me  -> phir 'confirm'."
Write-Host "   Trial me outgoing sirf verified number par jata hai, yani sirf aapke mobile par."
