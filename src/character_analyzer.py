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
            # Убираем возможные префиксы из EVE локального чата
            name = re.sub(r'^[<>]+\s*', '', name.strip())
            name = re.sub(r'\s+$', '', name)
            if name and len(name) > 1:
                clean_names.append(name)
        
        if not clean_names:
            return {}
        
        url = "https://esi.evetech.net/latest/universe/ids/"
        
        try:
            async with self.session.post(url, json=clean_names) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = {}
                    
                    # ESI возвращает разные секции для разных типов
                    for char_data in data.get('characters', []):
                        result[char_data['name']] = char_data['id']
                    
                    # Логируем не найденные имена
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
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Базовая информация
                    char_info = {
                        "id": character_id,
                        "name": data.get('name', f"Unknown_{character_id}"),
                        "corporation_id": data.get('corporation_id', 0),
                        "alliance_id": data.get('alliance_id', 0),
                        "birthday": data.get('birthday', ''),
                        "security_status": data.get('security_status', 0),
                        "title": data.get('title', '')
                    }
                    
                    # Получаем информацию о корпорации
                    if char_info["corporation_id"]:
                        corp_info = await self.get_corporation_info(char_info["corporation_id"])
                        char_info["corporation_name"] = corp_info.get("name", "Unknown")
                        char_info["corporation_ticker"] = corp_info.get("ticker", "")
                    
                    # Получаем информацию об альянсе
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
    

    async def get_zkill_activity(self, character_id: int, limit: int = 10) -> Dict:
        """
        Получает активность персонажа с zKillboard
        """
        self.stats["zkill_requests"] += 1
        
        # Проверяем кеш
        cache_key = f"zkill_{character_id}"
        if cache_key in self.cache["zkill"]:
            cache_data = self.cache["zkill"][cache_key]
            # Кеш жив 5 минут
            if datetime.now().timestamp() - cache_data["timestamp"] < 300:
                self.stats["cache_hits"] += 1
                return cache_data["data"]
        
        await self.ensure_session()
        
        # Используем стандартный endpoint без параметра limit
        # zKillboard по умолчанию возвращает последние киллы
        kills_url = f"https://zkillboard.com/api/kills/characterID/{character_id}/"
        losses_url = f"https://zkillboard.com/api/losses/characterID/{character_id}/"
        
        kills = []
        losses = []
        
        try:
            # Запрашиваем киллы
            async with self.session.get(kills_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Проверяем, что данные - это список
                    if isinstance(data, list):
                        kills = data
                        logging.info(f"Получено {len(kills)} киллов для {character_id}")
                    else:
                        # Если это словарь, возможно это сообщение об ошибке
                        if isinstance(data, dict):
                            if 'error' in data:
                                logging.warning(f"zKillboard вернул ошибку для киллов {character_id}: {data['error']}")
                            else:
                                logging.warning(f"zKillboard вернул словарь для киллов {character_id}: {data.keys()}")
                        kills = []
                elif resp.status == 404:
                    logging.info(f"Нет данных о киллах для {character_id}")
                    kills = []
                else:
                    logging.warning(f"zKillboard вернул статус {resp.status} для киллов {character_id}")
                    kills = []
        
        except Exception as e:
            logging.error(f"Ошибка при запросе киллов к zKillboard: {e}")
            self.stats["api_errors"] += 1
            kills = []
        
        try:
            # Запрашиваем потери
            async with self.session.get(losses_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Проверяем, что данные - это список
                    if isinstance(data, list):
                        losses = data
                        logging.info(f"Получено {len(losses)} потерь для {character_id}")
                    else:
                        # Если это словарь, возможно это сообщение об ошибке
                        if isinstance(data, dict):
                            if 'error' in data:
                                logging.warning(f"zKillboard вернул ошибку для потерь {character_id}: {data['error']}")
                            else:
                                logging.warning(f"zKillboard вернул словарь для потерь {character_id}: {data.keys()}")
                        losses = []
                elif resp.status == 404:
                    logging.info(f"Нет данных о потерях для {character_id}")
                    losses = []
                else:
                    logging.warning(f"zKillboard вернул статус {resp.status} для потерь {character_id}")
                    losses = []
        
        except Exception as e:
            logging.error(f"Ошибка при запросе потерь к zKillboard: {e}")
            self.stats["api_errors"] += 1
            losses = []
        
        # Ограничиваем количество данных вручную после получения
        kills = kills[:limit] if kills else []
        losses = losses[:limit] if losses else []
        
        # Анализируем активность
        result = {
            "kills": [],
            "losses": [],
            "total_kills": len(kills),
            "total_losses": len(losses),
            "favorite_ships": Counter(),
            "common_systems": Counter(),
            "solo_kills": 0,
            "gang_kills": 0,
            "recent_activity": None,
            "has_data": len(kills) > 0 or len(losses) > 0
        }
        
        # Если нет данных, сразу возвращаем результат
        if not result["has_data"]:
            logging.info(f"Нет активности для персонажа {character_id}")
            self.cache["zkill"][cache_key] = {
                "timestamp": datetime.now().timestamp(),
                "data": result
            }
            return result
        
        # Анализируем киллы
        if kills and isinstance(kills, list):
            for kill in kills[:5]:  # Берем только первые 5 для детального анализа
                try:
                    kill_data = await self._analyze_kill(kill, character_id, is_killer=True)
                    if kill_data:  # Проверяем, что данные не пустые
                        result["kills"].append(kill_data)
                        
                        # Извлекаем данные для статистики
                        victim = kill.get('victim', {})
                        if isinstance(victim, dict):
                            ship_id = victim.get('ship_type_id')
                            if ship_id:
                                result["favorite_ships"][ship_id] += 1
                        
                        system_id = kill.get('solar_system_id')
                        if system_id:
                            result["common_systems"][system_id] += 1
                        
                        # Проверяем соло/группа
                        attackers = kill.get('attackers', [])
                        if isinstance(attackers, list):
                            if len(attackers) == 1:
                                result["solo_kills"] += 1
                            else:
                                result["gang_kills"] += 1
                        
                        # Время последней активности
                        kill_time = kill.get('killmail_time', '')
                        if kill_time and (not result["recent_activity"] or kill_time > result["recent_activity"]):
                            result["recent_activity"] = kill_time
                except Exception as e:
                    logging.error(f"Ошибка при анализе килла: {e}")
                    continue
        
        # Анализируем потери
        if losses and isinstance(losses, list):
            for loss in losses[:5]:
                try:
                    loss_data = await self._analyze_kill(loss, character_id, is_killer=False)
                    if loss_data:
                        result["losses"].append(loss_data)
                        
                        # Извлекаем данные для статистики
                        victim = loss.get('victim', {})
                        if isinstance(victim, dict):
                            ship_id = victim.get('ship_type_id')
                            if ship_id:
                                result["favorite_ships"][ship_id] += 1
                        
                        system_id = loss.get('solar_system_id')
                        if system_id:
                            result["common_systems"][system_id] += 1
                        
                        # Время последней активности
                        loss_time = loss.get('killmail_time', '')
                        if loss_time and (not result["recent_activity"] or loss_time > result["recent_activity"]):
                            result["recent_activity"] = loss_time
                except Exception as e:
                    logging.error(f"Ошибка при анализе потери: {e}")
                    continue
        
        # Сохраняем в кеш
        self.cache["zkill"][cache_key] = {
            "timestamp": datetime.now().timestamp(),
            "data": result
        }
        
        logging.info(f"Анализ завершен для {character_id}: {len(result['kills'])} киллов, {len(result['losses'])} потерь")
        return result
    
    async def _analyze_kill(self, kill: Dict, character_id: int, is_killer: bool) -> Optional[Dict]:
      """
      Анализирует отдельный килл с полным получением имен
      """
      if not isinstance(kill, dict):
          logging.warning(f"Передан не словарь в _analyze_kill: {type(kill)}")
          return None
      
      try:
          victim = kill.get('victim', {})
          if not isinstance(victim, dict):
              victim = {}
          
          zkb = kill.get('zkb', {})
          if not isinstance(zkb, dict):
              zkb = {}
          
          # Получаем ID для запросов
          killmail_id = kill.get('killmail_id', 0)
          
          # Определяем роль персонажа
          if is_killer:
              # Ищем атакующего с нашим персонажем
              attacker_info = None
              attackers = kill.get('attackers', [])
              if isinstance(attackers, list):
                  for attacker in attackers:
                      if isinstance(attacker, dict) and attacker.get('character_id') == character_id:
                          attacker_info = attacker
                          break
              
              ship_id = attacker_info.get('ship_type_id') if attacker_info and isinstance(attacker_info, dict) else 0
              ship_name = await self.get_ship_name(ship_id) if ship_id else "Unknown Ship"
              damage = attacker_info.get('damage_done', 0) if attacker_info and isinstance(attacker_info, dict) else 0
              final_blow = attacker_info.get('final_blow', False) if attacker_info and isinstance(attacker_info, dict) else False
              
              # Кого убили
              victim_id = victim.get('character_id', 0)
              victim_name = await self.get_character_name(victim_id) if victim_id else "Unknown"
              victim_ship_id = victim.get('ship_type_id', 0)
              victim_ship = await self.get_ship_name(victim_ship_id) if victim_ship_id else "Unknown Ship"
              
              ship_display = ship_name
              victim_display = f"{victim_name} in {victim_ship}"
          else:
              # Персонаж - жертва
              ship_id = victim.get('ship_type_id', 0)
              ship_name = await self.get_ship_name(ship_id) if ship_id else "Unknown Ship"
              damage = None
              final_blow = None
              
              # Кто убил (финальный удар)
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
                  victim_display = f"killed by {killer_name} in {killer_ship}"
              else:
                  victim_display = "Unknown killer"
              
              ship_display = ship_name
          
          # Получаем название системы
          system_id = kill.get('solar_system_id', 0)
          system_name = await self.get_system_name(system_id) if system_id else "Unknown System"
          
          # Форматируем стоимость
          value = zkb.get('totalValue', 0)
          if value >= 1_000_000_000:
              value_str = f"{value/1_000_000_000:.2f}B"
          elif value >= 1_000_000:
              value_str = f"{value/1_000_000:.1f}M"
          else:
              value_str = f"{value:,.0f}"
          
          attackers_list = kill.get('attackers', [])
          attackers_count = len(attackers_list) if isinstance(attackers_list, list) else 0
          
          result = {
              "kill_id": killmail_id,
              "time": kill.get('killmail_time', ''),
              "system": system_name,
              "system_id": system_id,
              "value": value,
              "value_str": value_str,
              "ship": ship_display,
              "ship_id": ship_id,
              "victim": victim_display,
              "damage_done": damage,
              "final_blow": final_blow,
              "attackers_count": attackers_count,
              "is_killer": is_killer,
              "zkb_url": f"https://zkillboard.com/kill/{killmail_id}/"
          }
          
          # Логируем для отладки
          logging.debug(f"Анализ килла {killmail_id}: {result['victim']} в {result['system']}")
          
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
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    name = data.get('name', f"Char_{character_id}")
                    # Сохраняем в кеш
                    self.cache["characters"][character_id] = {"name": name, "id": character_id}
                    return name
                else:
                    logging.warning(f"ESI вернул {resp.status} для персонажа {character_id}")
                    return f"Char_{character_id}"
        except Exception as e:
            logging.error(f"Ошибка получения имени персонажа {character_id}: {e}")
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
        Принимает строку с именами (можно скопировать из локала)
        """
        # Разбиваем входную строку на имена
        lines = names_input.strip().split('\n')
        names = []
        
        for line in lines:
            # Убираем возможные префиксы из EVE локала
            # Формат обычно: "Name [corp]" или "Name"
            line = line.strip()
            if not line:
                continue
            
            # Пытаемся извлечь имя до первого пробела или скобки
            match = re.match(r'^([^\[\(]+)', line)
            if match:
                name = match.group(1).strip()
                if name:
                    names.append(name)
            else:
                names.append(line)
        
        if not names:
            return []
        
        # Конвертируем имена в ID
        name_to_id = await self.resolve_names_to_ids(names)
        
        if not name_to_id:
            return []
        
        # Анализируем каждого персонажа
        results = []
        
        for name, char_id in name_to_id.items():
            logging.info(f"Анализирую персонажа: {name} (ID: {char_id})")
            
            # Получаем базовую информацию
            char_info = await self.get_character_info(char_id)
            
            # Получаем активность с zKillboard
            activity = await self.get_zkill_activity(char_id)
            
            # Формируем результат
            result = {
                "name": name,
                "id": char_id,
                "corporation": char_info.get("corporation_name", "Unknown"),
                "corporation_ticker": char_info.get("corporation_ticker", ""),
                "alliance": char_info.get("alliance_name", "None"),
                "alliance_ticker": char_info.get("alliance_ticker", ""),
                "security_status": char_info.get("security_status", 0),
                "birthday": char_info.get("birthday", ""),
                "activity": activity
            }
            
            results.append(result)
            self.stats["analyzed_characters"] += 1
            
            # Небольшая задержка, чтобы не нагружать API
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
            corp = result["corporation"]
            corp_ticker = result["corporation_ticker"]
            alliance = result["alliance"]
            sec_status = result["security_status"]
            
            # Заголовок
            sec_emoji = "🟢" if sec_status >= 0 else "🔴"
            lines.append(f"\n**{sec_emoji} {name}**")
            
            # Корпорация/альянс
            if corp_ticker:
                lines.append(f"🏢 {corp} [{corp_ticker}]")
            else:
                lines.append(f"🏢 {corp}")
            
            if alliance != "None":
                lines.append(f"🌐 {alliance}")
            
            # Статистика активности
            activity = result["activity"]
            total_kills = activity.get("total_kills", 0)
            total_losses = activity.get("total_losses", 0)
            solo = activity.get("solo_kills", 0)
            gang = activity.get("gang_kills", 0)
            
            lines.append(f"⚔️ Kills: {total_kills} | 💀 Losses: {total_losses}")
            if total_kills > 0:
                solo_pct = (solo / total_kills) * 100 if total_kills > 0 else 0
                lines.append(f"🎯 Solo: {solo} ({solo_pct:.0f}%) | Group: {gang}")
            
            # Любимые корабли
            fav_ships = activity.get("favorite_ships", {})
            if fav_ships:
                # Берем топ-3
                top_ships = sorted(fav_ships.items(), key=lambda x: x[1], reverse=True)[:3]
                ships_text = []
                for ship_id, count in top_ships:
                    # Здесь нужно получить имя корабля, но у нас нет ship_id в контексте
                    # Временно используем ID
                    ships_text.append(f"Ship_{ship_id}: {count}")
                lines.append(f"🚀 Fav: {', '.join(ships_text)}")
            
            # Последние киллы/потери
            if activity.get("kills"):
                lines.append("**Последние убийства:**")
                for kill in activity["kills"][:2]:  # Показываем только 2
                    value = kill.get("value", 0)
                    val_str = f"{value/1e9:.2f}B" if value >= 1e9 else f"{value/1e6:.1f}M"
                    lines.append(f"  • {kill['victim']} in {kill['ship']} | {val_str} ISK | {kill['system']}")
            
            if activity.get("losses"):
                lines.append("**Последние потери:**")
                for loss in activity["losses"][:2]:
                    value = loss.get("value", 0)
                    val_str = f"{value/1e9:.2f}B" if value >= 1e9 else f"{value/1e6:.1f}M"
                    lines.append(f"  • {loss['ship']} | {val_str} ISK | {loss['system']}")
            
            lines.append("---")
        
        return "\n".join(lines)
    
    def get_stats(self) -> Dict:
        """
        Возвращает статистику работы модуля
        """
        return {
            **self.stats,
            "cache_size": sum(len(v) for v in self.cache.values())
        }


# Создаём глобальный экземпляр
_character_analyzer = CharacterAnalyzer()

def get_character_analyzer():
    """Возвращает глобальный экземпляр CharacterAnalyzer"""
    return _character_analyzer