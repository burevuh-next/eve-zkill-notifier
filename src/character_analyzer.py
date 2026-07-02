import logging
import aiohttp
import asyncio
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from typing import List, Dict, Set, Tuple, Optional
import re

class CharacterAnalyzer:
    """
    Модуль для анализа персонажей EVE Online
    Принимает список имен, возвращает подробную информацию об активности
    """
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self._esi_semaphore = asyncio.Semaphore(10)
        self.cache = {
            "characters": {},      # {char_id: {"name": name, "corporation_id": corp_id, "alliance_id": alliance_id}}
            "corporations": {},    # {corp_id: {"name": name, "ticker": ticker}}
            "alliances": {},       # {alliance_id: {"name": name, "ticker": ticker}}
            "ships": {},           # {ship_id: name}
            "systems": {},         # {system_id: name}
            "zkill": {}            # {char_id: {"last_kills": [], "last_losses": [], "last_activity": timestamp}}
        }
        
        self.stats = {
            "analyzed_characters": 0,
            "api_errors": 0,
            "cache_hits": 0,
            "zkill_requests": 0
        }
        
        logging.info("✅ CharacterAnalyzer инициализирован")
    
    async def ensure_session(self):
        """Создаёт сессию если её нет"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={"User-Agent": "EVE-KillBot/5.0 (Discord Bot)"},
                timeout=aiohttp.ClientTimeout(total=30)
            )
    
    async def close_session(self):
        """Закрывает сессию"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def resolve_names_to_ids(self, names: List[str]) -> Dict[str, int]:
        """
        Конвертирует имена персонажей в ID через ESI
        """
        if not names:
            return {}
        
        await self.ensure_session()
        
        # Очищаем имена от лишних символов
        clean_names = []
        for name in names:
            name = re.sub(r'^[<>]+\s*', '', name.strip())
            name = re.sub(r'\s+$', '', name)
            if name and len(name) > 1:
                clean_names.append(name)
        
        if not clean_names:
            return {}
        
        url = "https://esi.evetech.net/latest/universe/ids/"
        
        try:
            async with self._esi_semaphore:
                async with self.session.post(url, json=clean_names) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result = {}
                        
                        for char_data in data.get('characters', []):
                            result[char_data['name']] = char_data['id']
                        
                        found_names = set(result.keys())
                        for name in clean_names:
                            if name not in found_names:
                                logging.debug(f"Персонаж не найден: {name}")
                        
                        return result
                    else:
                        self.stats["api_errors"] += 1
                        logging.warning(f"ESI вернул статус {resp.status} при поиске имен")
                        return {}
        except Exception as e:
            self.stats["api_errors"] += 1
            logging.error(f"Ошибка при поиске имен: {e}")
            return {}
    
    async def get_character_info(self, character_id: int) -> Dict:
        """
        Получает базовую информацию о персонаже
        """
        if character_id in self.cache["characters"]:
            self.stats["cache_hits"] += 1
            return self.cache["characters"][character_id]
        
        await self.ensure_session()
        url = f"https://esi.evetech.net/latest/characters/{character_id}/"
        
        try:
            async with self._esi_semaphore:
                async with self.session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        char_info = {
                            "id": character_id,
                            "name": data.get('name', f"Unknown_{character_id}"),
                            "corporation_id": data.get('corporation_id', 0),
                            "alliance_id": data.get('alliance_id', 0),
                            "birthday": data.get('birthday', ''),
                            "security_status": data.get('security_status', 0),
                            "title": data.get('title', '')
                        }
                        
                        if char_info["corporation_id"]:
                            corp_info = await self.get_corporation_info(char_info["corporation_id"])
                            char_info["corporation_name"] = corp_info.get("name", "Unknown")
                            char_info["corporation_ticker"] = corp_info.get("ticker", "")
                        
                        if char_info["alliance_id"]:
                            alliance_info = await self.get_alliance_info(char_info["alliance_id"])
                            char_info["alliance_name"] = alliance_info.get("name", "Unknown")
                            char_info["alliance_ticker"] = alliance_info.get("ticker", "")
                        
                        self.cache["characters"][character_id] = char_info
                        return char_info
                    else:
                        self.stats["api_errors"] += 1
                        return {"id": character_id, "name": f"Unknown_{character_id}"}
        except Exception as e:
            self.stats["api_errors"] += 1
            logging.error(f"Ошибка получения информации о персонаже {character_id}: {e}")
            return {"id": character_id, "name": f"Error_{character_id}"}
    
    async def get_corporation_info(self, corporation_id: int) -> Dict:
        """
        Получает информацию о корпорации
        """
        if corporation_id in self.cache["corporations"]:
            return self.cache["corporations"][corporation_id]
        
        await self.ensure_session()
        url = f"https://esi.evetech.net/latest/corporations/{corporation_id}/"
        
        try:
            async with self._esi_semaphore:
                async with self.session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        corp_info = {
                            "id": corporation_id,
                            "name": data.get('name', f"Corp_{corporation_id}"),
                            "ticker": data.get('ticker', ''),
                            "member_count": data.get('member_count', 0)
                        }
                        self.cache["corporations"][corporation_id] = corp_info
                        return corp_info
                    else:
                        return {"id": corporation_id, "name": f"Corp_{corporation_id}", "ticker": ""}
        except Exception:
            return {"id": corporation_id, "name": f"Corp_{corporation_id}", "ticker": ""}
    
    async def get_alliance_info(self, alliance_id: int) -> Dict:
        """
        Получает информацию об альянсе
        """
        if alliance_id in self.cache["alliances"]:
            return self.cache["alliances"][alliance_id]
        
        await self.ensure_session()
        url = f"https://esi.evetech.net/latest/alliances/{alliance_id}/"
        
        try:
            async with self._esi_semaphore:
                async with self.session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        alliance_info = {
                            "id": alliance_id,
                            "name": data.get('name', f"Alliance_{alliance_id}"),
                            "ticker": data.get('ticker', '')
                        }
                        self.cache["alliances"][alliance_id] = alliance_info
                        return alliance_info
                    else:
                        return {"id": alliance_id, "name": f"Alliance_{alliance_id}", "ticker": ""}
        except Exception:
            return {"id": alliance_id, "name": f"Alliance_{alliance_id}", "ticker": ""}
    
    async def get_kill_details_from_esi(self, kill_id: int, hash: str) -> Optional[Dict]:
        """
        Получает полные данные килла из ESI по ID и хэшу
        """
        await self.ensure_session()
        url = f"https://esi.evetech.net/latest/killmails/{kill_id}/{hash}/"
        
        try:
            async with self._esi_semaphore:
                async with self.session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logging.info(f"Получены данные из ESI для килла {kill_id}")
                        return data
                    else:
                        logging.warning(f"ESI вернул {resp.status} для килла {kill_id}")
                        return None
        except Exception as e:
            logging.error(f"Ошибка при запросе к ESI для килла {kill_id}: {e}")
            return None
    
    async def get_zkill_activity(self, character_id: int, limit: int = 10) -> Dict:
        """
        Получает активность персонажа с zKillboard
        """
        self.stats["zkill_requests"] += 1
        
        cache_key = f"zkill_{character_id}"
        if cache_key in self.cache["zkill"]:
            cache_data = self.cache["zkill"][cache_key]
            if datetime.now().timestamp() - cache_data["timestamp"] < 300:
                self.stats["cache_hits"] += 1
                return cache_data["data"]
        
        await self.ensure_session()
        
        # Получаем статистику с zKillboard
        stats_url = f"https://zkillboard.com/api/stats/characterID/{character_id}/"
        kills_url = f"https://zkillboard.com/api/kills/characterID/{character_id}/"
        losses_url = f"https://zkillboard.com/api/losses/characterID/{character_id}/"
        
        kills = []
        losses = []
        stats_data = {}
        
        try:
            async with self.session.get(stats_url) as resp:
                if resp.status == 200:
                    stats_data = await resp.json()
                    logging.info(f"✅ Получена статистика с zKillboard для {character_id}")
                    logging.info(f"📊 Сырые данные stats: {stats_data}")
                    
                    # Проверим наличие alltime
                    if 'alltime' in stats_data:
                        logging.info(f"✅ Найден alltime: {stats_data['alltime']}")
                    else:
                        logging.warning(f"❌ Нет alltime в ответе")
                else:
                    logging.warning(f"❌ zKillboard вернул статус {resp.status} для статистики {character_id}")
                    stats_data = {}
        except Exception as e:
            logging.error(f"❌ Ошибка при запросе статистики: {e}")
            stats_data = {}
        
        # Получаем соло статистику из zKillboard
        solo_kills = stats_data.get('soloKills', 0)  # 568
        total_kills = stats_data.get('shipsDestroyed', 0)  # 1360
        solo_ratio = stats_data.get('soloRatio', 0)  # 45.2

        logging.info(f"🎯 Соло киллы из zKillboard: {solo_kills} из {total_kills} ({solo_ratio}%)")
        
        # Получаем топ корабли из stats zKillboard
        favorite_ships_alltime = Counter()
        if stats_data and 'topAllTime' in stats_data and stats_data['topAllTime'] is not None:
            for item in stats_data['topAllTime']:
                if item.get('type') == 'ship':
                    ships_data = item.get('data', [])
                    if ships_data:  # Проверяем что данные не пустые
                        logging.info(f"📊 Получено {len(ships_data)} топ кораблей с zKillboard")
                        for ship in ships_data[:10]:  # Берем топ-10
                            ship_id = ship.get('shipTypeID')
                            kills = ship.get('kills', 0)
                            if ship_id:
                                favorite_ships_alltime[ship_id] = kills
                                logging.info(f"  - Корабль {ship_id}: {kills} убийств")
                    else:
                        logging.info("📊 Нет данных о топ кораблях")
                    break
        else:
            logging.info("📊 Нет данных topAllTime в статистике")
        
        try:
            async with self.session.get(kills_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        kills = data
                        logging.info(f"Получено {len(kills)} киллов для {character_id}")
        except Exception as e:
            logging.error(f"Ошибка при запросе киллов: {e}")
        
        try:
            async with self.session.get(losses_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        losses = data
                        logging.info(f"Получено {len(losses)} потерь для {character_id}")
        except Exception as e:
            logging.error(f"Ошибка при запросе потерь: {e}")
        
        kills_sample = kills[:limit] if kills else []
        losses_sample = losses[:limit] if losses else []
        
        result = {
            "kills": [],
            "losses": [],
            "total_kills": total_kills,
            "total_losses": stats_data.get('shipLost', 0),
            "favorite_ships": favorite_ships_alltime,
            "common_systems": Counter(),
            "solo_kills": solo_kills,
            "solo_ratio": solo_ratio,
            "gang_kills": total_kills - solo_kills,
            "recent_activity": None,
            "has_data": len(kills) > 0 or len(losses) > 0,
            "stats": stats_data
        }
        
        if not result["has_data"]:
            logging.info(f"Нет активности для персонажа {character_id}")
            self.cache["zkill"][cache_key] = {
                "timestamp": datetime.now().timestamp(),
                "data": result
            }
            return result
        
        # Анализируем киллы
        if kills_sample:
            for kill in kills_sample[:5]:
                try:
                    kill_data = await self._analyze_kill(kill, character_id, is_killer=True)
                    if kill_data:
                        result["kills"].append(kill_data)
                        
                        # Собираем статистику по кораблям
                        attackers = kill.get('attackers', [])
                        if isinstance(attackers, list):
                            for attacker in attackers:
                                if isinstance(attacker, dict) and attacker.get('character_id') == character_id:
                                    ship_id = attacker.get('ship_type_id')
                                    if ship_id:
                                        result["favorite_ships"][ship_id] += 1
                                    break
                        
                        system_id = kill.get('solar_system_id')
                        if system_id:
                            result["common_systems"][system_id] += 1
                        
                        # Соло/группа
                        attackers_list = kill.get('attackers', [])
                        if isinstance(attackers_list, list):
                            if len(attackers_list) == 1:
                                result["solo_kills"] += 1
                            else:
                                result["gang_kills"] += 1
                        
                        kill_time = kill.get('killmail_time', '')
                        if kill_time and (not result["recent_activity"] or kill_time > result["recent_activity"]):
                            result["recent_activity"] = kill_time
                except Exception as e:
                    logging.error(f"Ошибка при анализе килла: {e}")
                    continue
        
        # Анализируем потери
        if losses_sample:
            for loss in losses_sample[:5]:
                try:
                    loss_data = await self._analyze_kill(loss, character_id, is_killer=False)
                    if loss_data:
                        result["losses"].append(loss_data)
                        
                        victim = loss.get('victim', {})
                        if isinstance(victim, dict):
                            ship_id = victim.get('ship_type_id')
                            if ship_id:
                                result["favorite_ships"][ship_id] += 1
                        
                        system_id = loss.get('solar_system_id')
                        if system_id:
                            result["common_systems"][system_id] += 1
                        
                        loss_time = loss.get('killmail_time', '')
                        if loss_time and (not result["recent_activity"] or loss_time > result["recent_activity"]):
                            result["recent_activity"] = loss_time
                except Exception as e:
                    logging.error(f"Ошибка при анализе потери: {e}")
                    continue
        
        self.cache["zkill"][cache_key] = {
            "timestamp": datetime.now().timestamp(),
            "data": result
        }
        
        logging.info(f"Анализ завершен для {character_id}: {len(result['kills'])} киллов, {len(result['losses'])} потерь")
        return result
    
    async def _analyze_kill(self, kill: Dict, character_id: int, is_killer: bool) -> Optional[Dict]:
        """
        Анализирует отдельный килл
        """
        if not isinstance(kill, dict):
            return None
        
        try:
            killmail_id = kill.get('killmail_id', 0)
            zkb = kill.get('zkb', {})
            
            victim = kill.get('victim', {})
            if not victim or not victim.get('character_id'):
                kill_hash = zkb.get('hash')
                if kill_hash:
                    esi_data = await self.get_kill_details_from_esi(killmail_id, kill_hash)
                    if esi_data:
                        kill = esi_data
                        victim = kill.get('victim', {})
            
            if not victim:
                return None
            
            system_id = kill.get('solar_system_id', 0)
            victim_id = victim.get('character_id', 0)
            victim_ship_id = victim.get('ship_type_id', 0)
            
            system_name = await self.get_system_name(system_id) if system_id else "Unknown System"
            victim_name = await self.get_character_name(victim_id) if victim_id else "Unknown"
            victim_ship = await self.get_ship_name(victim_ship_id) if victim_ship_id else "Unknown Ship"
            
            # Получаем время килла и форматируем его
            kill_time = kill.get('killmail_time', '')
            formatted_time = "Unknown"
            if kill_time:
                try:
                    # Парсим ISO формат и преобразуем в читаемый вид
                    dt = datetime.fromisoformat(kill_time.replace('Z', '+00:00'))
                    # Формат: "2024-03-07 15:30"
                    formatted_time = dt.strftime('%Y-%m-%d %H:%M')
                except Exception as e:
                    logging.error(f"Ошибка парсинга времени {kill_time}: {e}")
            
             # Определяем количество атакующих
            attackers_list = kill.get('attackers', [])
            attackers_count = len(attackers_list) if isinstance(attackers_list, list) else 0
            is_solo = attackers_count == 1
            
            if is_killer:
                # Ищем атакующего
                attacker_info = None
                attackers = kill.get('attackers', [])
                if isinstance(attackers, list):
                    for attacker in attackers:
                        if isinstance(attacker, dict) and attacker.get('character_id') == character_id:
                            attacker_info = attacker
                            break
                
                if attacker_info:
                    ship_id = attacker_info.get('ship_type_id', 0)
                    ship_name = await self.get_ship_name(ship_id) if ship_id else "Unknown Ship"
                    
                    # Формат: Корабль_убийцы -> Имя_жертвы's Корабль_жертвы
                    victim_display = f"{ship_name} → {victim_name}'s {victim_ship}"
                else:
                    ship_name = "Unknown Ship"
                    victim_display = f"Unknown → {victim_name}'s {victim_ship}"
            else:
                # Персонаж - жертва
                ship_name = victim_ship
                
                # Кто убил
                final_blow_attacker = None
                attackers = kill.get('attackers', [])
                if isinstance(attackers, list):
                    for attacker in attackers:
                        if isinstance(attacker, dict) and attacker.get('final_blow', False):
                            final_blow_attacker = attacker
                            break
                
                if final_blow_attacker:
                    killer_id = final_blow_attacker.get('character_id', 0)
                    killer_name = await self.get_character_name(killer_id) if killer_id else "Unknown"
                    killer_ship_id = final_blow_attacker.get('ship_type_id', 0)
                    killer_ship = await self.get_ship_name(killer_ship_id) if killer_ship_id else "Unknown Ship"
                    
                    # Формат: Корабль_жертвы ← Имя_убийцы's Корабль_убийцы
                    victim_display = f"{ship_name} ← {killer_name}'s {killer_ship}"
                else:
                    victim_display = f"{ship_name} ← Unknown"
            
            # Форматируем стоимость
            value = zkb.get('totalValue', 0)
            if value >= 1_000_000_000:
                value_str = f"{value/1_000_000_000:.2f}B"
            elif value >= 1_000_000:
                value_str = f"{value/1_000_000:.1f}M"
            elif value >= 1_000:
                value_str = f"{value/1_000:.1f}K"
            else:
                value_str = f"{value:,.0f}"
            # Добавляем эмодзи для соло/группа
            solo_emoji = "👤" if is_solo else "👥"
            
            result = {
                "kill_id": killmail_id,
                "time": formatted_time,
                "raw_time": kill_time,
                "system": system_name,
                "value": value,
                "value_str": value_str,
                "ship": ship_name,
                "victim": victim_display,
                "is_solo": is_solo,
                "solo_emoji": solo_emoji,
                "attackers_count": attackers_count,
                "zkb_url": f"https://zkillboard.com/kill/{killmail_id}/"
            }
            
            return result
            
        except Exception as e:
            logging.error(f"Ошибка в _analyze_kill: {e}")
            return None
    
    async def get_character_name(self, character_id: int) -> str:
        """Получает имя персонажа по ID"""
        if character_id == 0:
            return "Unknown"
        
        if character_id in self.cache["characters"]:
            cached = self.cache["characters"][character_id]
            if isinstance(cached, dict):
                return cached.get("name", f"Char_{character_id}")
            return cached
        
        await self.ensure_session()
        url = f"https://esi.evetech.net/latest/characters/{character_id}/"
        
        try:
            async with self._esi_semaphore:
                async with self.session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        name = data.get('name', f"Char_{character_id}")
                        self.cache["characters"][character_id] = {"name": name, "id": character_id}
                        return name
                    else:
                        return f"Char_{character_id}"
        except Exception:
            return f"Char_{character_id}"
    
    async def get_ship_name(self, ship_id: int) -> str:
        """Получает название корабля"""
        if ship_id == 0:
            return "Unknown Ship"
        
        if ship_id in self.cache["ships"]:
            return self.cache["ships"][ship_id]
        
        await self.ensure_session()
        url = f"https://esi.evetech.net/latest/universe/types/{ship_id}/"
        
        try:
            async with self._esi_semaphore:
                async with self.session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        name = data.get('name', f"Ship_{ship_id}")
                        self.cache["ships"][ship_id] = name
                        return name
                    else:
                        return f"Ship_{ship_id}"
        except Exception:
            return f"Ship_{ship_id}"
    
    async def get_system_name(self, system_id: int) -> str:
        """Получает название системы"""
        if system_id == 0:
            return "Unknown System"
        
        cache_key = f"system_{system_id}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        await self.ensure_session()
        url = f"https://esi.evetech.net/latest/universe/systems/{system_id}/"
        
        try:
            async with self._esi_semaphore:
                async with self.session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        name = data.get('name', f"System_{system_id}")
                        self.cache[cache_key] = name
                        return name
                    else:
                        return f"System_{system_id}"
        except Exception:
            return f"System_{system_id}"
    
    async def analyze_characters(self, names_input: str) -> List[Dict]:
        """
        Основной метод анализа списка персонажей
        """
        lines = names_input.strip().split('\n')
        names = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            match = re.match(r'^([^\[\(]+)', line)
            if match:
                name = match.group(1).strip()
                if name:
                    names.append(name)
            else:
                names.append(line)
        
        if not names:
            return []
        
        name_to_id = await self.resolve_names_to_ids(names)
        
        if not name_to_id:
            return []
        
        results = []
        
        for name, char_id in name_to_id.items():
            logging.info(f"Анализирую персонажа: {name} (ID: {char_id})")
            
            char_info = await self.get_character_info(char_id)
            activity = await self.get_zkill_activity(char_id)
            
            # СОХРАНЯЕМ ИМЕНА КОРАБЛЕЙ ДЛЯ ЛЮБИМЫХ
            ship_names = {}
            fav_ships = activity.get("favorite_ships", {})

            logging.info(f"📊 favorite_ships для {name} (с zKillboard): {dict(fav_ships)}")

            for ship_id in fav_ships.keys():
                ship_name = await self.get_ship_name(ship_id)
                ship_names[ship_id] = ship_name
                kills = fav_ships[ship_id]
                logging.info(f"  - {ship_name} ({ship_id}): {kills} убийств")

            logging.info(f"  - Всего сохранено имен: {len(ship_names)}")
            
            result = {
                "name": name,
                "id": char_id,
                "corporation": char_info.get("corporation_name", "Unknown"),
                "corporation_id": char_info.get("corporation_id", 0), 
                "alliance": char_info.get("alliance_name", "None"),
                "alliance_id": char_info.get("alliance_id", 0),  
                "security_status": char_info.get("security_status", 0),
                "birthday": char_info.get("birthday", ""),
                "activity": activity,
                "ship_names": ship_names
            }
            
            results.append(result)
            self.stats["analyzed_characters"] += 1
            
            await asyncio.sleep(0.5)
        
        return results
    
    def format_for_discord(self, results: List[Dict]) -> str:
        """
        Форматирует результаты для отправки в Discord
        """
        if not results:
            return "❌ Ни одного персонажа не найдено"
        
        lines = []
        
        for result in results:
            name = result["name"]
            char_id = result["id"]
            corp = result["corporation"]
            corp_id = result.get("corporation_id", 0)
            alliance = result["alliance"]
            alliance_id = result.get("alliance_id", 0)
            sec_status = result["security_status"]
            ship_names = result.get("ship_names", {})
 
            # Ссылки на zKillboard
            zkill_char_link = f"<https://zkillboard.com/character/{char_id}/>"
            zkill_corp_link = f"<https://zkillboard.com/corporation/{corp_id}/>" if corp_id else ""
            zkill_alliance_link = f"<https://zkillboard.com/alliance/{alliance_id}/>" if alliance_id and alliance_id != 0 else ""
            
                       
            sec_emoji = "🟢" if sec_status >= 0 else "🔴"
            lines.append(f"\n**{sec_emoji} [{name}]({zkill_char_link})**")
            

            
            if corp_id:
                lines.append(f"🏢 [{corp}]({zkill_corp_link})")
                        
            if alliance_id:
                lines.append(f"🌐 [{alliance}]({zkill_alliance_link})")
            
            
            # === ДОБАВЛЯЕМ СТАТИСТИКУ С ZKILLBOARD ===
            # Статистика из zKillboard
            activity = result["activity"]
            stats_data = activity.get("stats", {})

            # Проверяем наличие данных
            ships_destroyed = stats_data.get('shipsDestroyed', 0)
            ships_lost = stats_data.get('shipsLost', 0)
            isk_destroyed = stats_data.get('iskDestroyed', 0)
            isk_lost = stats_data.get('iskLost', 0)

            if ships_destroyed > 0 or ships_lost > 0:
                # Рассчитываем эффективность
                if ships_destroyed + ships_lost > 0:
                    efficiency = (ships_destroyed / (ships_destroyed + ships_lost)) * 100
                else:
                    efficiency = 0
                
                # Создаем прогресс-бар
                bar_length = 10
                filled = int((efficiency / 100) * bar_length)
                
                # Выбираем цвет и эмодзи в зависимости от эффективности
                if efficiency >= 90:
                    danger_emoji = "💀💀💀"
                    bar_color = "🟥"  # красный для очень опасных
                elif efficiency >= 75:
                    danger_emoji = "💀💀"
                    bar_color = "🟧"  # оранжевый
                elif efficiency >= 60:
                    danger_emoji = "💀"
                    bar_color = "🟨"  # желтый
                elif efficiency >= 40:
                    danger_emoji = "⚠️"
                    bar_color = "🟩"  # зеленый
                else:
                    danger_emoji = "🌱"
                    bar_color = "⬜"  # белый для безопасных
                
                # Создаем полоску
                bar = bar_color * filled + "⬜" * (bar_length - filled)
                
                lines.append(f"\n📊 **STATISTICS (All Time)**")
                lines.append(f"├ Ships Destroyed: **{ships_destroyed:,}** | Ships Lost: **{ships_lost:,}**")
                lines.append(f"├ ISK Destroyed: **{self.format_isk(isk_destroyed)}** | ISK Lost: **{self.format_isk(isk_lost)}**")
                lines.append(f"└ **Dangerous:** {danger_emoji} {bar} {efficiency:.1f}%")
                
                # Соло статистика из zKillboard
                solo_kills = activity.get("solo_kills", 0)  # 568
                total_kills_all = activity.get("total_kills", 0)  # 1360
                
                if total_kills_all > 0:
                    gang_kills = total_kills_all - solo_kills  # 1360 - 568 = 792
                    
                    solo_percent = (solo_kills / total_kills_all) * 100
                    gang_percent = 100 - solo_percent
                                        
                    lines.append(f"🎯 **Solo:** {solo_kills} ({solo_percent:.0f}%) | **Group:** {gang_kills} ({gang_percent:.0f}%)")
                    
                    logging.info(f"🎯 Соло статистика: {solo_kills}/{total_kills_all} ({solo_percent:.1f}%)")
                else:
                    lines.append("🎯 **Solo:** 0 (0%) | **Group:** 0 (0%)")
            
            # Любимые корабли
            fav_ships = activity.get("favorite_ships", {})
            if fav_ships:
                top_ships = sorted(fav_ships.items(), key=lambda x: x[1], reverse=True)[:5]
                ships_text = []
                for ship_id, count in top_ships:
                    ship_name = ship_names.get(ship_id, f"Ship_{ship_id}")
                    ships_text.append(f"**{ship_name}**: {count}")
                lines.append(f"\n🚀 Top Ships:  {',  '.join(ships_text)}")
            
            # Последние убийства
            if activity.get("kills"):
                lines.append(f"\n**Recent Kills (last {len(activity['kills'])}):**")
                for kill in activity["kills"]:
                    solo_emoji = kill.get('solo_emoji', '👥')
                    kill_time = kill.get('time', 'Unknown')
                    # Разбиваем victim_display на части и выделяем корабли жирным
                    victim_parts = kill['victim'].split('→')
                    if len(victim_parts) == 2:
                        killer_ship = victim_parts[0].strip()
                        victim_part = victim_parts[1].strip()
                        # Выделяем корабли жирным
                        formatted_kill = f"**{killer_ship}** → {victim_part}"
                    else:
                        formatted_kill = kill['victim']
                    
                    lines.append(f"  • `{kill_time}`  {solo_emoji} {formatted_kill} | {kill['value_str']} ISK | {kill['system']}")
            
            # Последние потери
            if activity.get("losses"):
                lines.append(f"\n**Recent Losses (last {len(activity['losses'])}):**")
                for loss in activity["losses"]:
                    solo_emoji = loss.get('solo_emoji', '👥')
                    loss_time = loss.get('time', 'Unknown')
                    # Разбиваем victim_display на части и выделяем корабли жирным
                    victim_parts = loss['victim'].split('←')
                    if len(victim_parts) == 2:
                        victim_ship = victim_parts[0].strip()
                        killer_part = victim_parts[1].strip()
                        # Выделяем корабли жирным
                        formatted_loss = f"**{victim_ship}** ← {killer_part}"
                    else:
                        formatted_loss = loss['victim']
                    
                    lines.append(f"  • `{loss_time}`  {solo_emoji} {formatted_loss} | {loss['value_str']} ISK | {loss['system']}")
                        
            lines.append("\n---")
        
        return "\n".join(lines)
    
    def format_isk(self, value: float) -> str:
        """Форматирует ISK"""
        if value >= 1_000_000_000_000:
            return f"{value/1_000_000_000_000:.2f}T"
        elif value >= 1_000_000_000:
            return f"{value/1_000_000_000:.2f}B"
        elif value >= 1_000_000:
            return f"{value/1_000_000:.1f}M"
        elif value >= 1_000:
            return f"{value/1_000:.1f}K"
        else:
            return f"{value:,.0f}"
    
    def get_stats(self) -> Dict:
        """Возвращает статистику работы модуля"""
        return {
            **self.stats,
            "cache_size": sum(len(v) for v in self.cache.values())
        }


# Создаём глобальный экземпляр
_character_analyzer = CharacterAnalyzer()

def get_character_analyzer():
    """Возвращает глобальный экземпляр CharacterAnalyzer"""
    return _character_analyzer