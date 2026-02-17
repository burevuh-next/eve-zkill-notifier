import logging
import os
import io
import time  # <-- Добавить этот импорт
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import aiohttp
import asyncio
from functools import partial

class LargeKillImageGenerator:
    """
    Генератор изображений killmail для Discord
    Адаптивный размер под длину имён
    """
    
    def __init__(self):
        self.cache_dir = "image_cache"
        self.output_dir = "killmail_images"
        
        self.image_ttl_hours = int(os.getenv("IMAGE_TTL_HOURS", "24"))  # По умолчанию 24 часа
        self.max_images_count = int(os.getenv("MAX_IMAGES_COUNT", "1000"))  # Максимум 1000 файлов
        
        os.makedirs(os.path.join(self.cache_dir, 'renders'), exist_ok=True)
        os.makedirs(os.path.join(self.cache_dir, 'portraits'), exist_ok=True)
        os.makedirs(os.path.join(self.cache_dir, 'corp_logos'), exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        
        self.load_fonts()
        
        self.colors = {
            'bg_dark': (12, 12, 18),
            'bg_card': (22, 24, 32),
            'bg_gradient_start': (18, 20, 28),
            'bg_gradient_end': (8, 10, 15),
            'text_white': (255, 255, 255),
            'text_primary': (230, 235, 240),
            'text_secondary': (150, 160, 175),
            'text_muted': (100, 110, 125),
            'accent_red': (220, 50, 50),
            'accent_green': (50, 200, 100),
            'accent_gold': (255, 200, 50),
            'accent_cyan': (0, 200, 220),
            'accent_purple': (180, 100, 255),
            'border': (40, 45, 55),
            'danger': (80, 255, 130),      # Зелёный для VICTIM
            'success': (255, 80, 80),      # Красный для KILLER
        }

        # Статистика для мониторинга
        self.stats = {
            "images_generated": 0,
            "total_generation_time": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "images_cleaned": 0,  # Добавлено
            "disk_space_freed_mb": 0  # Добавлено
        }

        # Запускаем фоновую задачу очистки
        self.cleanup_task = None
    async def start_cleanup_task(self):
        """Запускает фоновую задачу очистки старых изображений"""
        if self.cleanup_task is None:
            self.cleanup_task = asyncio.create_task(self._cleanup_loop())
            logging.info(f"🧹 Задача очистки изображений запущена (TTL: {self.image_ttl_hours}ч, макс: {self.max_images_count} файлов)")
    
    async def stop_cleanup_task(self):
        """Останавливает фоновую задачу очистки"""
        if self.cleanup_task is not None:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
            finally:
                self.cleanup_task = None
                logging.info("🧹 Задача очистки изображений остановлена")
    
    async def _cleanup_loop(self):
        """Фоновый цикл очистки старых изображений"""
        try:
            while True:
                # Проверяем раз в час
                await asyncio.sleep(3600)  # 1 час
                await self._cleanup_old_images()
        except asyncio.CancelledError:
            # Финальная очистка при остановке
            await self._cleanup_old_images()
            raise
    
    async def _cleanup_old_images(self):
        """Очищает старые изображения"""
        try:
            # Выполняем очистку в потоке, чтобы не блокировать event loop
            freed_space, cleaned_count = await asyncio.to_thread(self._cleanup_sync)
            
            if cleaned_count > 0:
                self.stats["images_cleaned"] += cleaned_count
                self.stats["disk_space_freed_mb"] += freed_space
                logging.info(f"🧹 Очищено {cleaned_count} старых изображений, освобождено {freed_space:.1f} МБ")
                
        except Exception as e:
            logging.error(f"❌ Ошибка при очистке изображений: {e}")
    
    def _cleanup_sync(self):
        """Синхронная очистка (выполняется в потоке)"""
        if not os.path.exists(self.output_dir):
            return 0, 0
        
        freed_space = 0
        cleaned_count = 0
        now = time.time()
        
        # Получаем список всех файлов
        files = []
        for filename in os.listdir(self.output_dir):
            if filename.startswith("kill_") and filename.endswith(".png"):
                filepath = os.path.join(self.output_dir, filename)
                try:
                    file_stat = os.stat(filepath)
                    file_age_hours = (now - file_stat.st_mtime) / 3600
                    
                    # Извлекаем kill_id из имени файла
                    kill_id = filename.replace("kill_", "").replace(".png", "")
                    
                    files.append({
                        'path': filepath,
                        'size': file_stat.st_size,
                        'mtime': file_stat.st_mtime,
                        'age_hours': file_age_hours,
                        'kill_id': kill_id
                    })
                except Exception:
                    continue
        
        # Сортируем по времени модификации (от старых к новым)
        files.sort(key=lambda x: x['mtime'])
        
        # 1. Удаляем по возрасту
        for file in files[:]:
            if file['age_hours'] > self.image_ttl_hours:
                try:
                    file_size = file['size']
                    os.remove(file['path'])
                    freed_space += file_size
                    cleaned_count += 1
                    files.remove(file)
                    logging.debug(f"🧹 Удалено старое изображение: {file['path']} (возраст: {file['age_hours']:.1f}ч)")
                except Exception as e:
                    logging.error(f"❌ Ошибка удаления {file['path']}: {e}")
        
        # 2. Если все еще превышен лимит, удаляем самые старые
        if len(files) > self.max_images_count:
            to_delete = len(files) - self.max_images_count
            for file in files[:to_delete]:
                try:
                    file_size = file['size']
                    os.remove(file['path'])
                    freed_space += file_size
                    cleaned_count += 1
                    logging.debug(f"🧹 Удалено изображение (лимит): {file['path']}")
                except Exception as e:
                    logging.error(f"❌ Ошибка удаления {file['path']}: {e}")
        
        return freed_space / (1024 * 1024), cleaned_count  # возвращаем МБ и количество
    
    def get_disk_usage(self):
        """Возвращает информацию об использовании диска"""
        if not os.path.exists(self.output_dir):
            return {"total_files": 0, "total_size_mb": 0}
        
        total_size = 0
        file_count = 0
        
        for filename in os.listdir(self.output_dir):
            if filename.startswith("kill_") and filename.endswith(".png"):
                filepath = os.path.join(self.output_dir, filename)
                try:
                    total_size += os.path.getsize(filepath)
                    file_count += 1
                except Exception:
                    continue
        
        return {
            "total_files": file_count,
            "total_size_mb": round(total_size / (1024 * 1024), 1)
        }
    def load_fonts(self):
        """Загрузка шрифтов (синхронная операция)"""
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
        
        bold_path = None
        regular_path = None
        
        for path in font_paths:
            if os.path.exists(path):
                if 'Bold' in path or 'bd' in path:
                    bold_path = path
                elif regular_path is None:
                    regular_path = path
        
        if bold_path is None and regular_path:
            bold_path = regular_path
        if regular_path is None and bold_path:
            regular_path = bold_path
            
        try:
            if bold_path:
                self.font_title = ImageFont.truetype(bold_path, 48)
                self.font_large = ImageFont.truetype(bold_path, 36)
                self.font_medium = ImageFont.truetype(bold_path, 24)
                self.font_normal = ImageFont.truetype(bold_path, 18)
            if regular_path:
                self.font_small = ImageFont.truetype(regular_path, 14)
                self.font_tiny = ImageFont.truetype(regular_path, 12)
            else:
                self.font_small = ImageFont.load_default()
                self.font_tiny = ImageFont.load_default()
        except Exception as e:
            logging.warning(f"Font loading error: {e}")
            self.font_title = ImageFont.load_default()
            self.font_large = ImageFont.load_default()
            self.font_medium = ImageFont.load_default()
            self.font_normal = ImageFont.load_default()
            self.font_small = ImageFont.load_default()
            self.font_tiny = ImageFont.load_default()

    async def download_image(self, session, url, filename, size=None):
        """Асинхронная загрузка изображения с кешированием"""
        cache_path = os.path.join(self.cache_dir, filename)
        
        # Проверяем кеш
        if os.path.exists(cache_path):
            try:
                # Чтение файла делаем в потоке, чтобы не блокировать event loop
                img_data = await asyncio.to_thread(self._load_image_from_cache, cache_path, size)
                if img_data:
                    self.stats["cache_hits"] += 1
                    return img_data
            except Exception as e:
                logging.debug(f"Cache read error: {e}")
                os.remove(cache_path)
        
        self.stats["cache_misses"] += 1
        
        # Загружаем изображение
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    # Обработку изображения делаем в потоке
                    img = await asyncio.to_thread(self._process_downloaded_image, data, cache_path, size)
                    return img
        except Exception as e:
            logging.debug(f"Image download failed: {url} -> {e}")
        
        return None
    
    def _load_image_from_cache(self, cache_path, size):
        """Загрузка из кеша (выполняется в потоке)"""
        try:
            img = Image.open(cache_path).convert('RGBA')
            if size:
                img = img.resize(size, Image.Resampling.LANCZOS)
            return img
        except Exception:
            return None
    
    def _process_downloaded_image(self, data, cache_path, size):
        """Обработка загруженного изображения (выполняется в потоке)"""
        try:
            img = Image.open(io.BytesIO(data)).convert('RGBA')
            img.save(cache_path)
            if size:
                img = img.resize(size, Image.Resampling.LANCZOS)
            return img
        except Exception as e:
            logging.error(f"Image processing error: {e}")
            return None

    def format_isk(self, value):
        if value >= 1_000_000_000_000:
            return f"{value / 1_000_000_000_000:.2f}T"
        if value >= 1_000_000_000:
            return f"{value / 1_000_000_000:.2f}B"
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"{value / 1_000:.1f}K"
        return f"{value:,.0f}"

    def get_value_color(self, value):
        if value >= 10_000_000_000:
            return self.colors['accent_purple']
        if value >= 1_000_000_000:
            return self.colors['accent_gold']
        if value >= 500_000_000:
            return self.colors['accent_cyan']
        if value >= 100_000_000:
            return self.colors['accent_green']
        return self.colors['text_white']

    def get_value_badge(self, value):
        if value >= 10_000_000_000:
            return "MEGA KILL", self.colors['accent_purple']
        if value >= 1_000_000_000:
            return "BILLION KILL", self.colors['accent_gold']
        if value >= 500_000_000:
            return "EXPENSIVE", self.colors['accent_cyan']
        if value >= 100_000_000:
            return "HIGH VALUE", self.colors['accent_green']
        return "KILL", self.colors['accent_red']

    def draw_rounded_rect(self, draw, coords, radius, fill, outline=None, width=1):
        draw.rounded_rectangle(coords, radius=radius, fill=fill, outline=outline, width=width)

    def calculate_card_width(self, name, corp_name, font_name, font_corp, portrait_size=64, padding=80, min_width=250, max_width=400):
        name_bbox = font_name.getbbox(name)
        name_width = name_bbox[2] - name_bbox[0]
        
        corp_bbox = font_corp.getbbox(corp_name)
        corp_width = corp_bbox[2] - corp_bbox[0]
        
        text_width = max(name_width, corp_width)
        needed_width = portrait_size + padding + text_width + 20
        
        return max(min_width, min(max_width, needed_width))

    async def generate_killmail_image(self, session, killmail_data, names_dict, event_type):
        """Основной метод генерации изображения"""
        import time
        start_time = time.time()
        
        try:
            # Подготавливаем данные для генерации (это быстро, можно в основном потоке)
            victim = killmail_data.get('victim', {})
            zkb = killmail_data.get('zkb', {})
            attackers = killmail_data.get('attackers', [])
            attacker = next((a for a in attackers if a.get('final_blow')), attackers[0] if attackers else {})
            
            ship_id = victim.get('ship_type_id', 0)
            value = float(zkb.get('totalValue', 0))
            k_id = killmail_data.get('killmail_id', 0)
            sys_id = killmail_data.get('solar_system_id', 0)
            
            ship_name = names_dict.get(int(ship_id), "Unknown Ship")
            sys_name = names_dict.get(int(sys_id), "Unknown System")
            v_name = names_dict.get(victim.get('character_id'), "Unknown")
            v_corp = names_dict.get(victim.get('corporation_id'), "Unknown Corp")
            a_name = names_dict.get(attacker.get('character_id'), "NPC")
            a_corp = names_dict.get(attacker.get('corporation_id'), "Unknown Corp")
            a_ship_name = names_dict.get(attacker.get('ship_type_id'), "Unknown")
            
            # Собираем ТОЛЬКО реальные задачи (не None)
            download_tasks = []
            task_names = []
            
            # Рендер корабля жертвы
            render_task = self.download_image(
                session,
                f"https://images.evetech.net/types/{ship_id}/render?size=512",
                f"renders/ship_{ship_id}.png",
                size=(220, 220)
            )
            download_tasks.append(render_task)
            task_names.append("render")
            
            # Портрет жертвы
            v_char_id = victim.get('character_id')
            if v_char_id:
                v_portrait_task = self.download_image(
                    session,
                    f"https://images.evetech.net/characters/{v_char_id}/portrait?size=64",
                    f"portraits/char_{v_char_id}.png",
                    size=(64, 64)
                )
                download_tasks.append(v_portrait_task)
                task_names.append("v_portrait")
            else:
                download_tasks.append(None)  # Заглушка для сохранения порядка
                task_names.append(None)
            
            # Портрет убийцы
            a_char_id = attacker.get('character_id')
            if a_char_id:
                a_portrait_task = self.download_image(
                    session,
                    f"https://images.evetech.net/characters/{a_char_id}/portrait?size=64",
                    f"portraits/char_{a_char_id}.png",
                    size=(64, 64)
                )
                download_tasks.append(a_portrait_task)
                task_names.append("a_portrait")
            else:
                download_tasks.append(None)
                task_names.append(None)
            
            # Лого корпорации жертвы
            v_corp_id = victim.get('corporation_id')
            if v_corp_id:
                v_logo_task = self.download_image(
                    session,
                    f"https://images.evetech.net/corporations/{v_corp_id}/logo?size=64",
                    f"corp_logos/corp_{v_corp_id}.png",
                    size=(48, 48)
                )
                download_tasks.append(v_logo_task)
                task_names.append("v_logo")
            else:
                download_tasks.append(None)
                task_names.append(None)
            
            # Иконка корабля убийцы
            a_ship_id = attacker.get('ship_type_id')
            if a_ship_id:
                a_ship_task = self.download_image(
                    session,
                    f"https://images.evetech.net/types/{a_ship_id}/icon?size=64",
                    f"renders/icon_{a_ship_id}.png",
                    size=(48, 48)
                )
                download_tasks.append(a_ship_task)
                task_names.append("a_ship")
            else:
                download_tasks.append(None)
                task_names.append(None)
            
            # Фильтруем None из задач для gather
            valid_tasks = [task for task in download_tasks if task is not None]
            
            if valid_tasks:
                # Ждем все реальные задачи
                results = await asyncio.gather(*valid_tasks, return_exceptions=True)
                
                # Собираем результаты обратно в соответствии с порядком
                result_index = 0
                render_result = None
                v_portrait_result = None
                a_portrait_result = None
                v_logo_result = None
                a_ship_result = None
                
                for i, task_name in enumerate(task_names):
                    if task_name == "render":
                        render_result = results[result_index] if result_index < len(results) else None
                        result_index += 1
                    elif task_name == "v_portrait":
                        v_portrait_result = results[result_index] if result_index < len(results) else None
                        result_index += 1
                    elif task_name == "a_portrait":
                        a_portrait_result = results[result_index] if result_index < len(results) else None
                        result_index += 1
                    elif task_name == "v_logo":
                        v_logo_result = results[result_index] if result_index < len(results) else None
                        result_index += 1
                    elif task_name == "a_ship":
                        a_ship_result = results[result_index] if result_index < len(results) else None
                        result_index += 1
            else:
                # Нет задач для загрузки
                render_result = None
                v_portrait_result = None
                a_portrait_result = None
                v_logo_result = None
                a_ship_result = None
            
            # Проверяем на исключения
            ship_render = render_result if render_result and not isinstance(render_result, Exception) else None
            v_portrait = v_portrait_result if v_portrait_result and not isinstance(v_portrait_result, Exception) else None
            a_portrait = a_portrait_result if a_portrait_result and not isinstance(a_portrait_result, Exception) else None
            v_logo = v_logo_result if v_logo_result and not isinstance(v_logo_result, Exception) else None
            a_ship = a_ship_result if a_ship_result and not isinstance(a_ship_result, Exception) else None
            
            # Тяжелую работу по созданию изображения выносим в поток
            kill_time = killmail_data.get('killmail_time', '')
            time_str = self._parse_kill_time(kill_time)
            
            # Создаем частичную функцию с захваченными данными
            generate_func = partial(
                self._generate_image_sync,
                ship_render=ship_render,
                v_portrait=v_portrait,
                a_portrait=a_portrait,
                v_logo=v_logo,
                a_ship=a_ship,
                ship_name=ship_name,
                sys_name=sys_name,
                v_name=v_name,
                v_corp=v_corp,
                a_name=a_name,
                a_corp=a_corp,
                a_ship_name=a_ship_name,
                value=value,
                k_id=k_id,
                time_str=time_str,
                attackers_count=len(attackers),
                victim_card_width=self.calculate_card_width(v_name, v_corp, self.font_medium, self.font_small),
                killer_card_width=self.calculate_card_width(a_name, a_corp, self.font_medium, self.font_small)
            )
            
            # Выполняем генерацию в потоке
            output_path = await asyncio.to_thread(generate_func)
            
            # Обновляем статистику
            elapsed = time.time() - start_time
            self.stats["images_generated"] += 1
            self.stats["total_generation_time"] += elapsed
            
            logging.info(f"✅ Image generated in {elapsed:.2f}s: {output_path}")
            
            # Проверяем, нужно ли запустить очистку
            disk_usage = self.get_disk_usage()
            if disk_usage["total_files"] > self.max_images_count * 0.9:
                asyncio.create_task(self._cleanup_old_images())
            
            return output_path
            
        except Exception as e:
            logging.error(f"❌ Error generating image: {e}", exc_info=True)
            return None
    
    def _parse_kill_time(self, kill_time):
        """Парсинг времени убийства (синхронный)"""
        time_str = datetime.now().strftime('%H:%M')
        if kill_time:
            try:
                dt = datetime.fromisoformat(kill_time.replace('Z', '+00:00'))
                time_str = dt.strftime('%H:%M')
            except:
                pass
        return time_str
    
    def _generate_image_sync(self, ship_render, v_portrait, a_portrait, v_logo, a_ship,
                            ship_name, sys_name, v_name, v_corp, a_name, a_corp, a_ship_name,
                            value, k_id, time_str, attackers_count, victim_card_width, killer_card_width):
        """Синхронная генерация изображения (выполняется в потоке)"""
        
        # Расчет размеров
        base_width = 250 + victim_card_width + 20 + killer_card_width + 60
        width = max(900, base_width)
        height = 500
        
        # Создание изображения
        img = Image.new('RGBA', (width, height), self.colors['bg_dark'])
        draw = ImageDraw.Draw(img, 'RGBA')
        
        # Градиентный фон
        for y in range(height):
            ratio = y / height
            r = int(self.colors['bg_gradient_start'][0] * (1 - ratio) + self.colors['bg_gradient_end'][0] * ratio)
            g = int(self.colors['bg_gradient_start'][1] * (1 - ratio) + self.colors['bg_gradient_end'][1] * ratio)
            b = int(self.colors['bg_gradient_start'][2] * (1 - ratio) + self.colors['bg_gradient_end'][2] * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b, 255))
        
        # Бейдж стоимости
        badge_text, badge_color = self.get_value_badge(value)
        value_color = self.get_value_color(value)
        isk_str = self.format_isk(value)
        
        badge_x, badge_y = 25, 20
        badge_w, badge_h = 160, 35
        self.draw_rounded_rect(draw, (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h), 
                               radius=8, fill=badge_color + (40,), outline=badge_color, width=2)
        draw.text((badge_x + 15, badge_y + 6), badge_text, font=self.font_small, fill=badge_color)
        
        # Стоимость
        value_str = f"{isk_str} ISK"
        bbox = draw.textbbox((0, 0), value_str, font=self.font_title)
        text_w = bbox[2] - bbox[0]
        draw.text((width // 2 - text_w // 2, 45), value_str, font=self.font_title, fill=value_color)
        
        # Название корабля
        bbox = draw.textbbox((0, 0), ship_name, font=self.font_large)
        text_w = bbox[2] - bbox[0]
        draw.text((width // 2 - text_w // 2, 105), ship_name, font=self.font_large, fill=self.colors['text_primary'])
        
        # Рендер корабля
        render_size = 220
        render_x = 40
        render_y = 160
        
        card_margin = 15
        self.draw_rounded_rect(draw, 
                               (render_x - card_margin, render_y - card_margin, 
                                render_x + render_size + card_margin, render_y + render_size + card_margin),
                               radius=15, fill=self.colors['bg_card'] + (200,), 
                               outline=self.colors['border'], width=2)
        
        if ship_render:
            if value >= 500_000_000:
                glow = ship_render.resize((render_size + 30, render_size + 30))
                glow = glow.filter(ImageFilter.GaussianBlur(15))
                glow = ImageEnhance.Brightness(glow).enhance(0.3)
                img.paste(glow, (render_x - 15, render_y - 15), glow)
            img.paste(ship_render, (render_x, render_y), ship_render)
        
        # Секция с информацией
        info_x = render_x + render_size + 30
        info_y = 160
        card_height = 200
        
        # VICTIM карточка
        victim_x = info_x
        self.draw_rounded_rect(draw, 
                               (victim_x - 10, info_y - 10, victim_x + victim_card_width, info_y + card_height),
                               radius=12, fill=self.colors['bg_card'] + (180,),
                               outline=self.colors['danger'], width=2)
        draw.text((victim_x + 5, info_y), "VICTIM", font=self.font_small, fill=self.colors['danger'])
        
        if v_portrait:
            img.paste(v_portrait, (victim_x + 5, info_y + 25), v_portrait)
        
        draw.text((victim_x + 80, info_y + 30), v_name, font=self.font_medium, fill=self.colors['text_white'])
        draw.text((victim_x + 80, info_y + 60), v_corp, font=self.font_small, fill=self.colors['text_secondary'])
        
        if v_logo:
            img.paste(v_logo, (victim_x + 5, info_y + 100), v_logo)
        draw.text((victim_x + 60, info_y + 115), f"Flying: {ship_name}", font=self.font_tiny, fill=self.colors['text_muted'])
        
        # KILLER карточка
        attacker_x = victim_x + victim_card_width + 20
        self.draw_rounded_rect(draw,
                               (attacker_x - 10, info_y - 10, attacker_x + killer_card_width, info_y + card_height),
                               radius=12, fill=self.colors['bg_card'] + (180,),
                               outline=self.colors['success'], width=2)
        draw.text((attacker_x + 5, info_y), "KILLER", font=self.font_small, fill=self.colors['success'])
        
        if a_portrait:
            img.paste(a_portrait, (attacker_x + 5, info_y + 25), a_portrait)
        
        draw.text((attacker_x + 80, info_y + 30), a_name, font=self.font_medium, fill=self.colors['text_white'])
        draw.text((attacker_x + 80, info_y + 60), a_corp, font=self.font_small, fill=self.colors['text_secondary'])
        
        if a_ship:
            img.paste(a_ship, (attacker_x + 5, info_y + 100), a_ship)
        draw.text((attacker_x + 60, info_y + 115), f"Flying: {a_ship_name}", font=self.font_tiny, fill=self.colors['text_muted'])
        
        # Нижняя секция
        bottom_y = 440
        draw.line([(25, bottom_y - 15), (width - 25, bottom_y - 15)], fill=self.colors['border'], width=1)
        
        draw.text((30, bottom_y), f"System: {sys_name}", font=self.font_normal, fill=self.colors['accent_cyan'])
        draw.text((250, bottom_y), f"Time: {time_str}", font=self.font_normal, fill=self.colors['text_secondary'])
        draw.text((400, bottom_y), f"Attackers: {attackers_count}", font=self.font_normal, fill=self.colors['text_muted'])
        
        # Ссылка на zKillboard
        url_text = f"https://zkillboard.com/kill/{k_id}/"
        draw.text((30, bottom_y + 30), url_text, font=self.font_small, fill=self.colors['text_muted'])
        draw.text((width - 200, bottom_y + 30), f"KillID: {k_id}", font=self.font_small, fill=self.colors['text_muted'])
        
        draw.text((width - 120, 15), "EVE KillBot", font=self.font_tiny, fill=self.colors['text_muted'] + (128,))
        
        # Сохранение
        output_path = os.path.join(self.output_dir, f"kill_{k_id}.png")
        img_rgb = Image.new('RGB', img.size, self.colors['bg_dark'])
        img_rgb.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
        img_rgb.save(output_path, 'PNG', quality=95)
        
        return output_path
    
    def get_stats(self):
        """Возвращает статистику генератора"""
        avg_time = 0
        if self.stats["images_generated"] > 0:
            avg_time = self.stats["total_generation_time"] / self.stats["images_generated"]
        
        disk_usage = self.get_disk_usage()
        
        return {
            "images_generated": self.stats["images_generated"],
            "avg_generation_time": round(avg_time, 2),
            "cache_hits": self.stats["cache_hits"],
            "cache_misses": self.stats["cache_misses"],
            "cache_hit_ratio": round(
                self.stats["cache_hits"] / (self.stats["cache_hits"] + self.stats["cache_misses"]) * 100, 1
            ) if (self.stats["cache_hits"] + self.stats["cache_misses"]) > 0 else 0,
            "images_cleaned": self.stats["images_cleaned"],
            "disk_space_freed_mb": round(self.stats["disk_space_freed_mb"], 1),
            "current_files": disk_usage["total_files"],
            "current_size_mb": disk_usage["total_size_mb"],
            "ttl_hours": self.image_ttl_hours,
            "max_files": self.max_images_count
        }


_generator = LargeKillImageGenerator()

def get_generator():
    return _generator
  
async def start_cleanup():
    """Запускает очистку при старте бота"""
    await _generator.start_cleanup_task()

async def stop_cleanup():
    """Останавливает очистку при остановке бота"""
    await _generator.stop_cleanup_task()