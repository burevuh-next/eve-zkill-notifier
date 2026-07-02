import discord
from discord.ext import commands
import aiohttp
import asyncio
import logging
import os
import json
import io
import sys
from datetime import datetime
from character_analyzer import get_character_analyzer


SUBS_FILE = "subscriptions.json"

def load_subs():
    if os.path.exists(SUBS_FILE):
        with open(SUBS_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except:
                return {}
    return {}

def save_subs(subs):
    with open(SUBS_FILE, "w", encoding="utf-8") as f:
        json.dump(subs, f, indent=4, ensure_ascii=False)

try:
    from image_generator_large import get_generator
    IMAGE_GENERATION_ENABLED = True
except ImportError:
    IMAGE_GENERATION_ENABLED = False
    logging.warning("⚠️ Image generator not found!")

try:
    from monitoring import monitor
    MONITORING_ENABLED = True
except ImportError:
    MONITORING_ENABLED = False
    logging.warning("⚠️ Monitoring module not found!")

class EveBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.name_cache = {}
        self.session = None
        self.config_updated = False 

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()

    async def on_ready(self):
        flag_file = "restart.flag"
        if os.path.exists(flag_file):
            try:
                with open(flag_file) as f:
                    data = json.load(f)
                channel = self.get_channel(data["channel_id"])
                if channel:
                    embed = discord.Embed(
                        title="🔄 Бот перезапущен",
                        color=discord.Color.green(),
                        timestamp=datetime.utcnow()
                    )
                    embed.set_footer(text="EVE KillBot")
                    await channel.send(embed=embed)
            except Exception as e:
                logging.error(f"Restart flag error: {e}")
            finally:
                os.remove(flag_file)
        logging.info(f"✅ Bot logged in as {self.user}")

    async def get_eve_names(self, ids):
        clean_ids = list(set([int(i) for i in ids if i and str(i).isdigit()]))
        if not clean_ids: 
            return {}
        
        to_fetch = [i for i in clean_ids if i not in self.name_cache]
        
        if to_fetch:
            url = "https://esi.evetech.net/latest/universe/names/"
            try:
                async with self.session.post(url, json=to_fetch) as resp:
                    if resp.status == 200:
                        for item in await resp.json():
                            self.name_cache[item['id']] = item['name']
                    else:
                        logging.warning(f"⚠️ ESI names API вернул статус {resp.status}")
            except Exception as e:
                logging.error(f"❌ Ошибка при получении имен: {e}")
        
        return {i: self.name_cache.get(i, f"ID:{i}") for i in clean_ids}

    def format_isk(self, value):
        if value >= 1e9: 
            return f"{value/1e9:.2f}B"
        if value >= 1e6: 
            return f"{value/1e6:.1f}M"
        return f"{value:,.0f}"

    def get_discord_timestamp(self, esi_time_str):
        try:
            dt = datetime.fromisoformat(esi_time_str.replace('Z', '+00:00'))
            return f"<t:{int(dt.timestamp())}:t>"
        except: 
            return "00:00"

    async def send_kill_notification(self, channel_id, killmail, event_type):
        channel = self.get_channel(int(channel_id))
        if not channel:
            logging.warning(f"⚠️ Channel {channel_id} not found")
            return

        zkb = killmail.get('zkb', {})
        value = zkb.get('totalValue', 0)
        k_id = killmail.get('killmail_id', 0)
        victim = killmail.get('victim', {})
        attackers = killmail.get('attackers', [])
        attacker = next((a for a in attackers if a.get('final_blow')), attackers[0] if attackers else {})

        ids = [
            killmail.get('solar_system_id'), 
            victim.get('ship_type_id'), 
            victim.get('character_id'), 
            attacker.get('character_id'),
            victim.get('corporation_id'), 
            attacker.get('corporation_id'),
            attacker.get('ship_type_id')
        ]
        names = await self.get_eve_names(ids)

        v_name = names.get(victim.get('character_id'), "Unknown")
        sys_name = names.get(killmail.get('solar_system_id'), "Unknown")
        time_ts = self.get_discord_timestamp(killmail.get('killmail_time', ''))
        
        # КЛЮЧЕВОЙ МОМЕНТ: ссылка обернута в <>, чтобы Discord не создавал превью
        zkill_url = f"<https://zkillboard.com/kill/{k_id}/>"
        
        # Контент сообщения
        if event_type == "PRIORITY_TARGET":
            content = (
                f"@everyone **PRIORITY TARGET!**\n"
                f"**{self.format_isk(value)} ISK** | {sys_name} | **{v_name}** | {time_ts}\n"
                f"{zkill_url}"
            )
        elif value >= 1_000_000_000:
            content = f"**BILLION KILL** | **{self.format_isk(value)} ISK** | {sys_name} | **{v_name}** | {time_ts}\n{zkill_url}"
        elif value >= 500_000_000:
            content = f"**EXPENSIVE KILL** | **{self.format_isk(value)} ISK** | {sys_name} | **{v_name}** | {time_ts}\n{zkill_url}"
        elif "KILL" in event_type:
            content = f"**FRIENDLY KILL** | **{self.format_isk(value)} ISK** | {sys_name} | **{v_name}** | {time_ts}\n{zkill_url}"
        else:
            content = f"**LOSS** | **{self.format_isk(value)} ISK** | {sys_name} | **{v_name}** | {time_ts}\n{zkill_url}"

        # ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЯ
        image_sent = False
        
        if IMAGE_GENERATION_ENABLED:
            try:
                generator = get_generator()
                path = await generator.generate_killmail_image(self.session, killmail, names, event_type)
                
                if path and os.path.exists(path):
                    file = discord.File(path, filename=f"kill_{k_id}.png")
                    await channel.send(content=content, file=file)
                    logging.info(f"✅ Kill notification sent to {channel_id} with image")
                    image_sent = True
                    
            except Exception as e:
                logging.error(f"❌ Image generation error: {e}")
        
        # FALLBACK: если изображение не отправлено
        if not image_sent:
            ship_name = names.get(int(victim.get('ship_type_id', 0)), "Unknown Ship")
            a_ship = names.get(attacker.get('ship_type_id'), "Unknown")
            
            color = discord.Color.gold() if event_type == "PRIORITY_TARGET" else (discord.Color.green() if "KILL" in event_type else discord.Color.red())
            
            embed = discord.Embed(
                title=f"{ship_name} destroyed",
                description=f"**{self.format_isk(value)} ISK**\n[zKillboard]({zkill_url})",
                color=color, 
                timestamp=datetime.utcnow()
            )
            embed.set_thumbnail(url=f"https://images.evetech.net/types/{victim.get('ship_type_id', 0)}/render?size=128")
            embed.add_field(name="Victim", value=f"**{v_name}**\n{names.get(victim.get('corporation_id'), 'Unknown')}", inline=True)
            embed.add_field(name="Killer", value=f"**{names.get(attacker.get('character_id'), 'NPC')}**\n{a_ship}", inline=True)
            embed.set_footer(text=f"KillID: {k_id}")
            
            await channel.send(content=content, embed=embed)
            logging.info(f"✅ Kill notification sent to {channel_id} with embed")

bot = EveBot()

@commands.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(title="EVE KillBot Help", color=discord.Color.green())
    embed.add_field(name="Setup", value="`!init` — инициализация канала\n`!min [value]` — мин. цена (напр. 50000000)\n`!status` — фильтры канала", inline=False)
    embed.add_field(name="Фильтры", value="`!add [type] [ID]` — добавить фильтр\n`!remove [type] [ID]` — удалить\nTypes: `system`, `region`, `const`, `ship`, `corp`, `char`, `ping_sys`, `ping_ship`", inline=False)
    embed.add_field(name="Массовое", value="`!addmulti [type] [ID1 ID2 ...]` — добавить список ID (через пробел или запятую)", inline=False)
    embed.add_field(name="Анализ", value="`!analyze <name>` / `!a` / `!who` — текстовый анализ\n`!analyzeimg <name>` / `!ai` / `!whoimg` — с картинкой\n`!analyze_stats` / `!stats` — статистика аналитика", inline=False)
    embed.add_field(name="Поиск", value="`!search <запрос>` — поиск по имени/ID", inline=False)
    embed.add_field(name="Управление", value="`!export` — экспорт фильтров в JSON\n`!import` <JSON> — импорт фильтров\n`!clearcache` — очистить кэш имён\n`!restart` — перезагрузка бота (только админ)", inline=False)
    embed.add_field(name="Мониторинг", value="`!monitor` — статистика ресурсов\n`!imgstats` — статистика изображений\n`!imgclean` — очистка старых изображений\n`!ping` — пинг\n`!check` — проверка соединений", inline=False)
    await ctx.send(embed=embed)

@commands.command(name="init")
@commands.has_permissions(manage_channels=True)
async def init_channel(ctx):
    subs = load_subs()
    ch_id = str(ctx.channel.id)
    if ch_id not in subs:
        subs[ch_id] = {
            "corps": [], "systems": [], "regions": [], 
            "ships": [], "chars": [], "consts": [], 
            "alliances": [], "ping_sys": [], "ping_ship": [], 
            "min_value": 1000000
        }
        save_subs(subs)
        bot.config_updated = True
        await ctx.send(f"✅ Channel {ctx.channel.mention} initialized!")

@commands.command(name="min")
@commands.has_permissions(manage_messages=True)
async def set_min_value(ctx, value: float):
    subs = load_subs()
    ch_id = str(ctx.channel.id)
    if ch_id in subs:
        subs[ch_id]["min_value"] = value
        save_subs(subs)
        bot.config_updated = True
        await ctx.send(f"💰 Threshold: **{bot.format_isk(value)} ISK**")

@commands.command(name="add")
@commands.has_permissions(manage_messages=True)
async def add_to_watch(ctx, category: str, item_id: int):
    subs = load_subs()
    ch_id = str(ctx.channel.id)
    if ch_id not in subs: 
        return await ctx.send("❌ Use `!init` first.")
    
    mapping = {
        "system": "systems", "region": "regions", "ship": "ships", 
        "corp": "corps", "char": "chars", "const": "consts", 
        "alliance": "alliances", "ping_sys": "ping_sys", "ping_ship": "ping_ship"
    }
    
    cat = category.lower()
    if cat not in mapping: 
        return await ctx.send("❌ Invalid type. Use: system, region, const, ship, corp, char, alliance, ping_sys, ping_ship")
    
    key = mapping[cat]
    if item_id not in subs[ch_id][key]:
        subs[ch_id][key].append(item_id)
        save_subs(subs)
        bot.config_updated = True
        res = await bot.get_eve_names([item_id])
        await ctx.send(f"✅ **{res.get(item_id, item_id)}** added to {cat}")

@commands.command(name="remove")
@commands.has_permissions(manage_messages=True)
async def remove_from_watch(ctx, category: str, item_id: int):
    subs = load_subs()
    ch_id = str(ctx.channel.id)
    
    mapping = {
        "system": "systems", "region": "regions", "ship": "ships", 
        "corp": "corps", "char": "chars", "const": "consts", 
        "ping_sys": "ping_sys", "ping_ship": "ping_ship"
    }
    
    key = mapping.get(category.lower())
    if ch_id in subs and key and item_id in subs[ch_id][key]:
        subs[ch_id][key].remove(item_id)
        save_subs(subs)
        bot.config_updated = True
        await ctx.send(f"✅ ID `{item_id}` removed from {category}")

@commands.command(name="status")
async def status(ctx):
    """Показывает полный список отслеживаемых параметров в канале"""
    subs = load_subs()
    ch_id = str(ctx.channel.id)
    
    if ch_id not in subs: 
        return await ctx.send("❌ Use `!init` first.")
    
    ch_data = subs[ch_id]
    
    # Собираем все ID для получения имен
    all_ids = []
    for k in ["ships","systems","regions","consts","corps","chars","ping_sys","ping_ship"]:
        all_ids.extend(ch_data.get(k, []))
    
    names = await bot.get_eve_names(all_ids)
    
    embed = discord.Embed(
        title=f"📊 Channel Status - {ctx.channel.name}", 
        color=discord.Color.blue(), 
        timestamp=datetime.utcnow()
    )
    
    categories = [
        ("ping_sys", "🔔 **Priority Systems**", "⚡"),
        ("ping_ship", "🔔 **Priority Ships**", "🚀"),
        ("systems", "🪐 **Systems**", "🌍"),
        ("regions", "🌌 **Regions**", "🗺️"),
        ("consts", "⚡ **Constellations**", "✨"),
        ("ships", "🚀 **Ships**", "⚓"),
        ("corps", "🏢 **Corporations**", "🏛️"),
        ("chars", "👤 **Characters**", "🧑")
    ]
    
    has_any = False
    
    for key, label, emoji in categories:
        ids = ch_data.get(key, [])
        if ids:
            has_any = True
            # Формируем список ВСЕХ элементов
            items = []
            for item_id in ids:
                name = names.get(item_id, f"Unknown [{item_id}]")
                items.append(f"• {name}")
            
            # Объединяем в текст
            items_text = "\n".join(items)
            
            # Discord имеет лимит 1024 символа на поле
            if len(items_text) <= 1024:
                embed.add_field(name=f"{emoji} {label}", value=items_text, inline=False)
            else:
                # Если слишком длинно, разбиваем на несколько полей
                chunks = [items[i:i+15] for i in range(0, len(items), 15)]
                for i, chunk in enumerate(chunks):
                    chunk_text = "\n".join(chunk)
                    field_name = f"{emoji} {label} (part {i+1}/{len(chunks)})"
                    embed.add_field(name=field_name, value=chunk_text, inline=False)
    
    if not has_any:
        embed.add_field(
            name="📭 No active filters",
            value="Add filters using:\n`!add system <ID>`\n`!add ship <ID>`\n`!add corp <ID>`\netc.",
            inline=False
        )
    
    # Добавляем информацию о минимальной стоимости
    min_value = ch_data.get('min_value', 1_000_000)
    embed.add_field(
        name="💰 Threshold",
        value=f"**{bot.format_isk(min_value)} ISK**",
        inline=False
    )
    
    # Добавляем статистику
    total_filters = sum(len(ch_data.get(k, [])) for k in ["ships","systems","regions","consts","corps","chars","ping_sys","ping_ship"])
    embed.set_footer(text=f"Total filters: {total_filters} • Channel ID: {ch_id}")
    
    await ctx.send(embed=embed)

@commands.command(name="monitor")
async def monitor_stats(ctx):
    """Показывает статистику мониторинга"""
    if not MONITORING_ENABLED:
        await ctx.send("📊 Мониторинг ресурсов отключен или модуль не загружен")
        return
    
    stats = monitor.get_stats()
    
    if not stats['enabled']:
        await ctx.send("📊 Мониторинг ресурсов отключен в конфигурации")
        return
    
    embed = discord.Embed(
        title="📊 Мониторинг ресурсов",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    
    embed.add_field(name="⏱ Время работы", value=stats['uptime'], inline=True)
    embed.add_field(name="✅ Проверок", value=stats['check_count'], inline=True)
    embed.add_field(name="🔌 Пик соединений", value=stats['connections_peak'], inline=True)
    
    embed.add_field(name="💾 Память (тек/пик)", value=f"{stats['memory_current_mb']} / {stats['memory_peak_mb']} МБ", inline=True)
    embed.add_field(name="⚡ CPU (тек/пик)", value=f"{stats['cpu_current_percent']} / {stats['cpu_peak_percent']}%", inline=True)
    embed.add_field(name="💽 Диск (проект)", value=f"{stats['disk_usage_mb']} МБ", inline=True)
    
    if stats['warnings']:
        warnings_text = "\n".join(stats['warnings'][-5:])
        embed.add_field(name="⚠️ Последние предупреждения", value=f"```{warnings_text}```", inline=False)
    
    await ctx.send(embed=embed)

@commands.command(name="ping")
async def ping(ctx):
    await ctx.send(f"o7 {ctx.author.mention}!")

@commands.command(name="check")
async def check(ctx, target_id: int = None):
    if target_id:
        res = await bot.get_eve_names([target_id])
        await ctx.send(f"ID `{target_id}` -> **{res.get(target_id, 'Not found')}**")
    else:
        await ctx.send("✅ Бот работает, всё в порядке. Использование: `!check <ID>`")

@commands.command(name="restart")
@commands.has_permissions(administrator=True)
async def restart_bot(ctx):
    """Перезагружает бота"""
    with open("restart.flag", "w") as f:
        json.dump({"channel_id": ctx.channel.id}, f)
    await ctx.send("🔄 Перезагрузка бота...")
    await asyncio.sleep(1)
    logging.info("🔄 Restarting bot via !restart command")
    os.execv(sys.executable, [sys.executable] + sys.argv)

@commands.command(name="imgstats")
async def image_stats(ctx):
    """Показывает статистику генератора изображений"""
    if not IMAGE_GENERATION_ENABLED:
        await ctx.send("❌ Генератор изображений отключен")
        return
    
    generator = get_generator()
    stats = generator.get_stats()
    
    embed = discord.Embed(
        title="🖼️ Статистика генератора изображений",
        color=discord.Color.purple(),
        timestamp=datetime.utcnow()
    )
    
    embed.add_field(name="✅ Сгенерировано", value=stats["images_generated"], inline=True)
    embed.add_field(name="⏱️ Среднее время", value=f"{stats['avg_generation_time']}с", inline=True)
    embed.add_field(name="💾 В кеше", value=stats["cache_hits"], inline=True)
    
    embed.add_field(name="📊 Hit ratio", value=f"{stats['cache_hit_ratio']}%", inline=True)
    embed.add_field(name="📁 Файлов сейчас", value=stats["current_files"], inline=True)
    embed.add_field(name="💽 Занято", value=f"{stats['current_size_mb']} МБ", inline=True)
    
    embed.add_field(name="🧹 Очищено файлов", value=stats["images_cleaned"], inline=True)
    embed.add_field(name="🗑️ Освобождено", value=f"{stats['disk_space_freed_mb']} МБ", inline=True)
    embed.add_field(name="⏰ TTL", value=f"{stats['ttl_hours']}ч", inline=True)
    
    # Прогресс-бар заполнения диска
    if stats['max_files'] > 0:
        usage_percent = (stats['current_files'] / stats['max_files']) * 100
        bar_length = 10
        filled = int(bar_length * usage_percent / 100)
        bar = '█' * filled + '░' * (bar_length - filled)
        embed.add_field(
            name="📊 Использование лимита", 
            value=f"`{bar}` {stats['current_files']}/{stats['max_files']} ({usage_percent:.1f}%)",
            inline=False
        )
    
    await ctx.send(embed=embed)

@commands.command(name="imgclean")
@commands.has_permissions(manage_messages=True)
async def image_clean(ctx):
    """Ручная очистка старых изображений"""
    if not IMAGE_GENERATION_ENABLED:
        await ctx.send("❌ Генератор изображений отключен")
        return
    
    msg = await ctx.send("🧹 Очищаю старые изображения...")
    
    generator = get_generator()
    freed_space, cleaned_count = await generator._cleanup_old_images()
    
    if cleaned_count > 0:
        await msg.edit(content=f"✅ Очищено {cleaned_count} изображений, освобождено {freed_space:.1f} МБ")
    else:
        await msg.edit(content="✅ Старых изображений не найдено")

@commands.command(name="analyze", aliases=["a", "who"])
async def analyze_characters(ctx, *, names_text: str = None):
    """
    Анализирует список персонажей из локала
    Пример: !analyze <скопированные имена из локала>
    """
    if not names_text:
        await ctx.send("❌ Укажите имена для анализа. Скопируйте их из локала и отправьте командой.\nПример: `!analyze` и вставьте список")
        return
    
    # Сообщение о начале анализа
    msg = await ctx.send(f"🔍 Анализирую {len(names_text.splitlines())} персонажей... Это может занять некоторое время.")
    
    try:
        analyzer = get_character_analyzer()
        await analyzer.ensure_session()
        
        results = await analyzer.analyze_characters(names_text)
        
        if not results:
            await msg.edit(content="❌ Не удалось найти ни одного персонажа. Проверьте имена и попробуйте снова.")
            return
        
        # Форматируем результат
        formatted = analyzer.format_for_discord(results)
        
        # Discord имеет лимит 2000 символов, разбиваем если нужно
        if len(formatted) > 1900:
            parts = [formatted[i:i+1900] for i in range(0, len(formatted), 1900)]
            await msg.edit(content=parts[0])
            for part in parts[1:]:
                await ctx.send(part)
        else:
            await msg.edit(content=formatted)
        
        # Показываем статистику
        stats = analyzer.get_stats()
        await ctx.send(f"📊 Статистика: проанализировано {stats['analyzed_characters']} персонажей, "
                      f"запросов к zKillboard: {stats['zkill_requests']}")
    
    except Exception as e:
        await msg.edit(content=f"❌ Ошибка при анализе: {str(e)}")
        logging.error(f"Ошибка в analyze_characters: {e}", exc_info=True)
    finally:
        # Закрываем сессию
        analyzer = get_character_analyzer()
        await analyzer.close_session()

@commands.command(name="analyzeimg", aliases=["ai", "whoimg"])
async def analyze_characters_image(ctx, *, names_text: str = None):
    """
    Анализирует персонажей и отправляет результат в виде изображения
    Пример: !analyzeimg <скопированные имена из локала>
    """
    if not names_text:
        await ctx.send("❌ Укажите имена для анализа.\nПример: `!analyzeimg` и вставьте список")
        return

    msg = await ctx.send(f"🖼️ Анализирую и генерирую изображения для {len(names_text.splitlines())} персонажей...")

    try:
        analyzer = get_character_analyzer()
        await analyzer.ensure_session()

        results = await analyzer.analyze_characters(names_text)

        if not results:
            await msg.edit(content="❌ Не удалось найти ни одного персонажа.")
            return

        if not IMAGE_GENERATION_ENABLED:
            await msg.edit(content="❌ Генератор изображений отключен")
            return

        generator = get_generator()

        for result in results:
            char_data = {
                "id": result["id"],
                "name": result["name"],
                "corporation": result["corporation"],
                "corporation_id": result.get("corporation_id", 0),
                "alliance": result["alliance"],
                "security_status": result["security_status"],
                "activity": result["activity"],
            }

            await msg.edit(content=f"🖼️ Генерирую изображение для {result['name']}...")

            image_path = await generator.generate_character_analysis_image(
                bot.session, char_data, result.get("ship_names", {})
            )

            if image_path and os.path.exists(image_path):
                file = discord.File(image_path, filename=f"analysis_{result['id']}.png")
                await ctx.send(file=file)
            else:
                await ctx.send(f"❌ Не удалось сгенерировать изображение для {result['name']}")

        await msg.edit(content=f"✅ Анализ завершен. Обработано {len(results)} персонажей.")

    except Exception as e:
        await msg.edit(content=f"❌ Ошибка при анализе: {str(e)}")
        logging.error(f"Ошибка в analyze_characters_image: {e}", exc_info=True)
    finally:
        analyzer = get_character_analyzer()
        await analyzer.close_session()

@commands.command(name="analyze_stats")
async def analyzer_stats(ctx):
    """Показывает статистику работы анализатора"""
    analyzer = get_character_analyzer()
    stats = analyzer.get_stats()
    
    embed = discord.Embed(
        title="📊 Статистика Character Analyzer",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    
    embed.add_field(name="👤 Проанализировано", value=stats["analyzed_characters"], inline=True)
    embed.add_field(name="📡 Запросов к zKill", value=stats["zkill_requests"], inline=True)
    embed.add_field(name="❌ Ошибок API", value=stats["api_errors"], inline=True)
    embed.add_field(name="💾 Кеш-хитов", value=stats["cache_hits"], inline=True)
    embed.add_field(name="📁 Размер кеша", value=stats["cache_size"], inline=True)
    
    await ctx.send(embed=embed)

@commands.command(name="stats")
async def stats_command(ctx):
    """Показывает статистику работы бота"""
    from processor import get_processor_stats

    p_stats = get_processor_stats()
    subs = load_subs()

    embed = discord.Embed(
        title="📊 Bot Statistics",
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )

    embed.add_field(name="✅ Processed", value=p_stats["processed_total"], inline=True)
    embed.add_field(name="📨 Notifications", value=p_stats["notifications_sent"], inline=True)
    embed.add_field(name="⏭️ Duplicates", value=p_stats["duplicates_skipped"], inline=True)
    embed.add_field(name="❌ Errors", value=p_stats["errors"], inline=True)
    embed.add_field(name="📁 Active channels", value=len(subs), inline=True)
    embed.add_field(name="💾 Name cache", value=len(bot.name_cache), inline=True)

    await ctx.send(embed=embed)

@commands.command(name="search")
async def search_command(ctx, *, query: str):
    """Ищет ID систем, персонажей, корпораций, кораблей по названию через ESI"""
    if not query.strip():
        await ctx.send("❌ Укажите текст для поиска.")
        return

    msg = await ctx.send(f"🔍 Searching for `{query}`...")

    try:
        url = "https://esi.evetech.net/latest/universe/ids/"
        async with bot.session.post(url, json=[query.strip()]) as resp:
            if resp.status != 200:
                await msg.edit(content=f"❌ ESI вернул статус {resp.status}")
                return
            data = await resp.json()

    except Exception as e:
        await msg.edit(content=f"❌ Ошибка запроса: {e}")
        return

    embed = discord.Embed(title=f"🔍 Search: {query}", color=discord.Color.blue())

    has_results = False
    categories = [
        ("characters", "👤 Characters"),
        ("corporations", "🏢 Corporations"),
        ("alliances", "🌐 Alliances"),
        ("systems", "🪐 Systems"),
        ("constellations", "✨ Constellations"),
        ("regions", "🌌 Regions"),
        ("types", "🚀 Types (ships/items)"),
    ]

    for key, label in categories:
        items = data.get(key, [])
        if items:
            has_results = True
            lines = [f"• **{item.get('name', '?')}** — ID: `{item.get('id', '?')}`" for item in items[:10]]
            embed.add_field(name=label, value="\n".join(lines), inline=False)

    if not has_results:
        await msg.edit(content=f"❌ Ничего не найдено для `{query}`.")
        return

    embed.set_footer(text="Use !add <type> <ID> to add filters")
    await msg.edit(content=None, embed=embed)

@commands.command(name="addmulti")
@commands.has_permissions(manage_messages=True)
async def add_multi(ctx, category: str, *, ids: str):
    """Массовое добавление ID в фильтр. Пример: !addmulti system 30000142 30002187"""
    subs = load_subs()
    ch_id = str(ctx.channel.id)
    if ch_id not in subs:
        return await ctx.send("❌ Use `!init` first.")

    mapping = {
        "system": "systems", "region": "regions", "ship": "ships",
        "corp": "corps", "char": "chars", "const": "consts",
        "alliance": "alliances", "ping_sys": "ping_sys", "ping_ship": "ping_ship"
    }

    cat = category.lower()
    if cat not in mapping:
        return await ctx.send("❌ Invalid type. Use: system, region, const, ship, corp, char, alliance, ping_sys, ping_ship")

    item_ids = []
    for part in ids.replace(",", " ").split():
        try:
            item_ids.append(int(part))
        except ValueError:
            await ctx.send(f"❌ Invalid ID: `{part}`")
            return

    key = mapping[cat]
    added = 0
    for item_id in item_ids:
        if item_id not in subs[ch_id][key]:
            subs[ch_id][key].append(item_id)
            added += 1

    if added > 0:
        save_subs(subs)
        bot.config_updated = True

    res = await bot.get_eve_names(item_ids)
    names_str = ", ".join(res.get(i, f"ID:{i}") for i in item_ids)
    await ctx.send(f"✅ Added {added}/{len(item_ids)} to {cat}: {names_str}")

@commands.command(name="export")
@commands.has_permissions(manage_messages=True)
async def export_config(ctx):
    """Экспортирует конфигурацию канала в JSON файл"""
    subs = load_subs()
    ch_id = str(ctx.channel.id)
    if ch_id not in subs:
        await ctx.send("❌ Use `!init` first.")
        return

    config_json = json.dumps(subs[ch_id], indent=2, ensure_ascii=False)
    filename = f"config_{ctx.channel.name}_{ch_id}.json"
    await ctx.send(file=discord.File(io.BytesIO(config_json.encode()), filename=filename))

@commands.command(name="import")
@commands.has_permissions(manage_messages=True)
async def import_config(ctx):
    """Импортирует конфигурацию канала из прикреплённого JSON файла"""
    if not ctx.message.attachments:
        await ctx.send("❌ Прикрепите JSON файл с конфигурацией.")
        return

    attachment = ctx.message.attachments[0]
    if not attachment.filename.endswith('.json'):
        await ctx.send("❌ Файл должен быть в формате JSON.")
        return

    try:
        content = await attachment.read()
        config = json.loads(content)
    except Exception as e:
        await ctx.send(f"❌ Ошибка чтения файла: {e}")
        return

    subs = load_subs()
    ch_id = str(ctx.channel.id)
    subs[ch_id] = config
    save_subs(subs)
    bot.config_updated = True
    await ctx.send(f"✅ Конфигурация импортирована для канала {ctx.channel.mention}")

@commands.command(name="clearcache")
@commands.has_permissions(manage_messages=True)
async def clear_cache(ctx):
    """Очищает кэш имён ESI"""
    cache_size = len(bot.name_cache)
    bot.name_cache.clear()
    await ctx.send(f"🧹 Кэш имён очищен. Удалено {cache_size} записей.")

# Регистрируем команды
bot.add_command(analyze_characters)
bot.add_command(analyze_characters_image)
bot.add_command(analyzer_stats)
bot.add_command(image_clean)
bot.add_command(stats_command)
bot.add_command(search_command)
bot.add_command(add_multi)
bot.add_command(export_config)
bot.add_command(import_config)
bot.add_command(clear_cache)
bot.add_command(help_command)
bot.add_command(init_channel)
bot.add_command(set_min_value)
bot.add_command(add_to_watch)
bot.add_command(remove_from_watch)
bot.add_command(status)
bot.add_command(monitor_stats)
bot.add_command(ping)
bot.add_command(check)
bot.add_command(restart_bot)
bot.add_command(image_stats)