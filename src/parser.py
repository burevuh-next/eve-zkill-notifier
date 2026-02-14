import logging

def parse_killmail(full_data, config):
    try:
        victim = full_data.get('victim', {})
        zkb = full_data.get('zkb', {})
        
        # 1. Извлекаем основные ID и приводим к int
        system_id = int(full_data.get('solar_system_id', 0))
        const_id = int(full_data.get('constellation_id', 0))
        reg_id = int(full_data.get('region_id', 0))
        ship_id = int(victim.get('ship_type_id', 0))
        
        # Стоимость килла (может быть float)
        value = float(zkb.get('totalValue', 0))
        min_value = float(config.get('min_value', 0))

        # 2. Оптимизируем поиск (приводим конфиги к множествам целых чисел)
        def get_id_set(key):
            return {int(x) for x in config.get(key, []) if str(x).isdigit() or isinstance(x, int)}

        watch_systems = get_id_set('systems')
        watch_consts  = get_id_set('consts')
        watch_regions = get_id_set('regions')
        watch_ships   = get_id_set('ships')
        watch_corps   = get_id_set('corps')
        watch_chars   = get_id_set('chars')
        
        ping_sys      = get_id_set('ping_sys')
        ping_ship     = get_id_set('ping_ship')

        # --- ЛОГИКА ФИЛЬТРАЦИИ ---

        # А. ПРИОРИТЕТЫ (Игнорируют стоимость)
        if system_id in ping_sys or ship_id in ping_ship:
            return True, "PRIORITY_TARGET"

        # Б. ПРОВЕРКА СТОИМОСТИ (Если это не приоритет — проверяем ISK)
        if value < min_value:
            # logging.debug(f"Skip: value {value} < min {min_value}")
            return False, None

        # В. ЛОКАЦИИ И КОРАБЛИ
        if ship_id in watch_ships:
            return True, "SHIP_WATCH"
            
        if (system_id in watch_systems or 
            const_id in watch_consts or 
            reg_id in watch_regions):
            return True, "LOCATION_WATCH"

        # Г. ЖЕРТВА (Корпорация или Персонаж)
        v_corp_id = int(victim.get('corporation_id', 0))
        v_char_id = int(victim.get('character_id', 0))
        
        if v_corp_id in watch_corps or v_char_id in watch_chars:
            return True, "TARGET_LOSS"

        # Д. АТАКУЮЩИЕ (Проверяем, не убил ли кто-то из наших целей кого-то другого)
        for att in full_data.get('attackers', []):
            a_corp_id = int(att.get('corporation_id', 0))
            a_char_id = int(att.get('character_id', 0))
            
            if a_corp_id in watch_corps or a_char_id in watch_chars:
                return True, "TARGET_KILL"

    except Exception as e:
        logging.error(f"❌ Ошибка в parse_killmail: {e}", exc_info=True)
        
    return False, None