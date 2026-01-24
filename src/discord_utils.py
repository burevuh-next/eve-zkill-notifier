import discord
from discord.ext import commands
import aiohttp
import logging
import os
import json
from datetime import datetime
from dotenv import set_key

class EveBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.name_cache = {}
        self.session = None
        self.config_updated = False 

    async def setup_hook(self):
        logging.info("--- ⚙️ ИНИЦИАЛИЗАЦИЯ БОТА ---")
        self.session = aiohttp.ClientSession()
        
        # Автоматическая регистрация всех глобальных команд
        for cmd in [ping, check, status, add_to_watch, remove_from_watch]:
            if not self.get_command(cmd.name):
                self.add_command(cmd)
            
        logging.info(f"✅ Команды загружены: {[c.name for c in self.commands]}")

    async def get_eve_names(self, ids):
        # Очистка и дедупликация
        clean_ids = list(set([int(i) for i in ids if i and str(i).isdigit()]))
        if not clean_ids: return {}
        
        result = {}
        to_fetch = [i for i in clean_ids if i not in self.name_cache]
        
        if to_fetch:
            url = "https://esi.evetech.net/latest/universe/names/"
            try:
                async with self.session.post(url, json=to_fetch, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data:
                            self.name_cache[item['id']] = item['name']
                    elif resp.status == 404:
                        # ДОЖИМАЕМ: Если вся пачка дала 404, проверяем по одному
                        logging.warning(f"⚠️ Пачка ID содержит некорректные данные. Резолвим поштучно...")
                        for single_id in to_fetch:
                            async with self.session.post(url, json=[single_id]) as s_resp:
                                if s_resp.status == 200:
                                    s_data = await s_resp.json()
                                    self.name_cache[single_id] = s_data[0]['name']
                                else:
                                    self.name_cache[single_id] = f"ID: {single_id}"
                    else:
                        logging.error(f"❌ ESI ошибка: {resp.status}")
            except Exception as e:
                logging.error(f"❌ Ошибка сети с ESI: {e}")
        
        # Заполняем результат из кэша
        for i in clean_ids:
            result[i] = self.name_cache.get(i, f"ID: {i}")
        return result

    def format_isk(self, value):
        """Красивое форматирование валюты"""
        if value >= 1_000_000_000: return f"{value / 1_000_000_000:.2f}B"
        if value >= 1_000_000: return f"{value / 1_000_000:.2f}M"
        return f"{value:,.0f}"

    def get_discord_timestamp(self, esi_time_str):
        """Преобразование времени ESI в динамический формат Discord"""
        try:
            dt = datetime.fromisoformat(esi_time_str.replace('Z', '+00:00'))
            return f"<t:{int(dt.timestamp())}:t>"
        except: return "00:00"

    async def send_kill_notification(self, channel_id, killmail, event_type):
        """Основная функция отправки уведомлений о киллах с исправленным пингом"""
        channel = self.get_channel(int(channel_id))
        if not channel: return

        # Чтение фильтров и СТРОГАЯ очистка от пробелов
        ping_systems = [s.strip() for s in os.getenv("PING_SYSTEM_IDS", "").split(",") if s.strip()]
        ping_ships = [s.strip() for s in os.getenv("PING_SHIP_IDS", "").split(",") if s.strip()]
        
        # Получаем ID и приводим к строке для надежного сравнения
        sys_id = str(killmail.get('solar_system_id', ''))
        victim = killmail.get('victim', {})
        ship_id = str(victim.get('ship_type_id', ''))
        
        content_prefix = ""
        # Проверяем наличие в списках приоритетов
        if sys_id in ping_systems or ship_id in ping_ships:
            content_prefix = "@everyone 🚨 **ОБНАРУЖЕНА ПРИОРИТЕТНАЯ ЦЕЛЬ!**"
            logging.info(f"🔔 Сработал приоритетный пинг: System:{sys_id}, Ship:{ship_id}")

        zkb = killmail.get('zkb', {})
        value = zkb.get('totalValue', 0)
        attacker = next((a for a in killmail.get('attackers', []) if a.get('final_blow')), {})
        
        # Резолвим имена
        ids_to_fetch = [sys_id, ship_id, victim.get('character_id'), victim.get('corporation_id'),
                        attacker.get('character_id'), attacker.get('corporation_id'), attacker.get('ship_type_id')]
        names = await self.get_eve_names(ids_to_fetch)

        v_name = names.get(victim.get('character_id'), "Unknown")
        v_ship = names.get(int(ship_id), "Unknown Ship")
        system_name = names.get(int(sys_id), "Unknown System")
        time_ts = self.get_discord_timestamp(killmail.get('killmail_time', ''))

        color = discord.Color.green() if "KILL" in event_type else discord.Color.red()
        
        embed = discord.Embed(
            title=f"💥 {v_ship} | {system_name}",
            description=f"### 💰 Стоимость: **{self.format_isk(value)} ISK**\n🔗 [zKillboard](https://zkillboard.com/kill/{killmail.get('killmail_id')}/)",
            color=color, timestamp=datetime.utcnow()
        )
        
        embed.set_thumbnail(url=f"https://images.evetech.net/types/{ship_id}/render?size=128")
        embed.add_field(name="👤 Жертва", value=f"**{v_name}**\n{names.get(victim.get('corporation_id'), 'Unknown Corp')}", inline=True)
        embed.add_field(name="⚔️ Убийца", value=f"**{names.get(attacker.get('character_id'), 'NPC')}**\n{names.get(attacker.get('corporation_id'), 'No Corp')}", inline=True)
        embed.set_footer(text=f"KillID: {killmail.get('killmail_id')} | {event_type}")

        await channel.send(content=f"{content_prefix}\n✅ **{time_ts}** | **{v_name}** | **{system_name}**", embed=embed)

# --- КОМАНДЫ ---

def save_to_env(key, value):
    set_key(".env", key, value)

@commands.command(name="add")
async def add_to_watch(ctx, category: str, item_id: str):
    mapping = {
        "system": "WATCHED_SYSTEM_IDS", "region": "WATCHED_REGIONS_IDS",
        "ship": "WATCHED_SHIP_IDS", "corp": "MY_CORP_IDS",
        "char": "WATCHED_CHAR_IDS", "consts": "WATCHED_CONSTELLATION_IDS",
        "ping_sys": "PING_SYSTEM_IDS", "ping_ship": "PING_SHIP_IDS"
    }

    cat = category.lower()
    if cat not in mapping:
        await ctx.send(f"❌ Доступные категории: `{', '.join(mapping.keys())}`")
        return

    var_name = mapping[cat]
    current_ids = [i.strip() for i in os.getenv(var_name, "").split(',') if i.strip()]
    
    if item_id in current_ids:
        await ctx.send("⚠️ Этот ID уже есть в списке.")
        return

    current_ids.append(item_id)
    new_val = ",".join(current_ids)
    os.environ[var_name] = new_val
    save_to_env(var_name, new_val)
    
    bot.config_updated = True 
    res = await bot.get_eve_names([int(item_id)])
    name = res.get(int(item_id), item_id)
    await ctx.send(f"✅ **{name}** успешно добавлен в `{cat}`. Потоки zKillboard перезапускаются... 🔄")

@commands.command(name="remove")
async def remove_from_watch(ctx, category: str, item_id: str):
    mapping = {
        "system": "WATCHED_SYSTEM_IDS", "region": "WATCHED_REGIONS_IDS",
        "ship": "WATCHED_SHIP_IDS", "corp": "MY_CORP_IDS",
        "char": "WATCHED_CHAR_IDS", "consts": "WATCHED_CONSTELLATION_IDS",
        "ping_sys": "PING_SYSTEM_IDS", "ping_ship": "PING_SHIP_IDS"
    }

    cat = category.lower()
    if cat not in mapping:
        await ctx.send("❌ Неверная категория.")
        return

    var_name = mapping[cat]
    current_ids = [i.strip() for i in os.getenv(var_name, "").split(',') if i.strip()]

    if item_id not in current_ids:
        await ctx.send("❌ ID не найден в этом списке.")
        return

    current_ids.remove(item_id)
    new_val = ",".join(current_ids)
    os.environ[var_name] = new_val
    save_to_env(var_name, new_val)
    
    bot.config_updated = True 
    await ctx.send(f"🗑️ ID `{item_id}` удален. Конфигурация обновлена! 💾")

@commands.command(name="status")
async def status(ctx):
    # Полный список всех категорий, которые мы отслеживаем
    env_vars = {
        "👤 Капсулеры [char]": "WATCHED_CHAR_IDS",
        "🏢 Корпорации [corp]": "MY_CORP_IDS",
        "🌌 Системы [system]": "WATCHED_SYSTEM_IDS",
        "🗺️ Регионы [region]": "WATCHED_REGIONS_IDS",
        "🚀 Корабли [ship]": "WATCHED_SHIP_IDS",
        "🌌 Созвездия [consts]": "WATCHED_CONSTELLATION_IDS",
        "🚨 Приоритетные Системы [ping_sys]": "PING_SYSTEM_IDS",
        "🚨 Приоритетные Корабли [ping_ship]": "PING_SHIP_IDS"
    }
    
    # 1. Собираем ВСЕ ID из ВСЕХ переменных окружения в один список
    all_ids_to_resolve = []
    for var_name in env_vars.values():
        val = os.getenv(var_name, "")
        if val:
            # Превращаем строку "ID,ID,ID" в список чисел, игнорируя мусор
            ids = [int(i.strip()) for i in val.split(',') if i.strip().isdigit()]
            all_ids_to_resolve.extend(ids)
    
    # 2. Делаем один запрос к ESI для получения всех имен сразу (быстро и эффективно)
    names_map = await bot.get_eve_names(all_ids_to_resolve)
    
    embed = discord.Embed(
        title="📊 Мониторинг zKillboard", 
        color=discord.Color.blue(), 
        timestamp=datetime.utcnow()
    )

    # 3. Строим поля Embed
    for label, var_name in env_vars.items():
        raw_ids = os.getenv(var_name, "")
        if not raw_ids:
            # Скрываем пустые ПИНГ-поля, чтобы не спамить, остальные показываем как "Пусто"
            if "ПИНГ" not in label:
                embed.add_field(name=label, value="`Не задано`", inline=False)
            continue
        
        ids = [int(i.strip()) for i in raw_ids.split(',') if i.strip().isdigit()]
        
        # Формируем красиво: Имя [ID]
        lines = []
        for i in ids:
            name = names_map.get(i, f"ID: {i}")
            lines.append(f"{name} [{i}]")
        
        content = "\n".join(lines)
        # Защита от слишком длинных списков (Discord limit 1024)
        if len(content) > 1000:
            content = content[:997] + "..."
            
        embed.add_field(name=label, value=f"```text\n{content}```", inline=False)

    # 4. Добавляем порог ISK
    min_val = os.getenv("MIN_VALUE", "0")
    try:
        val_formatted = f"{float(min_val):,.0f} ISK"
    except:
        val_formatted = "1 ISK"
        
    embed.add_field(name="💰 Порог", value=f"**{val_formatted}**")
    
    await ctx.send(embed=embed)

@commands.command(name="ping")
async def ping(ctx):
    await ctx.send(f"o7 {ctx.author.mention}! Бот на связи и готов к охоте. 📡")

@commands.command(name="check")
async def check(ctx, target_id: str):
    if not target_id.isdigit():
        await ctx.send("❌ Ошибка: введите числовой ID.")
        return
    res = await bot.get_eve_names([int(target_id)])
    await ctx.send(f"🔍 Результат для ID `{target_id}`: **{res.get(int(target_id), 'Не найдено')}**")

bot = EveBot()