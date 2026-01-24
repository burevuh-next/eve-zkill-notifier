def parse_killmail(full_data, config):
    try:
        victim = full_data.get('victim', {})
        zkb = full_data.get('zkb', {})
        
        # Данные килла
        system_id = int(full_data.get('solar_system_id', 0))
        const_id = int(full_data.get('constellation_id', 0))
        reg_id = int(full_data.get('region_id', 0))
        ship_id = int(victim.get('ship_type_id', 0))
        value = zkb.get('totalValue', 0)

        # 1. ПРИОРИТЕТЫ (Игнорируют стоимость)
        if system_id in config.get('ping_sys', []) or ship_id in config.get('ping_ship', []):
            return True, "PRIORITY_TARGET"

        # 2. ПРОВЕРКА СТОИМОСТИ (Для обычных целей)
        if value < config.get('min_value', 0):
            return False, None

        # 3. ФИЛЬТРЫ ЛОКАЦИИ И КОРАБЛЕЙ
        # Обрати внимание: в JSON ключ 'consts', проверяем его здесь
        if ship_id in config.get('ships', []):
            return True, "SHIP_WATCH"
            
        if (system_id in config.get('systems', []) or 
            const_id in config.get('consts', []) or 
            reg_id in config.get('regions', [])):
            return True, "LOCATION_WATCH"

        # 4. КОРПОРАЦИИ И ПЕРСОНАЖИ
        v_corp_id = int(victim.get('corporation_id', 0))
        v_char_id = int(victim.get('character_id', 0))
        
        if v_corp_id in config.get('corps', []) or v_char_id in config.get('chars', []):
            return True, "TARGET_LOSS"

        # Проверка атакующих (если мы ловим убийства наших целей)
        for att in full_data.get('attackers', []):
            if int(att.get('corporation_id', 0)) in config.get('corps', []) or \
               int(att.get('character_id', 0)) in config.get('chars', []):
                return True, "TARGET_KILL"

    except Exception as e:
        print(f"❌ Ошибка в parse_killmail: {e}")
        
    return False, None