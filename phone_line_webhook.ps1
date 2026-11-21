param([Parameter(Mandatory = $true)][string]$TunnelUrl)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$url = $TunnelUrl.Trim().TrimEnd("/")
if ($url -notmatch "^https://") { throw "Tunnel URL must start with https://" }

$py = @'
import base64, json, sys, urllib.parse, urllib.request
from jarvis_core import phone_line

cfg = phone_line._load_cfg()
sid = str(cfg.get("account_sid") or "")
token = str(cfg.get("auth_token") or "")
number = str(cfg.get("from_number") or "")
if not (sid and token and number):
    raise SystemExit("Twilio configured nahi hai. Pehle phone_line_setup.ps1 chalayein.")

base = "https://api.twilio.com/2010-04-01/Accounts/" + sid
auth = "Basic " + base64.b64encode((sid + ":" + token).encode("utf-8")).decode("ascii")

def request(url, fields=None, method="GET"):
    headers = {"Authorization": auth, "Accept": "application/json",
               "User-Agent": "Jarvis-PC-PhoneLine/1.0"}
    body = None
    if fields is not None:
        body = urllib.parse.urlencode(fields).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)

target = sys.argv[1].rstrip("/") + "/voice/inbound"
query = urllib.parse.urlencode({"PhoneNumber": number})
listing = request(base + "/IncomingPhoneNumbers.json?" + query)
numbers = listing.get("incoming_phone_numbers", [])
if not numbers:
    raise SystemExit("Twilio account me ye number nahi mila: " + number)
number_sid = numbers[0]["sid"]
result = request(
    base + "/IncomingPhoneNumbers/" + number_sid + ".json",
    {"VoiceUrl": target, "VoiceMethod": "POST"},
    method="POST",
)
print("Twilio webhook set:", result.get("phone_number"), "->",
      result.get("voice_url"), result.get("voice_method"))
'@

python -c $py $url
if ($LASTEXITCODE -ne 0) { throw "Twilio webhook update failed." }

Write-Host "`nAb test karein:"
Write-Host "- Kisi bhi mobile se Twilio number par call karein; Jarvis bolega."
Write-Host "- 'phone line status' ya 'what time is it' jaise commands dein."
Write-Host "- 'call me' bolein; Jarvis confirmation mange ga, 'confirm' kahein."
