import requests
import time
import os
import re
import json
from datetime import datetime, timezone

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID        = os.environ.get("CHAT_ID")
VOLUME_SEUIL   = 5000
CHECK_INTERVAL = 60
MAX_AGE_HOURS  = 24
WATCHLIST_FILE = "watchlist.json"

API_URL = "https://api2.virtuals.io/api/virtuals"
PARAMS  = {
    "filters[status]": "5",
    "sort": "createdAt:desc",
    "populate[0]": "image",
    "pagination[page]": 1,
    "pagination[pageSize]": 50,
}

alerted = set()
last_update_id = 0

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r") as f:
                return set(json.load(f))
        except Exception as e:
            print(f"[ERREUR watchlist] {e}")
    return set()

def save_watchlist(handles):
    try:
        with open(WATCHLIST_FILE, "w") as f:
            json.dump(sorted(handles), f)
    except Exception as e:
        print(f"[ERREUR watchlist] {e}")

watchlist = load_watchlist()

def extract_handle(text):
    """Extrait un pseudo X à partir d'un lien ou d'un @pseudo, ex: https://x.com/OxTrenchor -> OxTrenchor"""
    text = text.strip()
    match = re.search(r"(?:x\.com|twitter\.com)/([A-Za-z0-9_]+)", text)
    if match:
        return match.group(1).lower()
    match = re.match(r"@?([A-Za-z0-9_]+)$", text)
    if match:
        return match.group(1).lower()
    return None

def get_tokens():
    try:
        r = requests.get(API_URL, params=PARAMS, timeout=10)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        print(f"[ERREUR API] {e}")
        return []

def send_telegram(token):
    name     = token.get("name", "?")
    symbol   = token.get("symbol", "?")
    volume   = token.get("volume24h", 0)
    token_id = token.get("id", "")
    image    = (token.get("image") or {}).get("url", "")
    change   = token.get("priceChangePercent24h", 0)
    mcap     = token.get("mcapInVirtual", 0)
    created  = token.get("createdAt", "")[:10]
    arrow    = "🟢" if change >= 0 else "🔴"
    link     = f"https://app.virtuals.io/virtuals/{token_id}"

    # Le lien X et le site web peuvent se trouver soit sur le token lui-même,
    # soit sur le créateur, selon ce qui a été rempli au moment du lancement.
    token_links   = ((token.get("socials") or {}).get("VERIFIED_LINKS") or {})
    creator_links = (((token.get("creator") or {}).get("socials") or {}).get("VERIFIED_LINKS") or {})

    twitter_link = token_links.get("TWITTER") or creator_links.get("TWITTER")
    website_link = token_links.get("WEBSITE") or creator_links.get("WEBSITE")

    x_line = f"🐦 X : <a href='{twitter_link}'>{twitter_link}</a>\n" if twitter_link else "🐦 X : Non renseigné\n"
    web_line = f"🌐 Site : <a href='{website_link}'>{website_link}</a>\n" if website_link else "🌐 Site : Non renseigné\n"

    text = (
        f"🚨 <b>Nouveau token — seuil 5k$ atteint !</b>\n\n"
        f"🪙 <b>{name}</b>  <code>${symbol}</code>\n"
        f"📊 Volume 24h : <b>${volume:,.0f}</b>\n"
        f"{arrow} Prix 24h : <b>{change:+.2f}%</b>\n"
        f"💎 Market Cap : <b>{mcap:,.0f} VIRTUAL</b>\n"
        f"📅 Créé le : {created}\n"
        f"{x_line}"
        f"{web_line}"
        f"🔗 <a href='{link}'>Voir sur Virtuals</a>"
    )
    if image:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto", json={
            "chat_id": CHAT_ID, "photo": image, "caption": text, "parse_mode": "HTML"
        }, timeout=10)
    else:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
            "chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"
        }, timeout=10)
    print(f"[ALERTE] {name} (${symbol}) — Volume: ${volume:,.0f}")

def is_recent(token):
    created_str = token.get("createdAt", "")
    if not created_str:
        return False
    try:
        created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - created
        return age.total_seconds() < MAX_AGE_HOURS * 3600
    except:
        return False

def get_token_handle(token):
    """Retourne le pseudo X (en minuscule) lié à un token, si disponible."""
    token_links   = ((token.get("socials") or {}).get("VERIFIED_LINKS") or {})
    creator_links = (((token.get("creator") or {}).get("socials") or {}).get("VERIFIED_LINKS") or {})
    twitter_link = token_links.get("TWITTER") or creator_links.get("TWITTER")
    if not twitter_link:
        return None
    return extract_handle(twitter_link)

def reply(text):
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
        "chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"
    }, timeout=10)

def check_telegram_updates():
    global last_update_id, watchlist
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"offset": last_update_id + 1, "timeout": 0},
            timeout=10,
        )
        r.raise_for_status()
        updates = r.json().get("result", [])
    except Exception as e:
        print(f"[ERREUR getUpdates] {e}")
        return

    for update in updates:
        last_update_id = update["update_id"]
        message = update.get("message", {})
        text = (message.get("text") or "").strip()
        if not text:
            continue

        if text.startswith("/liste"):
            if watchlist:
                reply("👀 Comptes surveillés :\n" + "\n".join(f"@{h}" for h in sorted(watchlist)))
            else:
                reply("Aucun compte surveillé pour l'instant. Envoie-moi un lien X pour en ajouter un.")
            continue

        if text.startswith("/retirer"):
            parts = text.split(maxsplit=1)
            if len(parts) < 2:
                reply("Utilisation : /retirer <pseudo ou lien X>")
                continue
            handle = extract_handle(parts[1])
            if handle and handle in watchlist:
                watchlist.discard(handle)
                save_watchlist(watchlist)
                reply(f"✅ @{handle} retiré de la liste de surveillance.")
            else:
                reply("Ce compte n'était pas dans la liste.")
            continue

        handle = extract_handle(text)
        if handle:
            watchlist.add(handle)
            save_watchlist(watchlist)
            reply(f"✅ @{handle} ajouté à la liste de surveillance. Tu seras alerté dès qu'il lance un token.")

def send_watch_alert(token, handle):
    name     = token.get("name", "?")
    symbol   = token.get("symbol", "?")
    token_id = token.get("id", "")
    link     = f"https://app.virtuals.io/virtuals/{token_id}"
    text = (
        f"👀🚨 <b>Compte surveillé a lancé un token !</b>\n\n"
        f"🐦 Compte : @{handle}\n"
        f"🪙 <b>{name}</b>  <code>${symbol}</code>\n"
        f"🔗 <a href='{link}'>Voir sur Virtuals</a>"
    )
    reply(text)
    print(f"[ALERTE WATCHLIST] @{handle} — {name} (${symbol})")

def init_telegram_offset():
    """Ignore les messages déjà envoyés avant le démarrage du bot."""
    global last_update_id
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates", timeout=10)
        r.raise_for_status()
        updates = r.json().get("result", [])
        if updates:
            last_update_id = updates[-1]["update_id"]
    except Exception as e:
        print(f"[ERREUR init getUpdates] {e}")

def monitor():
    print(f"🚀 Bot démarré — seuil: ${VOLUME_SEUIL:,} | intervalle: {CHECK_INTERVAL}s")
    init_telegram_offset()
    while True:
        check_telegram_updates()

        tokens = get_tokens()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {len(tokens)} tokens récupérés")
        for token in tokens:
            tid    = token.get("id")
            volume = token.get("volume24h", 0) or 0

            handle = get_token_handle(token)
            if handle and handle in watchlist and tid not in alerted:
                send_watch_alert(token, handle)
                alerted.add(tid)
                continue

            if tid in alerted:
                continue
            if not is_recent(token):
                continue
            if volume >= VOLUME_SEUIL:
                send_telegram(token)
                alerted.add(tid)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    monitor()
