import requests
from datetime import datetime

def get_esi_name(category, item_id):
    if not item_id or item_id == 0 or item_id == 'Unknown':
        return "Unknown"
    
    if category == "characters":
        url = f"https://esi.evetech.net/latest/characters/{item_id}/?datasource=tranquility"
    else:
        url = f"https://esi.evetech.net/latest/universe/{category}/{item_id}/?datasource=tranquility"
    
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            return r.json().get('name', f"ID: {item_id}")
        elif r.status_code == 404 and category == "characters":
            return "NPC / Concord"
    except:
        pass
    return f"ID: {item_id}"

def send_kill_notification(webhook_url, full_data, event_type):
    k_id = full_data.get('killmail_id')
    zkb = full_data.get('zkb', {})
    value = zkb.get('totalValue', 0)
    
    # Обработка времени
    # API присылает время в формате: "2026-01-22T14:15:00Z"
    kill_time_str = full_data.get('killmail_time')
    discord_time = ""
    if kill_time_str:
        try:
            # Убираем 'Z' и парсим
            clean_time = kill_time_str.replace('Z', '')
            dt = datetime.fromisoformat(clean_time)
            timestamp = int(dt.timestamp())
            # Формат <t:timestamp:R> показывает "5 минут назад"
            # Формат <t:timestamp:F> показывает полную дату и время
            discord_time = f"<t:{timestamp}:F> (<t:{timestamp}:R>)"
        except:
            discord_time = kill_time_str

    # Форматирование цены
    if value >= 1_000_000_000: val_str = f"{value/1_000_000_000:.2f}b"
    elif value >= 1_000_000: val_str = f"{value/1_000_000:.1f}m"
    else: val_str = f"{value:,.0f} ISK"

    victim = full_data.get('victim', {})
    victim_name = get_esi_name("characters", victim.get('character_id'))
    victim_ship = get_esi_name("types", victim.get('ship_type_id'))
    system_name = get_esi_name("systems", full_data.get('solar_system_id'))
    
    # Поиск Убийцы
    killer_name, killer_ship = "Unknown", "Unknown"
    attackers = full_data.get('attackers', [])
    for att in attackers:
        if att.get('final_blow'):
            killer_name = get_esi_name("characters", att.get('character_id'))
            killer_ship = get_esi_name("types", att.get('ship_type_id'))
            break

    color = 0x3498db
    if "LOSS" in event_type: color = 0xe74c3c
    elif "KILL" in event_type or "TARGET" in event_type: color = 0x2ecc71

    payload = {
        "embeds": [{
            "title": f"💥 {victim_ship} | {val_str}",
            "url": f"https://zkillboard.com/kill/{k_id}/",
            "color": color,
            "thumbnail": {"url": f"https://images.evetech.net/types/{victim.get('ship_type_id')}/render?size=128"},
            "fields": [
                {"name": "👤 Жертва", "value": f"**{victim_name}**", "inline": True},
                {"name": "🌌 Система", "value": f"**{system_name}**", "inline": True},
                {"name": "⏰ Время (EVE)", "value": discord_time, "inline": False}, # Новое поле
                {"name": "💀 Убийца", "value": f"**{killer_name}** ({killer_ship})", "inline": False},
                {"name": "👥 Участники", "value": f"{len(attackers)} пилотов", "inline": True}
            ],
            "footer": {"text": f"Event: {event_type} | ID: {k_id}"}
        }]
    }
    requests.post(webhook_url, json=payload)