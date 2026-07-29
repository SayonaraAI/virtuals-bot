import requests
import json
import os

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID        = os.environ.get("CHAT_ID")

API_URL = "https://api2.virtuals.io/api/virtuals/125070"
PARAMS  = {
    "populate[0]": "image",
}

r = requests.get(API_URL, params=PARAMS, timeout=10)
r.raise_for_status()
data = r.json()

text = json.dumps(data, indent=2)
print(text)

# Send it to Telegram too, split into chunks if long, so it's easy to grab
if TELEGRAM_TOKEN and CHAT_ID:
    for i in range(0, len(text), 3500):
        chunk = text[i:i+3500]
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": f"<pre>{chunk}</pre>", "parse_mode": "HTML"},
            timeout=10,
        )
