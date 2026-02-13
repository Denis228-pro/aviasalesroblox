import asyncio
import aiohttp
import json
from typing import Optional, Dict, Any, List
import re
from datetime import datetime, timedelta

class AirportService:
    """Сервис для автоматического определения кодов аэропортов через API"""

    def __init__(self, bot):
        self.bot = bot
        self.session = None
        self.cache = {}
        self.cache_ttl = 86400  # 24 часа кэширования
        self.last_request = {}

        # API для поиска аэропортов (публичные, без API ключа)
        self.api_endpoints = [
            {
                'name': 'AviationAPI',
                'url': 'https://api.aviationapi.com/v1/airports?apt=',
                'parser': self._parse_aviationapi
            },
            {
                'name': 'OpenSky',
                'url': 'https://opensky-network.org/api/airports',
                'parser': self._parse_opensky
            },
            {
                'name': 'OurAirports',
                'url': 'https://davidmegginson.github.io/ourairports-data/airports.csv',
                'parser': self._parse_ourairports
            }
        ]

        # Регулярные выражения для извлечения IATA/ICAO кодов из текста
        self.iata_pattern = re.compile(r'\b[A-Z]{3}\b')
        self.icao_pattern = re.compile(r'\b[A-Z]{4}\b')

    async def initialize(self):
        """Инициализация сессии"""
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

    async def close(self):
        """Закрытие сессии"""
        if self.session:
            await self.session.close()

    async def search_airport_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Поиск аэропорта по названию"""
        # Проверяем кэш
        cache_key = f"name:{name.lower().strip()}"
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if (datetime.now() - cached_data['cached_at']).seconds < self.cache_ttl:
                return cached_data['data']

        # Ограничение частоты запросов
        if cache_key in self.last_request:
            time_since_last = (datetime.now() - self.last_request[cache_key]).seconds
            if time_since_last < 2:  # 2 секунды между запросами
                await asyncio.sleep(2 - time_since_last)

        self.last_request[cache_key] = datetime.now()

        # Пытаемся найти через разные API
        for endpoint in self.api_endpoints:
            try:
                result = await self._query_api(endpoint, name)
                if result and result.get('iata') and result.get('icao'):
                    # Кэшируем результат
                    self.cache[cache_key] = {
                        'data': result,
                        'cached_at': datetime.now()
                    }
                    return result
            except Exception as e:
                print(f"Ошибка API {endpoint['name']}: {e}")
                continue

        # Если API не сработали, попробуем извлечь коды из названия
        return await self._extract_from_text(name)

    async def search_airport_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Поиск аэропорта по коду (IATA или ICAO)"""
        code = code.upper().strip()

        # Проверяем кэш
        cache_key = f"code:{code}"
        if cache_key in self.cache:
            cached_data = self.cache[cache_key]
            if (datetime.now() - cached_data['cached_at']).seconds < self.cache_ttl:
                return cached_data['data']

        # Определяем тип кода
        if len(code) == 3:
            search_type = 'iata'
        elif len(code) == 4:
            search_type = 'icao'
        else:
            return None

        # Ищем через API
        for endpoint in self.api_endpoints:
            try:
                result = await self._query_api_by_code(endpoint, code, search_type)
                if result:
                    self.cache[cache_key] = {
                        'data': result,
                        'cached_at': datetime.now()
                    }
                    return result
            except Exception as e:
                print(f"Ошибка API {endpoint['name']}: {e}")
                continue

        return None

    async def _query_api(self, endpoint: Dict, query: str) -> Optional[Dict[str, Any]]:
        """Запрос к API"""
        try:
            if endpoint['name'] == 'OurAirports':
                # Для CSV файла - нужно скачать и парсить локально
                return await self._download_and_search_ourairports(query)

            url = f"{endpoint['url']}{query}"
            async with self.session.get(url) as response:
                if response.status == 200:
                    if 'json' in response.headers.get('Content-Type', ''):
                        data = await response.json()
                    else:
                        data = await response.text()

                    return endpoint['parser'](data, query)
        except Exception as e:
            print(f"Ошибка запроса к {endpoint['name']}: {e}")
            return None

    async def _query_api_by_code(self, endpoint: Dict, code: str, code_type: str) -> Optional[Dict[str, Any]]:
        """Запрос к API по коду"""
        try:
            if endpoint['name'] == 'OurAirports':
                return await self._download_and_search_ourairports_by_code(code, code_type)

            url = f"{endpoint['url']}?{code_type}={code}"
            async with self.session.get(url) as response:
                if response.status == 200:
                    if 'json' in response.headers.get('Content-Type', ''):
                        data = await response.json()
                    else:
                        data = await response.text()

                    return endpoint['parser'](data, code)
        except Exception as e:
            print(f"Ошибка запроса к {endpoint['name']}: {e}")
            return None

    async def _download_and_search_ourairports(self, query: str) -> Optional[Dict[str, Any]]:
        """Скачивание и поиск в OurAirports CSV"""
        try:
            url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
            async with self.session.get(url) as response:
                if response.status == 200:
                    csv_data = await response.text()

                    # Ищем в CSV по названию
                    query_lower = query.lower()
                    for line in csv_data.split('\n')[1:]:  # Пропускаем заголовок
                        if not line:
                            continue

                        parts = line.split(',')
                        if len(parts) >= 3:
                            name = parts[3].strip('"').lower()
                            if query_lower in name:
                                iata = parts[1].strip('"') if parts[1].strip('"') != '""' else None
                                icao = parts[2].strip('"') if parts[2].strip('"') != '""' else None

                                if iata and icao:
                                    return {
                                        'name': parts[3].strip('"'),
                                        'city': parts[10].strip('"') if len(parts) > 10 else '',
                                        'country': parts[8].strip('"') if len(parts) > 8 else '',
                                        'iata': iata,
                                        'icao': icao,
                                        'latitude': parts[4].strip('"') if len(parts) > 4 else '',
                                        'longitude': parts[5].strip('"') if len(parts) > 5 else ''
                                    }
        except Exception as e:
            print(f"Ошибка поиска в OurAirports: {e}")

        return None

    async def _download_and_search_ourairports_by_code(self, code: str, code_type: str) -> Optional[Dict[str, Any]]:
        """Поиск в OurAirports по коду"""
        try:
            url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
            async with self.session.get(url) as response:
                if response.status == 200:
                    csv_data = await response.text()

                    for line in csv_data.split('\n')[1:]:
                        if not line:
                            continue

                        parts = line.split(',')
                        if len(parts) >= 3:
                            if code_type == 'iata':
                                field_index = 1
                            else:  # icao
                                field_index = 2

                            field_value = parts[field_index].strip('"')
                            if field_value == code:
                                iata = parts[1].strip('"') if parts[1].strip('"') != '""' else None
                                icao = parts[2].strip('"') if parts[2].strip('"') != '""' else None

                                return {
                                    'name': parts[3].strip('"'),
                                    'city': parts[10].strip('"') if len(parts) > 10 else '',
                                    'country': parts[8].strip('"') if len(parts) > 8 else '',
                                    'iata': iata,
                                    'icao': icao,
                                    'latitude': parts[4].strip('"') if len(parts) > 4 else '',
                                    'longitude': parts[5].strip('"') if len(parts) > 5 else ''
                                }
        except Exception as e:
            print(f"Ошибка поиска кода в OurAirports: {e}")

        return None

    def _parse_aviationapi(self, data: Any, query: str) -> Optional[Dict[str, Any]]:
        """Парсинг ответа AviationAPI"""
        try:
            if isinstance(data, dict):
                for airport in data.values():
                    if isinstance(airport, list) and len(airport) > 0:
                        apt = airport[0]
                        if 'icao' in apt and 'iata' in apt:
                            return {
                                'name': apt.get('facility_name', ''),
                                'city': apt.get('city', ''),
                                'country': apt.get('state', ''),
                                'iata': apt.get('iata'),
                                'icao': apt.get('icao'),
                                'latitude': apt.get('latitude', ''),
                                'longitude': apt.get('longitude', '')
                            }
        except Exception as e:
            print(f"Ошибка парсинга AviationAPI: {e}")

        return None

    def _parse_opensky(self, data: Any, query: str) -> Optional[Dict[str, Any]]:
        """Парсинг ответа OpenSky"""
        try:
            if isinstance(data, list):
                for airport in data:
                    if query.lower() in airport.get('name', '').lower():
                        return {
                            'name': airport.get('name', ''),
                            'city': airport.get('city', ''),
                            'country': airport.get('country', ''),
                            'iata': airport.get('iata'),
                            'icao': airport.get('icao'),
                            'latitude': airport.get('latitude', ''),
                            'longitude': airport.get('longitude', '')
                        }
        except Exception as e:
            print(f"Ошибка парсинга OpenSky: {e}")

        return None

    def _parse_ourairports(self, data: Any, query: str) -> Optional[Dict[str, Any]]:
        """Парсинг OurAirports (уже обработан ранее)"""
        return None

    async def _extract_from_text(self, text: str) -> Optional[Dict[str, Any]]:
        """Извлечение кодов из текста (резервный метод)"""
        # Ищем IATA код (3 заглавные буквы)
        iata_matches = self.iata_pattern.findall(text.upper())
        if iata_matches:
            iata_code = iata_matches[0]
            # Попробуем найти информацию по этому коду
            return await self.search_airport_by_code(iata_code)

        # Ищем ICAO код (4 заглавные буквы)
        icao_matches = self.icao_pattern.findall(text.upper())
        if icao_matches:
            icao_code = icao_matches[0]
            return await self.search_airport_by_code(icao_code)

        return None

    def generate_flight_number(self, airline_iata: str, route_number: str) -> str:
        """Генерация номера рейса в формате IATA123"""
        # Убираем пробелы и приводим к верхнему регистру
        airline_iata = airline_iata.upper().strip()
        route_number = str(route_number).strip()

        # Если номер уже содержит IATA код, возвращаем как есть
        if route_number.startswith(airline_iata):
            return route_number.upper()

        # Иначе генерируем новый номер
        return f"{airline_iata}{route_number}"

    async def get_airport_suggestions(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Получение подсказок для автодополнения"""
        suggestions = []

        # Для простоты, можно использовать известные аэропорты
        known_airports = [
            {"name": "Шереметьево", "city": "Москва", "iata": "SVO", "icao": "UUEE"},
            {"name": "Домодедово", "city": "Москва", "iata": "DME", "icao": "UUDD"},
            {"name": "Внуково", "city": "Москва", "iata": "VKO", "icao": "UUWW"},
            {"name": "Пулково", "city": "Санкт-Петербург", "iata": "LED", "icao": "ULLI"},
            {"name": "Толмачёво", "city": "Новосибирск", "iata": "OVB", "icao": "UNNT"},
            {"name": "Кольцово", "city": "Екатеринбург", "iata": "SVX", "icao": "USSS"},
            {"name": "Казань", "city": "Казань", "iata": "KZN", "icao": "UWKD"},
            {"name": "Сочи", "city": "Сочи", "iata": "AER", "icao": "URSS"},
            {"name": "Минеральные Воды", "city": "Минеральные Воды", "iata": "MRV", "icao": "URMM"},
            {"name": "Храброво", "city": "Калининград", "iata": "KGD", "icao": "UMKK"},
        ]

        query_lower = query.lower()
        for airport in known_airports:
            if (query_lower in airport['name'].lower() or 
                query_lower in airport['city'].lower() or
                query_lower in airport['iata'].lower()):
                suggestions.append(airport)

            if len(suggestions) >= limit:
                break

        return suggestions