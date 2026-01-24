def parse_killmail(full_data, config):
    try:
        victim = full_data.get('victim', {})
        
        # 1. Приводим всё к int сразу, чтобы не делать этого в каждом условии
        system_id = int(full_data.get('solar_system_id', 0))
        const_id = int(full_data.get('constellation_id', 0))
        reg_id = int(full_data.get('region_id', 0))
        ship_id = int(victim.get('ship_type_id', 0))
        
        # 2. Подготавливаем списки (ключи из твоего main.py)
        ping_systems = [int(i) for i in config.get('ping_sys', [])]
        ping_ships = [int(i) for i in config.get('ping_ship', [])]
        
        target_ships = [int(i) for i in config.get('ships', [])]
        target_systems = [int(i) for i in config.get('systems', [])]
        target_corps = [int(i) for i in config.get('corps', [])]
        target_chars = [int(i) for i in config.get('chars', [])]

        # --- ЛОГИКА ОПРЕДЕЛЕНИЯ СОБЫТИЯ ---

        # 1. Сначала проверяем ПРИОРИТЕТЫ (ПИНГИ ИГНОРИРУЮТ МИНИМАЛЬНУЮ СТОИМОСТЬ)
        # ИСПРАВЛЕНО: используем правильные имена переменных ping_systems и ping_ships
        if system_id in ping_systems or ship_id in ping_ships:
            return True, "PRIORITY_TARGET"

        # 2. Проверка по минимальной стоимости для обычных целей
        zkb = full_data.get('zkb', {})
        if zkb.get('totalValue', 0) < config.get('min_value', 0):
            return False, None

        # 3. Проверка отслеживаемых кораблей
        if ship_id in target_ships:
            return True, "SHIP_WATCH"

        # 4. Проверка локации (Система, Регион, Созвездие)
        if system_id in target_systems or const_id in config.get('constellations', []) or reg_id in config.get('regions', []):
            return True, "LOCATION_WATCH"

        # 5. Персонажи (Capsuleers)
        v_char_id = int(victim.get('character_id', 0))
        if v_char_id in target_chars:
            return True, "CHARACTER_LOSS"
            
        for att in full_data.get('attackers', []):
            if int(att.get('character_id', 0)) in target_chars:
                return True, "CHARACTER_KILL"

        # 6. Корпорации
        v_corp_id = int(victim.get('corporation_id', 0))
        if v_corp_id in target_corps:
            return True, "CORP_LOSS"
            
        for att in full_data.get('attackers', []):
            if int(att.get('corporation_id', 0)) in target_corps:
                return True, "CORP_KILL"

    except Exception as e:
        #logging.error(f"❌ Ошибка парсинга: {e}") # Лучше использовать logging
        print(f"❌ Ошибка парсинга: {e}")
        
    return False, None