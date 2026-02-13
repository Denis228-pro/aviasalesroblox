"""
Discord бот для Aviasales Roblox - улучшенная версия
"""
import discord
from discord.ext import commands, tasks
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
import logging
from enum import Enum
import asyncio
import random
import traceback
import sys
from collections import deque
import aiohttp

from utils.database import DatabaseHandler
from utils.embeds import Embeds
from utils.status_manager import StatusManager, ActivityType

# =============== УЛУЧШЕННАЯ НАСТРОЙКА ЛОГИРОВАНИЯ ===============
def setup_logging():
    """Настройка логирования с ротацией и разными уровнями"""
    logger = logging.getLogger('aviasales_bot')
    logger.setLevel(logging.INFO)

    # Удаляем существующие обработчики
    logger.handlers.clear()

    # Форматтер с цветами для консоли
    class ColoredFormatter(logging.Formatter):
        COLORS = {
            'DEBUG': '\033[36m',      # Cyan
            'INFO': '\033[32m',       # Green
            'WARNING': '\033[33m',    # Yellow
            'ERROR': '\033[31m',      # Red
            'CRITICAL': '\033[35m',   # Magenta
            'RESET': '\033[0m'
        }

        def format(self, record):
            color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            record.levelname = f"{color}{record.levelname}{self.COLORS['RESET']}"
            record.msg = f"{color}{record.msg}{self.COLORS['RESET']}"
            return super().format(record)

    # Форматтер для файла (без цветов)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Консольный обработчик с цветами
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = ColoredFormatter(
        '[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)

    # Файловый обработчик с ротацией
    try:
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            'logs/bot.log',
            maxBytes=5*1024*1024,  # 5MB
            backupCount=10,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_formatter)
    except ImportError:
        file_handler = logging.FileHandler('bot.log', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_formatter)

    # Обработчик для ошибок
    error_handler = logging.FileHandler('logs/errors.log', encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)

    return logger

logger = setup_logging()

# =============== КОНСТАНТЫ И ПЕРЕЧИСЛЕНИЯ ===============
class ChannelType(Enum):
    """Типы каналов для удобного доступа"""
    REGISTRATION = "REGISTRATION_CHANNEL"
    PARTNERSHIP = "PARTNERSHIP_CHANNEL"
    SUPPORT = "SUPPORT_CHANNEL"
    FAQ = "FAQ_CHANNEL"
    AIRLINE_MODERATION = "AIRLINE_MODERATION_CHANNEL"
    PARTNER_MODERATION = "PARTNER_MODERATION_CHANNEL"
    SUPPORT_TICKETS = "SUPPORT_TICKETS_CHANNEL"
    AUDIT = "AUDIT_CHANNEL"
    COMPLAINTS = "COMPLAINTS_CHANNEL"
    LOGS = "LOGS_CHANNEL"
    STATS = "STATS_CHANNEL"
    ANNOUNCEMENTS = "ANNOUNCEMENTS_CHANNEL"

class BotStatus(Enum):
    """Статусы бота"""
    STARTING = "starting"
    RUNNING = "running"
    MAINTENANCE = "maintenance"
    STOPPING = "stopping"
    ERROR = "error"

# =============== КОНФИГУРАЦИОННЫЙ МЕНЕДЖЕР ===============
class ConfigManager:
    """Менеджер конфигурации с валидацией и кэшированием"""

    def __init__(self):
        self.config = {}
        self._cache = {}
        self._cache_time = {}
        self.CACHE_DURATION = 300  # 5 минут

    def load(self) -> Dict[str, Any]:
        """Загрузка и валидация конфигурации"""
        required_vars = [
            'DISCORD_TOKEN',
            'FIREBASE_CONFIG'
        ]

        optional_vars = [f"{channel_type.value}_ID" for channel_type in ChannelType]

        # Загружаем обязательные переменные
        missing_vars = []
        for var in required_vars:
            value = os.environ.get(var)
            if not value:
                missing_vars.append(var)
            else:
                self.config[var] = value

        if missing_vars:
            raise ValueError(f"Отсутствуют обязательные переменные окружения: {', '.join(missing_vars)}")

        # Загружаем необязательные переменные
        for var in optional_vars:
            value = os.environ.get(var)
            if value:
                try:
                    self.config[var] = int(value)
                except ValueError:
                    logger.warning(f"Некорректный ID канала для {var}: {value}")

        # Парсим конфиг Firebase
        try:
            self.config['FIREBASE_CONFIG_DICT'] = json.loads(self.config['FIREBASE_CONFIG'])
        except json.JSONDecodeError as e:
            raise ValueError(f"Ошибка парсинга Firebase конфига: {e}")

        # Загружаем дополнительные настройки
        self.config.update({
            'PREFIX': os.environ.get('BOT_PREFIX', '/'),
            'OWNER_ID': int(os.environ.get('OWNER_ID', 0)),
            'SUPPORT_SERVER': os.environ.get('SUPPORT_SERVER', ''),
            'LOG_LEVEL': os.environ.get('LOG_LEVEL', 'INFO'),
            'MAINTENANCE_MODE': os.environ.get('MAINTENANCE_MODE', 'false').lower() == 'true'
        })

        logger.info(f"✅ Загружено {len(self.config)} параметров конфигурации")
        return self.config

    def get(self, key: str, default=None):
        """Получение значения с кэшированием"""
        now = datetime.now()

        # Проверяем кэш
        if key in self._cache:
            cache_time = self._cache_time.get(key)
            if cache_time and (now - cache_time).seconds < self.CACHE_DURATION:
                return self._cache[key]

        # Получаем из конфига или переменных окружения
        if key in self.config:
            value = self.config[key]
        else:
            value = os.environ.get(key, default)

        # Кэшируем
        self._cache[key] = value
        self._cache_time[key] = now

        return value

    def reload(self):
        """Перезагрузка конфигурации"""
        self._cache.clear()
        self._cache_time.clear()
        return self.load()

# =============== FIREBASE МЕНЕДЖЕР (УЛУЧШЕННЫЙ) ===============
class FirebaseManager:
    """Улучшенный менеджер Firebase"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._initialized = True
            self.db = None
            self.batch = None
            self._stats = {
                'queries': 0,
                'errors': 0,
                'last_error': None
            }
    
    def initialize(self, firebase_config: str) -> firestore.firestore.Client:
        """Инициализация Firebase с пулом соединений и оптимизированными настройками"""
        if self.db is not None:
            return self.db
        
        try:
            cred_dict = json.loads(firebase_config)
            cred = credentials.Certificate(cred_dict)
            
            if not firebase_admin._apps:
                firebase_admin.initialize_app(
                    cred,
                    options={
                        'projectId': cred_dict.get('project_id'),
                        'httpTimeout': 15  # Уменьшаем таймаут для более быстрого отклика
                    }
                )
            
            # Включаем оптимизацию Firestore
            self.db = firestore.client()
            
            # Устанавливаем соединение заранее
            logger.info("✅ Firebase успешно инициализирован с оптимизацией")
            return self.db
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга JSON конфига Firebase: {e}")
            raise
        except ValueError as e:
            logger.error(f"❌ Ошибка инициализации Firebase: {e}")
            # Попробуем альтернативный метод
            return self._initialize_alternative(cred_dict)
        except Exception as e:
            logger.error(f"❌ Неизвестная ошибка инициализации Firebase: {e}")
            raise
    
    def _initialize_alternative(self, cred_dict: dict) -> firestore.firestore.Client:
        """Альтернативный метод инициализации"""
        try:
            logger.info("Пробуем альтернативный метод инициализации...")
            
            # Попробуем инициализировать без параметров
            if not firebase_admin._apps:
                firebase_admin.initialize_app()
            
            self.db = firestore.client()
            logger.info("✅ Firebase инициализирован альтернативным методом")
            return self.db
        except Exception as e:
            logger.error(f"❌ Альтернативный метод тоже не сработал: {e}")
            raise
    
    def _test_connection(self):
        """Тестирование соединения с Firebase"""
        try:
            # Простая проверка - получение коллекции stats
            stats_ref = self.db.collection('stats').limit(1).get()
            logger.debug(f"✅ Соединение с Firebase установлено, найдено {len(stats_ref)} документов")
        except Exception as e:
            logger.error(f"❌ Ошибка тестирования соединения с Firebase: {e}")
            # Не бросаем исключение, так как соединение может быть установлено позже
    
    async def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        """Получение статистики коллекции"""
        try:
            self._stats['queries'] += 1
            
            # Используем асинхронное выполнение для тяжелых операций
            docs = await asyncio.to_thread(
                lambda: list(self.db.collection(collection_name).limit(100).stream())
            )
            
            return {
                'count': len(docs),
                'sample': docs[:3] if docs else [],
                'last_updated': datetime.now()
            }
        except Exception as e:
            self._stats['errors'] += 1
            self._stats['last_error'] = str(e)
            logger.error(f"Ошибка получения статистики коллекции {collection_name}: {e}")
            return {
                'count': 0,
                'sample': [],
                'last_updated': datetime.now(),
                'error': str(e)
            }
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики менеджера"""
        return self._stats.copy()
    
    def start_batch(self):
        """Начало batch операции"""
        self.batch = self.db.batch()
    
    def commit_batch(self):
        """Коммит batch операции"""
        if self.batch:
            try:
                self.batch.commit()
                logger.debug("Batch операция завершена")
            except Exception as e:
                logger.error(f"Ошибка коммита batch операции: {e}")
            finally:
                self.batch = None

# =============== МЕНЕДЖЕР КАНАЛОВ ===============
class ChannelManager:
    """Менеджер для работы с каналами Discord"""

    def __init__(self, bot, config):
        self.bot = bot
        self.config = config
        self.channels = {}
        self._channel_cache = {}
        self._last_check = {}

    async def initialize(self):
        """Инициализация каналов"""
        logger.info("🔍 Инициализация каналов...")

        for channel_type in ChannelType:
            config_key = f"{channel_type.value}_ID"
            channel_id = self.config.get(config_key)

            if channel_id:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                    if channel:
                        self.channels[channel_type] = channel
                        self._channel_cache[channel_type] = {
                            'channel': channel,
                            'timestamp': datetime.now()
                        }
                        logger.info(f"✅ Канал {channel_type.value}: {channel.name}")
                    else:
                        logger.warning(f"⚠️ Канал {channel_type.value} не найден")
                except discord.Forbidden:
                    logger.error(f"❌ Нет доступа к каналу {channel_type.value}")
                except discord.HTTPException as e:
                    logger.error(f"❌ Ошибка получения канала {channel_type.value}: {e}")
                except Exception as e:
                    logger.error(f"❌ Неизвестная ошибка для канала {channel_type.value}: {e}")
            else:
                logger.warning(f"⚠️ ID для канала {channel_type.value} не указан")

        logger.info(f"✅ Загружено {len(self.channels)} каналов")

    async def get_channel(self, channel_type: ChannelType) -> Optional[discord.TextChannel]:
        """Получение канала с кэшированием"""
        now = datetime.now()

        # Проверяем кэш
        if channel_type in self._channel_cache:
            cache_data = self._channel_cache[channel_type]
            if (now - cache_data['timestamp']).seconds < 300:  # 5 минут
                return cache_data['channel']

        # Получаем канал заново
        config_key = f"{channel_type.value}_ID"
        channel_id = self.config.get(config_key)

        if not channel_id:
            return None

        try:
            channel = await self.bot.fetch_channel(channel_id)
            if channel:
                self._channel_cache[channel_type] = {
                    'channel': channel,
                    'timestamp': now
                }
            return channel
        except Exception as e:
            logger.error(f"Ошибка получения канала {channel_type.value}: {e}")
            return None

    async def send_to_channel(self, channel_type: ChannelType, **kwargs) -> Optional[discord.Message]:
        """Отправка сообщения в канал"""
        channel = await self.get_channel(channel_type)
        if not channel:
            logger.warning(f"Канал {channel_type.value} недоступен")
            return None

        try:
            # Проверяем разрешения
            if not channel.permissions_for(channel.guild.me).send_messages:
                logger.error(f"❌ Нет прав на отправку сообщений в {channel.name}")
                return None

            message = await channel.send(**kwargs)
            logger.debug(f"Сообщение отправлено в {channel.name}")
            return message
        except discord.Forbidden:
            logger.error(f"❌ Запрещено отправлять сообщения в {channel.name}")
        except discord.HTTPException as e:
            logger.error(f"❌ Ошибка отправки в {channel.name}: {e}")
        except Exception as e:
            logger.error(f"❌ Неизвестная ошибка при отправке в {channel.name}: {e}")

        return None

# =============== МОДЕЛЬ ДАННЫХ (УЛУЧШЕННАЯ) ===============
class BotData:
    """Улучшенный класс для работы с данными"""

    def __init__(self, db: firestore.firestore.Client):
        self.db = db
        self.collections = {
            'airlines': db.collection('airlines'),
            'flights': db.collection('flights'),
            'partners': db.collection('partners'),
            'tickets': db.collection('tickets'),
            'subscriptions': db.collection('subscriptions'),
            'moderation_queue': db.collection('moderation_queue'),
            'support_tickets': db.collection('support_tickets'),
            'airline_applications': db.collection('airline_applications'),
            'partner_applications': db.collection('partner_applications'),
            'bans': db.collection('bans'),
            'stats': db.collection('stats'),
            'users': db.collection('users'),
            'guilds': db.collection('guilds'),
            'commands': db.collection('commands'),
            'errors': db.collection('errors')
        }

        # Кэш данных
        self._cache = {}
        self._cache_timestamps = {}

        # Статистика
        self.stats = {
            'total_airlines': 0,
            'total_flights': 0,
            'active_flights': 0,
            'total_users': 0,
            'total_guilds': 0,
            'open_tickets': 0,
            'command_count': 0,
            'error_count': 0
        }

        # История операций
        self.operation_history = deque(maxlen=100)

    async def initialize(self):
        """Инициализация данных"""
        logger.info("📊 Инициализация данных...")

        # Загружаем статистику
        await self.refresh_stats()

        # Загружаем кэшированные данные
        await self.cache_frequent_data()

        logger.info(f"✅ Данные инициализированы: {len(self.collections)} коллекций")

    async def refresh_stats(self):
        """Обновление статистики"""
        try:
            tasks = [
                self._count_documents('airlines'),
                self._count_documents('flights'),
                self._count_active_flights(),
                self._count_documents('users'),
                self._count_documents('guilds'),
                self._count_open_tickets(),
                self._count_documents('commands'),
                self._count_documents('errors')
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Обновляем статистику
            self.stats.update({
                'total_airlines': results[0] if not isinstance(results[0], Exception) else 0,
                'total_flights': results[1] if not isinstance(results[1], Exception) else 0,
                'active_flights': results[2] if not isinstance(results[2], Exception) else 0,
                'total_users': results[3] if not isinstance(results[3], Exception) else 0,
                'total_guilds': results[4] if not isinstance(results[4], Exception) else 0,
                'open_tickets': results[5] if not isinstance(results[5], Exception) else 0,
                'command_count': results[6] if not isinstance(results[6], Exception) else 0,
                'error_count': results[7] if not isinstance(results[7], Exception) else 0
            })

            # Сохраняем статистику в Firebase
            await self._save_stats_to_firebase()

            logger.debug("📊 Статистика обновлена")

        except Exception as e:
            logger.error(f"Ошибка обновления статистики: {e}")

    async def _count_documents(self, collection_name: str) -> int:
        """Подсчет документов в коллекции"""
        try:
            docs = self.collections[collection_name].count().get()
            return docs[0][0].value if docs else 0
        except Exception as e:
            logger.error(f"Ошибка подсчета документов в {collection_name}: {e}")
            return 0

    async def _count_active_flights(self) -> int:
        """Подсчет активных рейсов"""
        try:
            now = datetime.now()
            today_start = datetime(now.year, now.month, now.day)

            query = self.collections['flights'].where('departure_time', '>=', today_start)
            docs = query.count().get()
            return docs[0][0].value if docs else 0
        except Exception as e:
            logger.error(f"Ошибка подсчета активных рейсов: {e}")
            return 0

    async def _count_open_tickets(self) -> int:
        """Подсчет открытых тикетов"""
        try:
            query = self.collections['support_tickets'].where('status', '==', 'open')
            docs = query.count().get()
            return docs[0][0].value if docs else 0
        except Exception as e:
            logger.error(f"Ошибка подсчета открытых тикетов: {e}")
            return 0

    async def _save_stats_to_firebase(self):
        """Сохранение статистики в Firebase"""
        try:
            stats_ref = self.collections['stats'].document('bot_stats')
            await asyncio.to_thread(
                stats_ref.set,
                {
                    **self.stats,
                    'last_updated': datetime.now(),
                    'bot_version': '2.0.0'
                },
                merge=True
            )
        except Exception as e:
            logger.error(f"Ошибка сохранения статистики в Firebase: {e}")

    async def cache_frequent_data(self):
        """Кэширование часто используемых данных"""
        try:
            # Кэшируем активные авиакомпании
            # Используем list() чтобы сразу получить данные и избежать StreamGenerator ошибки
            active_airlines_query = await asyncio.to_thread(
                lambda: list(self.collections['airlines'].where('active', '==', True).limit(50).stream())
            )
            airlines = [doc.to_dict() for doc in active_airlines_query]

            self._cache['active_airlines'] = airlines
            self._cache_timestamps['active_airlines'] = datetime.now()

            # Кэшируем популярные рейсы
            # Исправлено: убрали асинхронный цикл для StreamGenerator
            popular_flights_query = await asyncio.to_thread(
                lambda: list(self.collections['flights'].order_by('bookings', direction=firestore.Query.DESCENDING).limit(20).stream())
            )
            flights = [doc.to_dict() for doc in popular_flights_query]

            self._cache['popular_flights'] = flights
            self._cache_timestamps['popular_flights'] = datetime.now()

            logger.debug(f"Кэшировано: {len(airlines)} авиакомпаний, {len(flights)} рейсов")

        except Exception as e:
            logger.error(f"Ошибка кэширования данных: {e}")

    def get_cached(self, key: str, max_age: int = 300):
        """Получение данных из кэша"""
        if key not in self._cache:
            return None

        timestamp = self._cache_timestamps.get(key)
        if not timestamp:
            return None

        age = (datetime.now() - timestamp).seconds
        if age > max_age:
            return None

        return self._cache[key]

    def log_operation(self, operation: str, details: Dict[str, Any]):
        """Логирование операции"""
        log_entry = {
            'timestamp': datetime.now(),
            'operation': operation,
            'details': details
        }
        self.operation_history.append(log_entry)

# =============== МЕНЕДЖЕР СТАТУСОВ ===============
class DynamicStatusManager:
    """Улучшенный менеджер динамического статуса"""

    def __init__(self, bot):
        self.bot = bot
        self.status_manager = StatusManager(bot)

        # Конфигурация интервалов (в секундах)
        self.intervals = {
            "holiday": 45,       # Праздничные
            "seasonal": 35,      # Сезонные
            "weekday": 25,       # Дни недели
            "time_based": 20,    # По времени
            "regular": 15,       # Обычные
            "animated": 12,      # Анимированные
            "meme": 18,          # Мемные
            "absurd": 22,        # Абсурдные
            "sassy": 16,         # Дерзкие
            "default": 20        # По умолчанию
        }

        # Минимальный и максимальный интервалы
        self.min_interval = 10
        self.max_interval = 60

        # Состояние
        self.current_category = "default"
        self.current_interval = self.intervals["default"]
        self.is_running = False
        self.status_task = None

        # Активность
        self.last_activity = datetime.now()
        self.activity_counter = 0

        # История
        self.status_history = deque(maxlen=20)
        self.performance_log = deque(maxlen=50)

        # Ограничитель частоты
        self.last_status_change = datetime.now()
        self.min_change_interval = 5  # Минимум 5 секунд между сменами

        # Сессия для HTTP-запросов
        self.session = None

    async def start(self):
        """Запуск менеджера статусов"""
        if self.is_running:
            logger.warning("Менеджер статусов уже запущен")
            return

        self.is_running = True

        # Создаем HTTP-сессию
        self.session = aiohttp.ClientSession()

        # Запускаем задачу
        self.status_task = asyncio.create_task(self._smart_status_updater())

        logger.info("🚀 Динамический менеджер статусов запущен")

    async def stop(self):
        """Остановка менеджера статусов"""
        if not self.is_running:
            return

        self.is_running = False

        if self.status_task:
            self.status_task.cancel()
            try:
                await self.status_task
            except asyncio.CancelledError:
                pass

        if self.session:
            await self.session.close()

        logger.info("🛑 Менеджер статусов остановлен")

    async def _smart_status_updater(self):
        """Умный планировщик обновления статусов"""
        logger.info("🔄 Планировщик статусов запущен")

        while self.is_running:
            try:
                # Проверяем готовность бота
                if not self.bot.is_ready():
                    await asyncio.sleep(10)
                    continue

                # Рассчитываем адаптивный интервал
                interval = await self._calculate_adaptive_interval()

                # Ждем до следующего обновления
                await asyncio.sleep(interval)

                # Обновляем статус
                await self.update_status()

                # Периодически сбрасываем счетчики
                if self.activity_counter > 1000:
                    self.activity_counter = 0
                    logger.debug("Счетчик активности сброшен")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в планировщике статусов: {e}")
                await asyncio.sleep(30)

    async def _calculate_adaptive_interval(self) -> float:
        """Рассчет адаптивного интервала"""
        base_interval = self.current_interval

        # Корректировка на основе активности
        time_since_activity = (datetime.now() - self.last_activity).seconds

        if time_since_activity < 60:  # Высокая активность
            multiplier = 0.5  # Вдвое чаще
        elif time_since_activity < 300:  # Средняя активность
            multiplier = 0.75
        else:  # Низкая активность
            multiplier = 1.0

        # Корректировка на основе времени суток
        hour = datetime.now().hour
        if 0 <= hour < 6:  # Ночь
            multiplier *= 1.5  # Реже
        elif 18 <= hour < 24:  # Вечер
            multiplier *= 0.8  # Чаще

        adaptive_interval = base_interval * multiplier

        # Ограничиваем интервал
        adaptive_interval = max(self.min_interval, min(self.max_interval, adaptive_interval))

        return adaptive_interval

    async def update_status(self):
        """Обновление статуса бота"""
        try:
            # Проверяем ограничение частоты
            now = datetime.now()
            if (now - self.last_status_change).seconds < self.min_change_interval:
                return

            # Получаем статистику
            stats = await self.status_manager.get_bot_stats()

            # Получаем статус
            status_data = self.status_manager.get_status_with_category(stats)
            category = status_data.get("category", "default")

            # Обновляем текущие значения
            self.current_category = category
            self.current_interval = self.intervals.get(category, self.intervals["default"])

            # Устанавливаем статус
            await self._set_discord_status(status_data)

            # Логируем
            self._log_status_change(status_data, category)

            # Обновляем время последнего изменения
            self.last_status_change = now

            # 10% шанс на специальный эффект
            if random.random() < 0.1:
                await self._special_effect()

        except Exception as e:
            logger.error(f"Ошибка обновления статуса: {e}")

    async def _set_discord_status(self, status_data: Dict[str, Any]):
        """Установка статуса в Discord"""
        try:
            # Маппинг типов активности
            activity_map = {
                "playing": discord.ActivityType.playing,
                "watching": discord.ActivityType.watching,
                "listening": discord.ActivityType.listening,
                "competing": discord.ActivityType.competing,
                "streaming": discord.ActivityType.streaming
            }

            activity_type = activity_map.get(
                status_data["type"], 
                discord.ActivityType.playing
            )

            # Для streaming нужен URL
            if activity_type == discord.ActivityType.streaming:
                activity = discord.Streaming(
                    name=status_data["name"],
                    url="https://twitch.tv/aviasales",
                    game="Aviasales Roblox"
                )
            else:
                activity = discord.Activity(
                    type=activity_type,
                    name=status_data["name"],
                    details="Система управления авиарейсами",
                    state=f"Категория: {status_data.get('category', 'default')}",
                    timestamps={"start": datetime.now().timestamp()},
                    assets={
                        "large_image": "aviasales_logo",
                        "large_text": "Aviasales Roblox",
                        "small_image": "online",
                        "small_text": "Онлайн"
                    }
                )

            # Устанавливаем статус
            await self.bot.change_presence(
                activity=activity,
                status=discord.Status.online
            )

            logger.debug(f"Статус обновлен: {status_data['name']}")

        except Exception as e:
            logger.error(f"Ошибка установки Discord статуса: {e}")
            raise

    async def _special_effect(self):
        """Специальные эффекты для статуса"""
        effects = [
            self._double_blink,
            self._quick_sequence,
            self._holiday_surprise
        ]

        effect = random.choice(effects)
        try:
            await effect()
        except Exception as e:
            logger.debug(f"Эффект не сработал: {e}")

    async def _double_blink(self):
        """Эффект двойного моргания"""
        original_status = await self._get_current_activity()

        # Первый быстрый статус
        quick_status = {
            "type": "playing",
            "name": random.choice(["⚡", "✨", "🌟"]) + " Мгновение...",
            "category": "animated"
        }
        await self._set_discord_status(quick_status)
        await asyncio.sleep(1.5)

        # Второй быстрый статус
        quick_status["name"] = random.choice(["💫", "🌀", "🌈"]) + " И снова!"
        await self._set_discord_status(quick_status)
        await asyncio.sleep(1.5)

        # Возвращаем оригинальный статус
        if original_status:
            await self._set_discord_status(original_status)

    async def _quick_sequence(self):
        """Быстрая последовательность статусов"""
        sequences = [
            ["✈️", "🛫", "🌍", "🛬", "💺"],
            ["🔍", "💰", "🎫", "✈️", "🌴"],
            ["⌛", "⚡", "✅", "🎉", "🏆"]
        ]

        sequence = random.choice(sequences)
        for emoji in sequence:
            status = {
                "type": "playing",
                "name": f"{emoji} Быстрая смена...",
                "category": "animated"
            }
            await self._set_discord_status(status)
            await asyncio.sleep(0.8)

    async def _holiday_surprise(self):
        """Праздничный сюрприз"""
        holidays = {
            "🎄": "Новогоднее настроение!",
            "🎃": "Хэллоуин уже близко!",
            "❤️": "Любовь в воздухе!",
            "🎉": "Время праздновать!"
        }

        emoji, text = random.choice(list(holidays.items()))
        status = {
            "type": "playing",
            "name": f"{emoji} {text}",
            "category": "holiday"
        }

        await self._set_discord_status(status)
        await asyncio.sleep(3)

    async def _get_current_activity(self) -> Optional[Dict[str, Any]]:
        """Получение текущей активности"""
        if not self.bot.activity:
            return None

        activity_map_reverse = {
            discord.ActivityType.playing: "playing",
            discord.ActivityType.watching: "watching",
            discord.ActivityType.listening: "listening",
            discord.ActivityType.competing: "competing",
            discord.ActivityType.streaming: "streaming"
        }

        return {
            "type": activity_map_reverse.get(type(self.bot.activity), "playing"),
            "name": self.bot.activity.name,
            "category": "current"
        }

    def _log_status_change(self, status_data: Dict[str, Any], category: str):
        """Логирование смены статуса"""
        log_entry = {
            "timestamp": datetime.now(),
            "status": status_data["name"],
            "category": category,
            "type": status_data["type"]
        }

        self.status_history.append(log_entry)

        # Периодическое логирование
        if len(self.status_history) % 10 == 0:
            logger.info(f"📊 История статусов: {len(self.status_history)} записей")

    def record_activity(self):
        """Запись активности пользователя"""
        self.last_activity = datetime.now()
        self.activity_counter += 1

        # 5% шанс на быстрое обновление
        if random.random() < 0.05:
            asyncio.create_task(self._trigger_quick_update())

    async def _trigger_quick_update(self):
        """Триггер быстрого обновления"""
        if not self.is_running:
            return

        # Ждем минимум 2 секунды после последнего изменения
        if (datetime.now() - self.last_status_change).seconds < 2:
            return

        await self.update_status()

    def get_status_info(self) -> Dict[str, Any]:
        """Получение информации о статусе"""
        return {
            "running": self.is_running,
            "current_category": self.current_category,
            "current_interval": self.current_interval,
            "activity_counter": self.activity_counter,
            "last_activity": self.last_activity.strftime("%H:%M:%S"),
            "status_history_count": len(self.status_history),
            "last_status_change": self.last_status_change.strftime("%H:%M:%S")
        }

# =============== МЕНЕДЖЕР МОДУЛЕЙ ===============
class ModuleManager:
    """Менеджер для загрузки и управления модулями"""

    def __init__(self, bot):
        self.bot = bot
        self.modules = {}
        self.failed_modules = {}
        self.module_stats = {}

        # Список модулей для загрузки
        self.MODULES = [
            'cogs.airlines',
            'cogs.flights',
            'cogs.passengers',
            'cogs.admin',
            'cogs.partners',
            'cogs.support',
            'cogs.stats',
            'cogs.utils',
            'cogs.fun'
        ]

    async def load_all(self):
        """Загрузка всех модулей параллельно"""
        logger.info("📦 Загрузка модулей...")

        results = {
            'loaded': [],
            'failed': [],
            'skipped': []
        }

        async def load_module(module_path):
            try:
                if not await self._module_exists(module_path):
                    return ('skipped', module_path, "Модуль не найден")

                await self.bot.load_extension(module_path)
                self.modules[module_path] = {
                    'loaded': datetime.now(),
                    'status': 'loaded'
                }
                return ('loaded', module_path, None)

            except commands.ExtensionAlreadyLoaded:
                return ('skipped', module_path, "Уже загружен")
            except Exception as e:
                self.failed_modules[module_path] = str(e)
                return ('failed', module_path, str(e))

        # Загружаем модули параллельно
        tasks = [load_module(m) for m in self.MODULES]
        module_results = await asyncio.gather(*tasks)

        for status, path, error in module_results:
            results[status].append(path)
            if status == 'loaded':
                logger.info(f"✅ Модуль {path} загружен")
            elif status == 'failed':
                logger.error(f"❌ Ошибка загрузки модуля {path}: {error}")
            else:
                logger.warning(f"⚠️ Модуль {path} пропущен: {error}")

        logger.info(f"📊 Итоги загрузки: {len(results['loaded'])} загружено, "
                   f"{len(results['failed'])} ошибок, {len(results['skipped'])} пропущено")

        return results

    async def _module_exists(self, module_path: str) -> bool:
        """Проверка существования модуля"""
        # Простая проверка - пытаемся импортировать
        try:
            __import__(module_path.replace('.', '/').replace('cogs/', 'cogs.'))
            return True
        except ImportError:
            return False

    async def reload_module(self, module_path: str) -> bool:
        """Перезагрузка модуля"""
        try:
            await self.bot.reload_extension(module_path)
            self.modules[module_path] = {
                'loaded': datetime.now(),
                'status': 'reloaded'
            }
            logger.info(f"🔄 Модуль {module_path} перезагружен")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка перезагрузки модуля {module_path}: {e}")
            return False

    async def unload_module(self, module_path: str) -> bool:
        """Выгрузка модуля"""
        try:
            await self.bot.unload_extension(module_path)
            if module_path in self.modules:
                del self.modules[module_path]
            logger.info(f"📤 Модуль {module_path} выгружен")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка выгрузки модуля {module_path}: {e}")
            return False

    def get_module_info(self) -> Dict[str, Any]:
        """Получение информации о модулях"""
        return {
            'total_modules': len(self.MODULES),
            'loaded': len(self.modules),
            'failed': len(self.failed_modules),
            'modules': list(self.modules.keys()),
            'failed_list': list(self.failed_modules.keys())
        }

# =============== ОСНОВНОЙ КЛАСС БОТА ===============
class AviasalesBot(commands.Bot):
    """Улучшенный главный класс бота"""

    def __init__(self, config: ConfigManager):
        # Настройка intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.presences = True
        intents.message_content = True

        super().__init__(
            command_prefix=config.get('PREFIX', '/'),
            intents=intents,
            help_command=None,
            case_insensitive=True,
            strip_after_prefix=True,
            allowed_mentions=discord.AllowedMentions(
                everyone=False,
                roles=False,
                users=True,
                replied_user=True
            )
        )

        # Конфигурация
        self.config = config
        self.config_manager = config

        # Менеджеры
        self.firebase_manager = None
        self.channel_manager = None
        self.module_manager = None
        self.status_manager = None
        self.data = None

        # Время запуска
        self.start_time = None
        self.uptime = timedelta(0)

        # Статистика
        self.stats = {
            'commands_processed': 0,
            'messages_received': 0,
            'errors_handled': 0,
            'users_served': 0,
            'guilds_served': 0
        }

        # Сессия для HTTP-запросов
        self.http_session = None

        # Фоновые задачи
        self.background_tasks = []

        # Состояние бота
        self.bot_status = BotStatus.STARTING
        self.maintenance_mode = config.get('MAINTENANCE_MODE', False)

        # Кэш
        self.command_cache = {}
        self.user_cache = {}

        # Настройка логирования
        self.logger = logger

    async def setup_hook(self):
        """Настройка бота перед запуском"""
        self.logger.info("⚙️ Настройка бота...")

        # Устанавливаем статус
        self.bot_status = BotStatus.STARTING

        # Создаем HTTP-сессию
        self.http_session = aiohttp.ClientSession()

        # Инициализируем Firebase
        self.firebase_manager = FirebaseManager()
        db = self.firebase_manager.initialize(self.config.get('FIREBASE_CONFIG'))

        # Инициализируем данные
        self.data = BotData(db)
        await self.data.initialize()

        # Инициализируем менеджер каналов
        self.channel_manager = ChannelManager(self, self.config)

        # Инициализируем менеджер модулей
        self.module_manager = ModuleManager(self)

        # Инициализируем менеджер статусов
        self.status_manager = DynamicStatusManager(self)

        self.logger.info("✅ Настройка завершена")

    async def on_ready(self):
        """Событие готовности бота"""
        self.start_time = datetime.now()
        self.bot_status = BotStatus.RUNNING

        self.logger.info(f'🚀 Бот {self.user} запущен!')
        self.logger.info(f'📊 Серверов: {len(self.guilds)} | Пользователей: {len(self.users)}')
        self.logger.info(f'🆔 ID бота: {self.user.id}')
        self.logger.info(f'👤 Имя бота: {self.user.name}#{self.user.discriminator}')

        # Обновляем статистику
        self.stats.update({
            'guilds_served': len(self.guilds),
            'users_served': len(self.users)
        })

        # Инициализируем каналы
        await self.channel_manager.initialize()

        # Загружаем модули
        await self.module_manager.load_all()

        # Синхронизируем команды
        await self._sync_commands()

        # Запускаем менеджер статусов
        await self.status_manager.start()

        # Запускаем фоновые задачи
        await self._start_background_tasks()

        # Отправляем сообщение о запуске
        await self._send_startup_message()

        # Специальный статус при запуске
        await self.status_manager.update_status()

        self.logger.info("✅ Бот полностью готов к работе!")

    async def _sync_commands(self):
        """Синхронизация команд"""
        try:
            synced = await self.tree.sync()
            self.logger.info(f'✅ Синхронизировано {len(synced)} команд')

            if synced:
                self.logger.debug("Список команд:")
                for cmd in synced:
                    self.logger.debug(f"  - /{cmd.name}")
        except Exception as e:
            self.logger.error(f'❌ Ошибка синхронизации команд: {e}')

    async def _start_background_tasks(self):
        """Запуск фоновых задач"""
        @tasks.loop(minutes=5)
        async def update_stats():
            try:
                await self.data.refresh_stats()
                self.logger.debug("📊 Статистика обновлена")
            except Exception as e:
                self.logger.error(f"Ошибка обновления статистики: {e}")

        @tasks.loop(hours=1)
        async def update_uptime():
            self.uptime = datetime.now() - self.start_time
            self.logger.info(f"⏱️ Аптайм: {self.uptime}")

        @tasks.loop(minutes=15)
        async def cleanup_cache():
            try:
                # Очищаем старые записи из кэша
                now = datetime.now()
                keys_to_remove = []

                for key, timestamp in self.data._cache_timestamps.items():
                    if (now - timestamp).seconds > 3600:  # 1 час
                        keys_to_remove.append(key)

                for key in keys_to_remove:
                    del self.data._cache[key]
                    del self.data._cache_timestamps[key]

                if keys_to_remove:
                    self.logger.debug(f"🧹 Очищен кэш: {len(keys_to_remove)} записей")
            except Exception as e:
                self.logger.error(f"Ошибка очистки кэша: {e}")

        @tasks.loop(minutes=30)
        async def check_health():
            """Проверка здоровья бота"""
            try:
                health_status = await self._check_health()
                if health_status['status'] != 'healthy':
                    self.logger.warning(f"⚠️ Проблемы со здоровьем: {health_status}")
            except Exception as e:
                self.logger.error(f"Ошибка проверки здоровья: {e}")

        # Запускаем задачи
        update_stats.start()
        update_uptime.start()
        cleanup_cache.start()
        check_health.start()

        self.background_tasks = [update_stats, update_uptime, cleanup_cache, check_health]
        self.logger.info(f"✅ Запущено {len(self.background_tasks)} фоновых задач")

    async def _check_health(self) -> Dict[str, Any]:
        """Проверка здоровья бота"""
        checks = {
            'discord_connected': self.is_ready(),
            'firebase_connected': self.firebase_manager.db is not None,
            'status_manager_running': self.status_manager.is_running if self.status_manager else False,
            'http_session_open': not self.http_session.closed if self.http_session else False,
            'tasks_running': all(task.is_running() for task in self.background_tasks),
            'memory_usage': self._get_memory_usage()
        }

        status = 'healthy'
        if not all(checks.values()):
            status = 'unhealthy'

        return {
            'status': status,
            'checks': checks,
            'timestamp': datetime.now()
        }

    def _get_memory_usage(self) -> Dict[str, float]:
        """Получение информации об использовании памяти"""
        try:
            import psutil
            process = psutil.Process()
            memory_info = process.memory_info()

            return {
                'rss_mb': memory_info.rss / 1024 / 1024,
                'vms_mb': memory_info.vms / 1024 / 1024,
                'percent': process.memory_percent()
            }
        except ImportError:
            return {'error': 'psutil не установлен'}
        except Exception as e:
            return {'error': str(e)}

    async def _send_startup_message(self):
        """Отправка сообщения о запуске"""
        try:
            # Создаем embed
            embed = discord.Embed(
                title="🚀 Aviasales Bot Запущен!",
                description="Бот успешно запущен и готов к работе.",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )

            embed.add_field(name="🆔 Бот", value=f"{self.user.name}#{self.user.discriminator}", inline=True)
            embed.add_field(name="👤 Владелец", value=f"<@{self.config.get('OWNER_ID')}>", inline=True)
            embed.add_field(name="📊 Серверов", value=len(self.guilds), inline=True)
            embed.add_field(name="👥 Пользователей", value=len(self.users), inline=True)
            embed.add_field(name="⚡ Пинг", value=f"{round(self.latency * 1000)}ms", inline=True)
            embed.add_field(name="📦 Модулей", value=len(self.module_manager.modules), inline=True)

            embed.set_footer(text=f"ID: {self.user.id}")
            embed.set_thumbnail(url=self.user.avatar.url if self.user.avatar else self.user.default_avatar.url)

            # Отправляем в канал логирования
            await self.channel_manager.send_to_channel(
                ChannelType.LOGS,
                embed=embed
            )

        except Exception as e:
            self.logger.error(f"Ошибка отправки сообщения о запуске: {e}")

    async def on_message(self, message):
        """Обработка входящих сообщений"""
        # Игнорируем сообщения от ботов
        if message.author.bot:
            return

        # Записываем активность
        if self.status_manager:
            self.status_manager.record_activity()

        # Обновляем статистику
        self.stats['messages_received'] += 1

        # Продолжаем обычную обработку
        await self.process_commands(message)

    async def on_command_completion(self, ctx):
        """Событие успешного выполнения команды"""
        self.stats['commands_processed'] += 1

        # Логируем команду
        self.logger.info(f"✅ Команда выполнена: /{ctx.command.name} "
                        f"пользователем {ctx.author} в {ctx.guild.name if ctx.guild else 'DM'}")

        # Сохраняем в Firebase
        if self.data:
            try:
                await asyncio.to_thread(
                    self.data.collections['commands'].add,
                    {
                        'user_id': str(ctx.author.id),
                        'command': ctx.command.name,
                        'guild_id': str(ctx.guild.id) if ctx.guild else None,
                        'channel_id': str(ctx.channel.id),
                        'timestamp': datetime.now(),
                        'success': True
                    }
                )
            except Exception as e:
                self.logger.error(f"Ошибка сохранения команды в Firebase: {e}")

    async def on_command_error(self, ctx, error):
        """Обработка ошибок команд"""
        self.stats['errors_handled'] += 1

        # Игнорируем некоторые ошибки
        if isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ У вас недостаточно прав для выполнения этой команды!", ephemeral=True)
            return
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Недостаточно аргументов! Используйте: `/{ctx.command.name} {ctx.command.signature}`", ephemeral=True)
            return
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Неверные аргументы команды!", ephemeral=True)
            return
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Эта команда на перезарядке! Попробуйте через {error.retry_after:.1f} секунд.", ephemeral=True)
            return
        elif isinstance(error, commands.NotOwner):
            await ctx.send("❌ Эта команда доступна только владельцу бота!", ephemeral=True)
            return

        # Логируем ошибку
        self.logger.error(f"Ошибка команды {ctx.command.name}: {error}")

        # Сохраняем ошибку в Firebase
        if self.data:
            try:
                error_data = {
                    'user_id': str(ctx.author.id),
                    'command': ctx.command.name if ctx.command else 'unknown',
                    'error': str(error),
                    'traceback': traceback.format_exc(),
                    'timestamp': datetime.now(),
                    'guild_id': str(ctx.guild.id) if ctx.guild else None,
                    'channel_id': str(ctx.channel.id)
                }

                await asyncio.to_thread(
                    self.data.collections['errors'].add,
                    error_data
                )
            except Exception as e:
                self.logger.error(f"Ошибка сохранения ошибки в Firebase: {e}")

        # Отправляем пользователю сообщение об ошибке
        embed = discord.Embed(
            title="❌ Произошла ошибка",
            description="При выполнении команды произошла непредвиденная ошибка.",
            color=discord.Color.red()
        )

        embed.add_field(name="Ошибка", value=f"```{str(error)[:100]}```", inline=False)
        embed.add_field(name="Что делать?", value="1. Проверьте правильность команды\n2. Попробуйте позже\n3. Обратитесь в поддержку", inline=False)
        embed.set_footer(text="Ошибка зарегистрирована и будет исправлена")

        try:
            await ctx.send(embed=embed, ephemeral=True)
        except:
            pass

    async def on_guild_join(self, guild):
        """Событие присоединения к серверу"""
        self.logger.info(f"➕ Присоединился к серверу: {guild.name} (ID: {guild.id})")

        # Обновляем статистику
        self.stats['guilds_served'] += 1

        # Отправляем приветственное сообщение
        try:
            embed = discord.Embed(
                title="👋 Спасибо за добавление!",
                description="Aviasales Bot поможет вам управлять авиакомпаниями и рейсами в Roblox.",
                color=discord.Color.blue()
            )

            embed.add_field(name="Основные команды", value="`/help` - список команд", inline=False)
            embed.add_field(name="Настройка", value="Настройте каналы в настройках сервера", inline=False)
            embed.add_field(name="Поддержка", value=f"[Сервер поддержки]({self.config.get('SUPPORT_SERVER')})", inline=False)

            # Ищем канал для отправки
            channel = guild.system_channel or guild.text_channels[0] if guild.text_channels else None

            if channel:
                await channel.send(embed=embed)
        except Exception as e:
            self.logger.error(f"Ошибка отправки приветственного сообщения: {e}")

    async def on_guild_remove(self, guild):
        """Событие удаления с сервера"""
        self.logger.info(f"➖ Покинул сервер: {guild.name} (ID: {guild.id})")
        self.stats['guilds_served'] -= 1

    async def close(self):
        """Корректное закрытие бота"""
        self.logger.info("🛑 Завершение работы бота...")
        self.bot_status = BotStatus.STOPPING

        # Останавливаем менеджер статусов
        if self.status_manager:
            await self.status_manager.stop()

        # Останавливаем фоновые задачи
        for task in self.background_tasks:
            task.cancel()

        # Закрываем HTTP-сессию
        if self.http_session:
            await self.http_session.close()

        # Сохраняем финальную статистику
        await self._save_final_stats()

        # Закрываем бота
        await super().close()

        self.logger.info("👋 Бот завершил работу")

    async def _save_final_stats(self):
        """Сохранение финальной статистики"""
        try:
            if self.data:
                final_stats = {
                    'uptime': str(self.uptime),
                    'total_commands': self.stats['commands_processed'],
                    'total_messages': self.stats['messages_received'],
                    'total_errors': self.stats['errors_handled'],
                    'total_guilds': self.stats['guilds_served'],
                    'total_users': self.stats['users_served'],
                    'shutdown_time': datetime.now()
                }

                await asyncio.to_thread(
                    self.data.collections['stats'].document('shutdown_stats').set,
                    final_stats
                )
        except Exception as e:
            self.logger.error(f"Ошибка сохранения финальной статистики: {e}")

    def get_bot_info(self) -> Dict[str, Any]:
        """Получение информации о боте"""
        return {
            'status': self.bot_status.value,
            'uptime': str(self.uptime) if self.uptime else '0:00:00',
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'stats': self.stats.copy(),
            'version': '2.0.0',
            'maintenance_mode': self.maintenance_mode,
            'latency': round(self.latency * 1000, 2),
            'guild_count': len(self.guilds),
            'user_count': len(self.users),
            'module_info': self.module_manager.get_module_info() if self.module_manager else None,
            'status_info': self.status_manager.get_status_info() if self.status_manager else None
        }

# =============== ЗАПУСК БОТА ===============
async def main():
    """Основная функция запуска бота"""
    try:
        # Инициализация
        logger.info("=" * 50)
        logger.info("🚀 Запуск Aviasales Bot v2.0.0")
        logger.info("=" * 50)

        # Загрузка конфигурации
        config_manager = ConfigManager()
        config = config_manager.load()

        # Создание бота
        bot = AviasalesBot(config_manager)

        # Запуск бота
        await bot.start(config['DISCORD_TOKEN'])

    except KeyboardInterrupt:
        logger.info("👋 Получен сигнал прерывания")
    except discord.LoginFailure:
        logger.critical("❌ Неверный токен Discord бота!")
    except Exception as e:
        logger.critical(f"❌ Критическая ошибка при запуске бота: {e}")
        logger.critical(traceback.format_exc())
    finally:
        # Корректное завершение
        if 'bot' in locals() and isinstance(bot, AviasalesBot):
            await bot.close()

if __name__ == "__main__":
    # Создаем директории для логов
    os.makedirs('logs', exist_ok=True)

    # Запускаем бота
    asyncio.run(main())
