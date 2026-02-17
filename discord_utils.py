import discord
from discord.ext import commands
import aiohttp
import logging
import os
import json
from datetime import datetime

# --- ФУНКЦИИ УПРАВЛЕНИЯ ПОДПИСКАМИ ---
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

# --- ИНТЕГРАЦИЯ ГЕНЕРАТОРА ---
try:
    from image_generator_dual_format import get_generator
    IMAGE_GENERATION_ENABLED = True
except ImportError:
    IMAGE_GENERATION_ENABLED = False
    logging.warning("⚠️ image_generator_dual_format.py не найден!")

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
        if not clean_ids: return {}
        to_fetch = [i for i in clean_ids if i not in self.name_cache]
        if to_fetch:
            url = "https://esi.evetech.net/latest/universe/names/"
            try:
                async with self.session.post(url, json=to_fetch) as resp:
                    if resp.status == 200:
                        for item in await resp.json():
                            self.name_cache[item['id']] = item['name']
            except: pass
        return {i: self.name_cache.get(i, f"ID:{i}") for i in clean_ids}

    def format_isk(self, value):
        if value >= 1e9: return f"{value/1e9:.2f}B"
        if value >= 1e6: return f"{value/1e6:.1f}M"
        return f"{value:,.0f}"

    def get_discord_timestamp(self, esi_time_str):
        try:
            dt = datetime.fromisoformat(esi_time_str.replace('Z', '+00:00'))
            return f"<t:{int(dt.timestamp())}:t>"
        except: return "00:00"

    async def send_kill_notification(self, channel_id, killmail, event_type):
        """Отправляет чистое текстовое уведомление и картинку"""
        channel = self.get_channel(int(channel_id))
        if not channel: return

        zkb = killmail.get('zkb', {})
        value = zkb.get('totalValue', 0)
        k_id = killmail.get('killmail_id', 0)
        victim = killmail.get('victim', {})
        attackers = killmail.get('attackers', [])
        attacker = next((a for a in attackers if a.get('final_blow')), attackers[0] if attackers else {})

        ids = [
            killmail.get('solar_system_id'), victim.get('ship_type_id'), 
            victim.get('character_id'), attacker.get('character_id'),
            victim.get('corporation_id'), attacker.get('corporation_id')
        ]
        names = await self.get_eve_names(ids)

        prefix = "🚨 **PRIORITY**" if event_type == "PRIORITY_TARGET" else "📢 **KILL**"
        v_name = names.get(victim.get('character_id'), "Unknown")
        sys_name = names.get(killmail.get('solar_system_id'), "Unknown")
        time_ts = self.get_discord_timestamp(killmail.get('killmail_time', ''))
        
        content = (
            f"{prefix} | **{self.format_isk(value)} ISK** | {sys_name} | "
            f"**{v_name}** | {time_ts} | <https://zkillboard.com/kill/{k_id}/>"
        )

        if IMAGE_GENERATION_ENABLED:
            try:
                path = await get_generator().generate_killmail_image(self.session, killmail, names, event_type)
                if os.path.exists(path):
                    await channel.send(content=content, file=discord.File(path))
                    return
            except Exception as e:
                logging.error(f"❌ Ошибка картинки: {e}")

        await channel.send(content=content)

bot = EveBot()
# Далее твои @commands.command...

# --- КОМАНДЫ ---

@commands.command(name="help")
async def help_command(ctx):
    """Выводит справку по командам"""
    embed = discord.Embed(
        title="📖 Справка EVE KillBot",
        description="Мониторинг zKillboard в реальном времени. Настройте фильтры для этого канала!",
        color=discord.Color.green()
    )
    embed.add_field(name="🛠 Базовые", value="`!init` - Начать работу в канале\n`!status` - Текущие фильтры\n`!min [число]` - Порог в ISK (напр. `!min 500`)", inline=False)
    embed.add_field(name="📡 Фильтры", value="`!add [тип] [ID]` / `!remove [тип] [ID]`\nТипы: `system`, `region`, `const`, `ship`, `corp`, `char`", inline=False)
    embed.add_field(name="🚨 Пинги", value="Игнорируют порог ISK:\n`!add ping_sys [ID]`\n`!add ping_ship [ID]`", inline=False)
    embed.add_field(name="🔍 Инфо", value="`!check [ID]` - Узнать имя по ID\n`!ping` - Проверка связи", inline=False)
    embed.set_footer(text="o7 Fly Safe")
    await ctx.send(embed=embed)

@commands.command(name="init")
@commands.has_permissions(manage_channels=True)
async def init_channel(ctx):
    subs = load_subs()
    ch_id = str(ctx.channel.id)
    if ch_id not in subs:
        subs[ch_id] = {
            "corps": [], "systems": [], "regions": [], "ships": [],
            "chars": [], "consts": [], "ping_sys": [], "ping_ship": [],
            "min_value": 1000000
        }
        save_subs(subs)
        bot.config_updated = True
        await ctx.send(f"✅ Канал {ctx.channel.mention} инициализирован!")
    else:
        await ctx.send("⚠️ Канал уже настроен.")

@commands.command(name="min")
@commands.has_permissions(manage_messages=True)
async def set_min_value(ctx, value: float):
    """Установить порог в миллионах"""
    subs = load_subs()
    ch_id = str(ctx.channel.id)
    if ch_id in subs:
        subs[ch_id]["min_value"] = value
        save_subs(subs)
        bot.config_updated = True
        await ctx.send(f"💰 Новый порог: **{bot.format_isk(value)} ISK**")

@commands.command(name="add")
@commands.has_permissions(manage_messages=True)
async def add_to_watch(ctx, category: str, item_id: int):
    subs = load_subs()
    ch_id = str(ctx.channel.id)
    if ch_id not in subs: return await ctx.send("❌ Используйте `!init`.")

    mapping = {
        "system": "systems", "region": "regions", "ship": "ships",
        "corp": "corps", "char": "chars", "const": "consts",
        "ping_sys": "ping_sys", "ping_ship": "ping_ship"
    }

    cat = category.lower()
    if cat not in mapping: return await ctx.send("❌ Неверный тип.")

    key = mapping[cat]
    if item_id not in subs[ch_id][key]:
        subs[ch_id][key].append(item_id)
        save_subs(subs)
        bot.config_updated = True 
        res = await bot.get_eve_names([item_id])
        await ctx.send(f"✅ **{res.get(item_id, item_id)}** добавлен в `{cat}`.")

@commands.command(name="remove")
@commands.has_permissions(manage_messages=True)
async def remove_from_watch(ctx, category: str, item_id: int):
    subs = load_subs()
    ch_id = str(ctx.channel.id)
    mapping = {"system":"systems","region":"regions","ship":"ships","corp":"corps","char":"chars","const":"consts","ping_sys":"ping_sys","ping_ship":"ping_ship"}
    key = mapping.get(category.lower())
    if ch_id in subs and key and item_id in subs[ch_id][key]:
        subs[ch_id][key].remove(item_id)
        save_subs(subs)
        bot.config_updated = True
        await ctx.send(f"🗑️ ID `{item_id}` удален.")

@commands.command(name="status")
async def status(ctx):
    subs = load_subs()
    ch_id = str(ctx.channel.id)
    if ch_id not in subs: 
        return await ctx.send("❌ Канал не настроен. Используйте `!init`.")

    ch_data = subs[ch_id]
    keys_to_show = {
        "ships": "🚀 Корабли",
        "systems": "🌌 Системы",
        "regions": "🗺️ Регионы",
        "consts": "🔭 Созвездия",
        "corps": "🏢 Корпорации",
        "chars": "👤 Персонажи",
        "ping_sys": "🚨 Пинг Системы",
        "ping_ship": "🚨 Пинг Корабли"
    }
    
    # Собираем все ID для одного запроса имен
    all_ids = []
    for k in keys_to_show:
        all_ids.extend(ch_data.get(k, []))
    
    names = await bot.get_eve_names(all_ids)
    
    embed = discord.Embed(
        title="📊 Статус канала", 
        color=discord.Color.blue(),
        timestamp=datetime.utcnow()
    )
    
    for k, label in keys_to_show.items():
        ids = ch_data.get(k, [])
        if ids:
            # Формат: • Имя [ID]
            txt = "\n".join([f"• {names.get(i, i)} [{i}]" for i in ids])
            
            # Проверка на длину (Discord Embed field limit 1024 chars)
            if len(txt) > 1000:
                txt = txt[:990] + "..."
                
            embed.add_field(name=label, value=f"```text\n{txt}```", inline=False)
    
    embed.add_field(
        name="💰 Порог", 
        value=f"**{bot.format_isk(ch_data.get('min_value', 0))} ISK**",
        inline=True
    )
    
    embed.set_footer(text=f"ID канала: {ch_id} | o7")
    await ctx.send(embed=embed)

@commands.command(name="ping")
async def ping(ctx):
    await ctx.send(f"o7 {ctx.author.mention}! Бот на связи.")

@commands.command(name="check")
async def check(ctx, target_id: int):
    res = await bot.get_eve_names([target_id])
    await ctx.send(f"🔍 ID `{target_id}` -> **{res.get(target_id, 'Не найдено')}**")