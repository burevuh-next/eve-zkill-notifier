import discord
from discord.ext import commands
import aiohttp
import logging
import os
import json
from datetime import datetime


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
    embed.add_field(name="Basic", value="`!init` | `!status` | `!min [value]`", inline=False)
    embed.add_field(name="Filters", value="`!add/remove [type] [ID]`\nTypes: system, region, const, ship, corp, char", inline=False)
    embed.add_field(name="Priority", value="`!add ping_sys [ID]` | `!add ping_ship [ID]`", inline=False)
    embed.add_field(name="Monitoring", value="`!monitor` - статистика ресурсов", inline=False)
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
            "ping_sys": [], "ping_ship": [], 
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
        "ping_sys": "ping_sys", "ping_ship": "ping_ship"
    }
    
    cat = category.lower()
    if cat not in mapping: 
        return await ctx.send("❌ Invalid type. Use: system, region, const, ship, corp, char, ping_sys, ping_ship")
    
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
    subs = load_subs()
    ch_id = str(ctx.channel.id)
    if ch_id not in subs: 
        return await ctx.send("❌ Use `!init` first.")
    
    ch_data = subs[ch_id]
    all_ids = []
    for k in ["ships","systems","regions","consts","corps","chars","ping_sys","ping_ship"]:
        all_ids.extend(ch_data.get(k, []))
    
    names = await bot.get_eve_names(all_ids)
    
    embed = discord.Embed(
        title="📊 Channel Status", 
        color=discord.Color.blue(), 
        timestamp=datetime.utcnow()
    )
    
    categories = [
        ("ships", "🚀 Ships"),
        ("systems", "🪐 Systems"),
        ("regions", "🌌 Regions"),
        ("consts", "⚡ Constellations"),
        ("corps", "🏢 Corporations"),
        ("chars", "👤 Characters"),
        ("ping_sys", "🔔 Priority Systems"),
        ("ping_ship", "🔔 Priority Ships")
    ]
    
    for key, label in categories:
        ids = ch_data.get(key, [])
        if ids:
            items = []
            for i in ids[:5]:  # Показываем только первые 5
                items.append(f"• {names.get(i, i)} [{i}]")
            if len(ids) > 5:
                items.append(f"... и еще {len(ids) - 5}")
            embed.add_field(name=label, value="\n".join(items), inline=False)
    
    embed.add_field(name="💰 Threshold", value=f"**{bot.format_isk(ch_data.get('min_value', 0))} ISK**")
    
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
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    
    embed.add_field(name="🔌 Пик соединений", value=stats['connections_peak'], inline=True)
    embed.add_field(name="💾 Пик памяти", value=f"{stats['memory_peak_mb']} МБ", inline=True)
    embed.add_field(name="⚡ Пик CPU", value=f"{stats['cpu_peak_percent']}%", inline=True)
    
    if stats['warnings']:
        warnings_text = "\n".join(stats['warnings'][-5:])
        embed.add_field(name="⚠️ Последние предупреждения", value=f"```{warnings_text}```", inline=False)
    
    await ctx.send(embed=embed)

@commands.command(name="ping")
async def ping(ctx):
    await ctx.send(f"o7 {ctx.author.mention}!")

@commands.command(name="check")
async def check(ctx, target_id: int):
    res = await bot.get_eve_names([target_id])
    await ctx.send(f"ID `{target_id}` -> **{res.get(target_id, 'Not found')}**")

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





# Регистрируем команды
bot.add_command(image_clean)
bot.add_command(help_command)
bot.add_command(init_channel)
bot.add_command(set_min_value)
bot.add_command(add_to_watch)
bot.add_command(remove_from_watch)
bot.add_command(status)
bot.add_command(monitor_stats)
bot.add_command(ping)
bot.add_command(check)
bot.add_command(image_stats)