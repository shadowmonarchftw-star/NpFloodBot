"""Interactive Telegram Bot Command Handler.

Enables the bot to process interactive slash commands from users in groups or private chats:
/status, /balkhu, /roshi, /nakkhu, /koshi, /narayani, /emergency, /help.
"""

from __future__ import annotations

import html
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from services.hydrology import fetch_river_telemetry
from services.risk_evaluator import evaluate_risk
from services.telegram_notifier import format_npt_time
from services.weather import fetch_catchment_weather

logger = logging.getLogger(__name__)

HELP_MESSAGE = """
<b>🌊 NEPAL RIVER BASIN FLOOD EARLY WARNING BOT</b>
नेपाल नदी प्रणाली बाढी पूर्वसूचना बट

<b>Available Commands / उपलब्ध कमाण्डहरू:</b>
• <code>/status</code> - Real-time gauge table for all 14 monitored river stations.
• <code>/balkhu</code> - Bagmati at Balkhu (Kathmandu) live status & vulnerable bastis.
• <code>/roshi</code> - Roshi Khola at Panauti / Bhakunde Besi (BP Highway) status.
• <code>/nakkhu</code> - Nakkhu Khola (Southern Lalitpur) live reading.
• <code>/koshi</code> - Saptakoshi at Chatara (Eastern Nepal) live status.
• <code>/narayani</code> - Narayani River at Devghat live status.
• <code>/emergency</code> - Emergency helpline numbers (Nepal Police, APF, DHM).
• <code>/help</code> - Show this menu.

<i>Dedicated to the flood-resilient communities of Nepal.</i>
"""

EMERGENCY_CONTACTS = """
<b>🚨 NEPAL EMERGENCY HELPLINES | आपतकालीन सम्पर्क नम्बरहरू</b>
━━━━━━━━━━━━━━━━━━━━━━
👮 <b>नेपाल प्रहरी (Nepal Police):</b> <code>100</code>
🛡️ <b>सशस्त्र प्रहरी बल (Armed Police Force):</b> <code>1114</code>
🌊 <b>बाढी पूर्वसूचना हटलाइन (DHM Flood Toll-Free):</b> <code>1155</code>
🚑 <b>एम्बुलेन्स सेवा (Ambulance):</b> <code>102</code>
🚒 <b>दमकल / अग्नि नियन्त्रक (Fire Brigade):</b> <code>101</code>
🚦 <b>ट्राफिक प्रहरी (Traffic Police):</b> <code>103</code>

⚠️ <i>बाढीको जोखिम देखिएमा वा जलसतह सतर्कता तह पार गरेमा तुरुन्त माथिका नम्बरहरूमा सम्पर्क गर्नुहोस्।</i>
"""


def process_telegram_updates(bot_token: Optional[str] = None) -> int:
    """Poll for unhandled user messages and reply to slash commands."""
    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not configured for command processing.")
        return 0

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        resp = requests.get(url, params={"timeout": 3, "limit": 20}, timeout=5.0)
        if resp.status_code != 200:
            return 0
        data = resp.json()
        updates = data.get("result", [])
    except Exception as e:
        logger.debug(f"Failed to fetch Telegram updates: {e}")
        return 0

    if not updates:
        return 0

    processed_count = 0
    max_update_id = 0

    for upd in updates:
        upd_id = upd.get("update_id", 0)
        max_update_id = max(max_update_id, upd_id)

        msg = upd.get("message") or upd.get("channel_post")
        if not msg:
            continue

        text = (msg.get("text") or "").strip()
        chat = msg.get("chat", {})
        chat_id = chat.get("id")

        if not text or not chat_id:
            continue

        cmd = text.split()[0].lower().split("@")[0]  # Strip bot handle if present

        reply_text = None
        if cmd in ("/start", "/help"):
            reply_text = HELP_MESSAGE
        elif cmd == "/emergency":
            reply_text = EMERGENCY_CONTACTS
        elif cmd in ("/balkhu", "/roshi", "/nakkhu", "/koshi", "/narayani"):
            station_map = {
                "/balkhu": "bagmati_balkhu",
                "/roshi": "roshi_panauti",
                "/nakkhu": "nakkhu_lele",
                "/koshi": "koshi_chatara",
                "/narayani": "narayani_devghat",
            }
            target_id = station_map[cmd]
            try:
                readings = fetch_river_telemetry(station_id=target_id)
                if readings:
                    r = readings[0]
                    w = fetch_catchment_weather(r.upstream_catchment, r.upstream_lat, r.upstream_lon)
                    risk = evaluate_risk(r, w)
                    now_str = format_npt_time()
                    reply_text = (
                        f"<b>🌊 {risk.station_name}</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📏 <b>वर्तमान जलसतह:</b> <code>{r.current_level:.2f} m</code>\n"
                        f"⚠️ <b>सतर्कता तह:</b> <code>{r.warning_level:.2f} m</code> | 🔴 <b>खतरा तह:</b> <code>{r.danger_level:.2f} m</code>\n"
                        f"📈 <b>प्रवृत्ति (Trend):</b> <code>{'+' if r.rising_velocity>0 else ''}{r.rising_velocity:.2f} m/hr</code>\n"
                        f"🌧️ <b>माथिल्लो तटीय वर्षा:</b> <code>{w.forecast_1h_mm:.1f} mm/hr</code> ({w.catchment_name})\n"
                        f"🚨 <b>स्थिति:</b> {risk.severity.emoji} <b>{risk.severity.badge_ne}</b>\n\n"
                        f"🏘️ <b>तटीय जोखिम क्षेत्रहरू:</b>\n{r.vulnerable_areas_ne}\n\n"
                        f"🕒 <i>अपडेट: {now_str}</i>"
                    )
            except Exception as e:
                reply_text = f"⚠️ Could not fetch data for {cmd}: {e}"
        elif cmd == "/status":
            try:
                readings = fetch_river_telemetry()
                lines = ["<b>🌊 नेपाल प्रमुख नदी जलसतह प्रत्यक्ष विवरण (Real-Time Gauges):</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
                for r in readings[:10]:
                    status_emoji = "🟢" if r.current_level < r.warning_level else ("🟠" if r.current_level < r.danger_level else "🔴")
                    lines.append(f"• <b>{r.station_name.split('(')[0].strip()}:</b> <code>{r.current_level:.2f}m</code> (W:{r.warning_level:.1f}m | D:{r.danger_level:.1f}m) {status_emoji}")
                now_str = format_npt_time()
                lines.append("━━━━━━━━━━━━━━━━━━━━━━")
                lines.append(f"🕒 <i>{now_str} | DHM & Open-Meteo</i>")
                reply_text = "\n".join(lines)
            except Exception as e:
                reply_text = f"⚠️ Could not retrieve live status: {e}"

        if reply_text:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": reply_text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                    timeout=6.0,
                )
                processed_count += 1
            except Exception as e:
                logger.error(f"Failed to reply to {cmd}: {e}")

    # Confirm receipt of updates by updating offset
    if max_update_id > 0:
        try:
            requests.get(url, params={"offset": max_update_id + 1}, timeout=3.0)
        except Exception:
            pass

    return processed_count
