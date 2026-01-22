def parse_killmail(full_data, config):
    try:
        zkb = full_data.get('zkb', {})
        if zkb.get('totalValue', 0) < config['min_value']:
            return False, None

        victim = full_data.get('victim', {})
        system_id = full_data.get('solar_system_id')
        const_id = full_data.get('constellation_id')
        reg_id = full_data.get('region_id')
        ship_id = victim.get('ship_type_id')

        # 1. Приоритет: Отслеживаемые корабли
        if ship_id in config['ships']:
            return True, "SHIP_TARGET_SPOTTED"

        # 2. Локация: Система или Созвездие
        if system_id in config['systems'] or const_id in config['constellations'] or reg_id in config['regions']:
            return True, "LOCATION_WATCH_EVENT"

        # 3. Корпорации
        if victim.get('corporation_id') in config['corps']:
            return True, "CORP_LOSS"
        for att in full_data.get('attackers', []):
            if att.get('corporation_id') in config['corps']:
                return True, "CORP_KILL"

    except Exception as e:
        print(f"Parsing error: {e}")
    return False, None