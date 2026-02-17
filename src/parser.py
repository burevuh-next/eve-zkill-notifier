import logging

def parse_killmail(full_data, channel_config, global_filter_sets=None):
    """
    Парсит killmail и применяет фильтры
    
    Args:
        full_data: полные данные killmail
        channel_config: конфигурация конкретного канала
        global_filter_sets: оптимизированные сеты фильтров (опционально)
    """
    try:
        victim = full_data.get('victim', {})
        zkb = full_data.get('zkb', {})
        
        # 1. Извлекаем основные ID
        system_id = int(full_data.get('solar_system_id', 0))
        const_id = int(full_data.get('constellation_id', 0))
        reg_id = int(full_data.get('region_id', 0))
        ship_id = int(victim.get('ship_type_id', 0))
        
        # Стоимость килла
        value = float(zkb.get('totalValue', 0))
        min_value = float(channel_config.get('min_value', 0))

        # 2. Получаем сеты фильтров
        # Если передан глобальный оптимизированный конфиг - используем его
        # Иначе создаем сеты из конфига канала на лету
        if global_filter_sets:
            # Используем готовые сеты (быстрее)
            watch_systems = global_filter_sets.get('systems', set())
            watch_consts = global_filter_sets.get('consts', set())
            watch_regions = global_filter_sets.get('regions', set())
            watch_ships = global_filter_sets.get('ships', set())
            watch_corps = global_filter_sets.get('corps', set())
            watch_chars = global_filter_sets.get('chars', set())
            ping_sys = global_filter_sets.get('ping_sys', set())
            ping_ship = global_filter_sets.get('ping_ship', set())
        else:
            # Fallback: создаем сеты из конфига канала (медленнее, но надежнее)
            def get_id_set(key):
                items = channel_config.get(key, [])
                return {int(x) for x in items if str(x).isdigit()}

            watch_systems = get_id_set('systems')
            watch_consts = get_id_set('consts')
            watch_regions = get_id_set('regions')
            watch_ships = get_id_set('ships')
            watch_corps = get_id_set('corps')
            watch_chars = get_id_set('chars')
            ping_sys = get_id_set('ping_sys')
            ping_ship = get_id_set('ping_ship')

        # --- ЛОГИКА ФИЛЬТРАЦИИ ---
        # А. ПРИОРИТЕТЫ (Игнорируют стоимость)
        if system_id in ping_sys or ship_id in ping_ship:
            return True, "PRIORITY_TARGET"

        # Б. ПРОВЕРКА СТОИМОСТИ
        if value < min_value:
            return False, None

        # В. ЛОКАЦИИ И КОРАБЛИ
        if ship_id in watch_ships:
            return True, "SHIP_WATCH"
            
        if (system_id in watch_systems or 
            const_id in watch_consts or 
            reg_id in watch_regions):
            return True, "LOCATION_WATCH"

        # Г. ЖЕРТВА
        v_corp_id = int(victim.get('corporation_id', 0))
        v_char_id = int(victim.get('character_id', 0))
        
        if v_corp_id in watch_corps or v_char_id in watch_chars:
            return True, "TARGET_LOSS"

        # Д. АТАКУЮЩИЕ
        for att in full_data.get('attackers', []):
            a_corp_id = int(att.get('corporation_id', 0))
            a_char_id = int(att.get('character_id', 0))
            
            if a_corp_id in watch_corps or a_char_id in watch_chars:
                return True, "TARGET_KILL"

    except Exception as e:
        logging.error(f"❌ Ошибка в parse_killmail: {e}", exc_info=True)
        
    return False, None