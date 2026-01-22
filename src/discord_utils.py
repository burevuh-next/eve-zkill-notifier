import requests
from datetime import datetime

NAME_CACHE = {}

def get_eve_names(ids):
    ids = [int(i) for i in ids if i and str(i).isdigit()]
    if not ids: return {}
    result = {}
    to_fetch = [i for i in ids if i not in NAME_CACHE]
    if to_fetch:
        try:
            url = "https://esi.evetech.net/latest/universe/names/"
            resp = requests.post(url, json=list(set(to_fetch)), timeout=5)
            if resp.status_code == 200:
                for item in resp.json():
                    NAME_CACHE[item['id']] = item['name']
        except: pass
    for i in ids:
        result[i] = NAME_CACHE.get(i, f"ID: {i}")
    return result

def format_isk(value):
    if value >= 1_000_000_000: return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000: return f"{value / 1_000_000:.2f}M"
    return f"{value:,.0f}"

def get_discord_timestamp(esi_time_str):
    try:
        dt = datetime.fromisoformat(esi_time_str.replace('Z', '+00:00'))
        return f"<t:{int(dt.timestamp())}:t>"
    except: return "00:00"

def send_kill_notification(webhook_url, killmail, event_type):
    zkb = killmail.get('zkb', {})
    k_id = killmail.get('killmail_id')
    value = zkb.get('totalValue', 0)
       
    victim = killmail.get('victim', {})
    attacker = next((a for a in killmail.get('attackers', []) if a.get('final_blow')), {})
    
    v_char_id = victim.get('character_id')
    a_char_id = attacker.get('character_id')
    
    system_id = killmail.get('solar_system_id')
    v_corp_id = victim.get('corporation_id')
    a_corp_id = attacker.get('corporation_id')
    v_ship_id = victim.get('ship_type_id')
    a_ship_id = attacker.get('ship_type_id')

    ids_to_resolve = [
        system_id, v_corp_id, a_corp_id, v_ship_id, a_ship_id,
        victim.get('character_id'), attacker.get('character_id')
    ]
    names = get_eve_names(ids_to_resolve)

    v_name = names.get(victim.get('character_id'), "Unknown")
    v_corp = names.get(v_corp_id, "Unknown Corp")
    v_ship = names.get(v_ship_id, "Unknown Ship")
    
    a_name = names.get(attacker.get('character_id'), "NPC / Structure")
    a_corp = names.get(a_corp_id, "No Corporation")
    a_ship = names.get(a_ship_id, "Unknown Ship")
    
    system_name = names.get(system_id, "Unknown System")
    time_short = get_discord_timestamp(killmail.get('killmail_time', ''))

    color = 0x3498db
    if "LOSS" in event_type: color = 0xed1c24
    if "KILL" in event_type: color = 0x2ecc71

# Формируем ссылки на иконки (64 пикселя — оптимально для маленьких иконок)
    v_corp_icon = f"https://images.evetech.net/corporations/{v_corp_id}/logo?size=128"
    a_corp_icon = f"https://images.evetech.net/corporations/{a_corp_id}/logo?size=128"
    v_ship_img = f"https://images.evetech.net/types/{v_ship_id}/render?size=128"
    v_url = f"https://zkillboard.com/character/{v_char_id}/" if v_char_id else "#"
    a_url = f"https://zkillboard.com/character/{a_char_id}/" if a_char_id else "#"
    
    payload = {
        "content": f"✅ **{time_short}** | **{v_name}** |     **{system_name}** ",
        "embeds": [{
            "color": color,
            # Логотип агрессора теперь здесь (он будет больше и заметнее)
            "description": f"# 💰 {format_isk(value)} ISK\n🔗 [Открыть на zKillboard](https://zkillboard.com/kill/{k_id}/)",
            "fields": [
                {
                    "name": "👤 ЖЕРТВА",
                    "value": f"**[{v_name}]({v_url})**\n*{v_ship}*\n\n**Corp:** {v_corp}\n",
                    "inline": True
                },
                {
                    "name": "⚔️ АГРЕССОР",
                    "value": f"**[{a_name}]({a_url})**\n*{a_ship}*\n\n**Corp:** {a_corp}\n",
                    "inline": True
                }
            ],
            "thumbnail": {"url": v_ship_img},
            # Логотип жертвы сделаем крупным внизу для симметрии
            
            "footer": {
                "text": f"KillID: {k_id} • {event_type.replace('_', ' ')}"
            }
        }]
    }
    requests.post(webhook_url, json=payload)