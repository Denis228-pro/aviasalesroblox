import firebase_admin
from firebase_admin import firestore
from datetime import datetime
from typing import Dict, List, Optional, Any

class DatabaseHandler:
    def __init__(self, db):
        self.db = db
        self._airline_cache = {}
        self._partners_cache = None
        self._cache_time = {}

    def _is_cache_valid(self, key, ttl=300):
        if key not in self._cache_time:
            return False
        return (datetime.now() - self._cache_time[key]).total_seconds() < ttl

    # Авиакомпании
    async def get_airline_by_owner(self, owner_id: str) -> Optional[Dict]:
        """Получить авиакомпанию по ID владельца"""
        cache_key = f"owner_{owner_id}"
        if self._is_cache_valid(cache_key):
            return self._airline_cache.get(cache_key)

        airlines_ref = self.db.collection('airlines')
        query = airlines_ref.where('owner_id', '==', str(owner_id)).limit(1)
        results = query.get()

        if len(results) > 0:
            data = results[0].to_dict()
            data['id'] = results[0].id
            self._airline_cache[cache_key] = data
            self._cache_time[cache_key] = datetime.now()
            return data
        return None

    async def get_airline_by_id(self, airline_id: str) -> Optional[Dict]:
        """Получить авиакомпанию по ID"""
        cache_key = f"id_{airline_id}"
        if self._is_cache_valid(cache_key):
            return self._airline_cache.get(cache_key)

        airline_ref = self.db.collection('airlines').document(airline_id)
        airline = airline_ref.get()

        if airline.exists:
            data = airline.to_dict()
            data['id'] = airline.id
            self._airline_cache[cache_key] = data
            self._cache_time[cache_key] = datetime.now()
            return data
        return None

    async def update_airline_stats(self, airline_id: str, stats_update: Dict):
        """Обновить статистику авиакомпании"""
        airline_ref = self.db.collection('airlines').document(airline_id)

        # Инвалидируем кэш
        self._airline_cache.pop(f"id_{airline_id}", None)
        # Нам сложно найти ключ по owner_id без запроса, поэтому просто очистим или подождем TTL

        # Получаем текущие статистики
        airline = airline_ref.get()
        if airline.exists:
            current_stats = airline.to_dict().get('statistics', {})

            # Обновляем статистики
            for key, value in stats_update.items():
                if key in current_stats:
                    current_stats[key] += value
                else:
                    current_stats[key] = value

            # Сохраняем
            airline_ref.update({
                'statistics': current_stats,
                'updated_at': datetime.now().isoformat()
            })

    # Рейсы
    async def create_flight(self, flight_data: Dict) -> str:
        """Создать новый рейс"""
        flights_ref = self.db.collection('flights')
        flight_doc = flights_ref.add(flight_data)
        return flight_doc[1].id

    async def get_flights_by_airline(self, airline_id: str) -> List[Dict]:
        """Получить все рейсы авиакомпании"""
        flights_ref = self.db.collection('flights')
        query = flights_ref.where('airline_id', '==', airline_id)
        results = query.get()

        return [doc.to_dict() for doc in results]

    async def update_flight_status(self, flight_id: str, status: str):
        """Обновить статус рейса"""
        try:
            flight_ref = self.db.collection('flights').document(flight_id)
            flight_ref.update({
                'status': status,
                'updated_at': datetime.now().isoformat()
            })
        except Exception as e:
            print(f"Ошибка обновления статуса рейса {flight_id}: {e}")

    # Подписки
    async def add_subscription(self, user_id: str, flight_id: str):
        """Добавить подписку на уведомления о рейсе"""
        subs_ref = self.db.collection('subscriptions')

        # Проверяем, есть ли уже подписка
        query = subs_ref.where('user_id', '==', user_id).where('flight_id', '==', flight_id).limit(1)
        existing = query.get()

        if len(existing) == 0:
            subscription_data = {
                'user_id': user_id,
                'flight_id': flight_id,
                'created_at': datetime.now().isoformat(),
                'notifications_sent': []
            }
            subs_ref.add(subscription_data)
            return True
        return False

    # Партнеры
    async def get_all_partners(self) -> List[Dict]:
        """Получить всех активных партнеров"""
        if self._is_cache_valid('partners'):
            return self._partners_cache

        partners_ref = self.db.collection('partners')
        query = partners_ref.where('status', '==', 'active')
        results = query.get()

        data = [doc.to_dict() for doc in results]
        self._partners_cache = data
        self._cache_time['partners'] = datetime.now()
        return data

    # Модерация
    async def get_pending_applications(self) -> List[Any]:
        """Получить все ожидающие заявки"""
        apps_ref = self.db.collection('airline_applications')
        query = apps_ref.where('status', '==', 'pending')
        results = query.get()

        return [(doc.id, doc.to_dict()) for doc in results]