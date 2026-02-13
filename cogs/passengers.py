import firebase_admin
from firebase_admin import firestore
import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import Button, View, Modal, TextInput, Select
from datetime import datetime, timedelta
from typing import Optional
import asyncio

class Passengers(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="поиск", description="Поиск рейсов")
    @app_commands.describe(
        date="Дата вылета (ДД.ММ.ГГГГ)",
        departure="Код аэропорта вылета (например: SVO)",
        arrival="Код аэропорта прилета (например: DME)"
    )
    async def search_flights(
        self,
        interaction: discord.Interaction,
        date: Optional[str] = None,
        departure: Optional[str] = None,
        arrival: Optional[str] = None
    ):
        """Поиск рейсов по параметрам"""
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        
        db_handler = self.bot.data
        db = db_handler.db
        flights_ref = db.collection('flights')

        # Базовый запрос - только активные рейсы
        query = flights_ref.where('status', 'in', ['scheduled', 'boarding', 'delayed'])

        # Конвертируем дату если указана
        departure_date = None
        if date:
            try:
                departure_date = datetime.strptime(date, "%d.%m.%Y")
            except ValueError:
                await interaction.response.send_message(
                    "❌ Неверный формат даты! Используйте ДД.ММ.ГГГГ",
                    ephemeral=True
                )
                return

        # Получаем рейсы
        flights = query.get()

        # Фильтруем результаты
        filtered_flights = []

        for flight in flights:
            flight_data = flight.to_dict()
            flight_id = flight.id

            # Фильтр по дате
            if date:
                flight_date_str = flight_data.get('departure_date')
                if not flight_date_str or flight_date_str != date:
                    continue

            # Фильтр по аэропорту вылета
            if departure:
                flight_departure = flight_data.get('departure_code', '').upper()
                if flight_departure != departure.upper():
                    continue

            # Фильтр по аэропорту прилета
            if arrival:
                flight_arrival = flight_data.get('arrival_code', '').upper()
                if flight_arrival != arrival.upper():
                    continue

            filtered_flights.append((flight_id, flight_data))

        # Сортируем по дате и времени
        filtered_flights.sort(key=lambda x: x[1].get('departure_datetime', ''))

        if len(filtered_flights) == 0:
            await interaction.response.send_message(
                "❌ Рейсы по вашему запросу не найдены!",
                ephemeral=True
            )
            return

        # Создаем Embed с результатами
        embed = discord.Embed(
            title="🔍 Результаты поиска рейсов",
            description=f"Найдено рейсов: **{len(filtered_flights)}**",
            color=discord.Color.blue()
        )

        # Добавляем информацию о фильтрах
        filters_text = ""
        if date:
            filters_text += f"📅 Дата: **{date}**\n"
        if departure:
            filters_text += f"🛫 Вылет из: **{departure.upper()}**\n"
        if arrival:
            filters_text += f"🛬 Прилет в: **{arrival.upper()}**\n"

        if filters_text:
            embed.add_field(name="🎯 Примененные фильтры", value=filters_text, inline=False)

        # Создаем View с селектором для выбора рейса
        class FlightSelectView(View):
            def __init__(self, flights: list):
                super().__init__(timeout=180)
                self.flights = flights

                # Создаем опции для селектора
                options = []
                for i, (flight_id, flight_data) in enumerate(flights[:25], 1):
                    dep_code = flight_data.get('departure_code', 'N/A')
                    arr_code = flight_data.get('arrival_code', 'N/A')
                    flight_num = flight_data.get('flight_number', 'N/A')
                    airline = flight_data.get('airline_name', 'Неизвестно')

                    option = discord.SelectOption(
                        label=f"{flight_num} ({dep_code} → {arr_code})",
                        description=f"{airline} - {flight_data.get('departure_date', '')} {flight_data.get('departure_time', '')}",
                        value=flight_id,
                        emoji="✈️"
                    )
                    options.append(option)

                self.select = Select(
                    placeholder="Выберите рейс для подробностей...",
                    options=options
                )
                self.select.callback = self.flight_selected
                self.add_item(self.select)

            async def flight_selected(self, interaction: discord.Interaction):
                selected_id = self.select.values[0]

                # Находим выбранный рейс
                selected_flight = None
                selected_data = None

                for flight_id, flight_data in self.flights:
                    if flight_id == selected_id:
                        selected_flight = flight_id
                        selected_data = flight_data
                        break

                if not selected_flight:
                    await interaction.response.send_message(
                        "❌ Рейс не найден!",
                        ephemeral=True
                    )
                    return

                # Создаем Embed с деталями рейса
                if not selected_data:
                    return await interaction.response.send_message("❌ Ошибка данных рейса", ephemeral=True)
                
                details_embed = discord.Embed(
                    title=f"✈️ Детали рейса {selected_data.get('flight_number', '')}",
                    color=discord.Color.blue()
                )

                # Добавляем поля с информацией
                details_embed.add_field(name="🏢 Авиакомпания", value=f"{selected_data.get('airline_name', 'Неизвестно')} ({selected_data.get('airline_iata', 'N/A')})", inline=True)
                details_embed.add_field(name="🛫 Вылет", value=f"{selected_data.get('departure_airport', 'Неизвестно')} ({selected_data.get('departure_code', 'N/A')})", inline=True)
                details_embed.add_field(name="🛬 Прилет", value=f"{selected_data.get('arrival_airport', 'Неизвестно')} ({selected_data.get('arrival_code', 'N/A')})", inline=True)
                details_embed.add_field(name="📅 Дата", value=selected_data.get('departure_date', 'Неизвестно'), inline=True)
                details_embed.add_field(name="⏰ Время вылета", value=selected_data.get('departure_time', 'Неизвестно'), inline=True)
                details_embed.add_field(name="✈️ Воздушное судно", value=selected_data.get('aircraft', 'Неизвестно'), inline=True)

                # Статус рейса
                status = selected_data.get('status', 'scheduled')
                status_emoji = {
                    'scheduled': '🟢',
                    'boarding': '🟡',
                    'departed': '✈️',
                    'delayed': '🟠',
                    'cancelled': '🔴',
                    'completed': '✅'
                }.get(status, '❓')

                status_text = {
                    'scheduled': 'По расписанию',
                    'boarding': 'Идет регистрация',
                    'departed': 'Вылетел',
                    'delayed': 'Задержан',
                    'cancelled': 'Отменен',
                    'completed': 'Завершен'
                }.get(status, 'Неизвестно')

                details_embed.add_field(name="📊 Статус", value=f"{status_emoji} {status_text}", inline=True)

                # Информация о регистрации
                details_embed.add_field(name="🎮 Открытие сервера", value=selected_data.get('server_open_time', 'Неизвестно'), inline=True)
                details_embed.add_field(name="📋 Начало регистрации", value=selected_data.get('registration_start', 'Неизвестно'), inline=True)
                details_embed.add_field(name="🌐 Часовой пояс", value=selected_data.get('timezone', 'Неизвестно'), inline=True)

                # Ссылки на игры
                departure_link = selected_data.get('departure_game_link', '')
                arrival_link = selected_data.get('arrival_game_link', '')

                if departure_link:
                    details_embed.add_field(name="🎮 Ссылка на игру (вылет)", value=departure_link, inline=False)
                if arrival_link:
                    details_embed.add_field(name="🎮 Ссылка на игру (прилет)", value=arrival_link, inline=False)

                # Классы обслуживания
                service_classes = selected_data.get('service_classes', ['Эконом', 'Бизнес', 'Первый'])
                details_embed.add_field(name="💺 Классы обслуживания", value=", ".join(service_classes), inline=False)

                # Кнопки для взаимодействия
                class FlightDetailsView(View):
                    def __init__(self, flight_id: str, flight_data: dict):
                        super().__init__(timeout=180)
                        self.flight_id = flight_id
                        self.flight_data = flight_data

                    @discord.ui.button(label="🔔 Напомнить", style=discord.ButtonStyle.primary, emoji="🔔")
                    async def remind_button(self, interaction: discord.Interaction, button: Button):
                        db = interaction.client.data.db

                        # Сохраняем подписку
                        subscriptions_ref = db.collection('subscriptions')

                        # Проверяем, есть ли уже подписка
                        query = subscriptions_ref.where('user_id', '==', str(interaction.user.id)).where('flight_id', '==', self.flight_id).limit(1)
                        existing = query.get()

                        if len(existing) > 0:
                            await interaction.response.send_message(
                                "❌ Вы уже подписаны на уведомления об этом рейсе!",
                                ephemeral=True
                            )
                            return

                        subscription_data = {
                            'user_id': str(interaction.user.id),
                            'username': str(interaction.user),
                            'flight_id': self.flight_id,
                            'created_at': datetime.now().isoformat(),
                            'notifications': ['24h', '6h', '1h', '30min', 'server_open'],
                            'notifications_sent': []
                        }

                        subscriptions_ref.add(subscription_data)

                        # Увеличиваем счетчик подписок
                        flights_ref = db.collection('flights')
                        flights_ref.document(self.flight_id).update({
                            'subscriptions': firestore.Increment(1)
                        })

                        await interaction.response.send_message(
                            "✅ Вы подписались на уведомления о рейсе! Вы получите напоминания:\n"
                            "• За 24 часа до вылета\n"
                            "• За 6 часов до вылета\n"
                            "• За 1 час до вылета\n"
                            "• За 30 минут до вылета\n"
                            "• При открытии сервера",
                            ephemeral=True
                        )

                    @discord.ui.button(label="📊 Статистика рейса", style=discord.ButtonStyle.secondary, emoji="📊")
                    async def stats_button(self, interaction: discord.Interaction, button: Button):
                        db = interaction.client.data.db

                        # Получаем количество подписок
                        subscriptions_ref = db.collection('subscriptions')
                        query = subscriptions_ref.where('flight_id', '==', self.flight_id)
                        subscriptions = query.get()

                        stats_embed = discord.Embed(
                            title=f"📊 Статистика рейса {self.flight_data.get('flight_number', '')}",
                            color=discord.Color.blue()
                        )

                        stats_embed.add_field(name="🔔 Подписок на уведомления", value=f"**{len(subscriptions)}**", inline=True)

                        # Статус рейса
                        status = self.flight_data.get('status', 'scheduled')
                        status_emoji = {
                            'scheduled': '🟢',
                            'boarding': '🟡',
                            'departed': '✈️',
                            'delayed': '🟠',
                            'cancelled': '🔴',
                            'completed': '✅'
                        }.get(status, '❓')

                        stats_embed.add_field(name="📊 Статус", value=f"{status_emoji} {status}", inline=True)

                        # Время до вылета
                        departure_str = self.flight_data.get('departure_datetime')
                        if departure_str:
                            try:
                                departure_time = datetime.fromisoformat(departure_str.replace('Z', '+00:00'))
                                now = datetime.now()

                                if departure_time > now:
                                    time_until = departure_time - now
                                    hours = int(time_until.total_seconds() // 3600)
                                    minutes = int((time_until.total_seconds() % 3600) // 60)

                                    stats_embed.add_field(name="⏰ До вылета", value=f"**{hours}ч {minutes}м**", inline=True)
                            except:
                                pass

                        await interaction.response.send_message(embed=stats_embed, ephemeral=True)

                details_view = FlightDetailsView(selected_flight, selected_data)
                await interaction.response.send_message(embed=details_embed, view=details_view, ephemeral=True)

        # Показываем первые 5 рейсов в общем Embed
        for i, (flight_id, flight_data) in enumerate(filtered_flights[:5], 1):
            flight_info = f"""
            ✈️ **{flight_data.get('flight_number', 'Без номера')}**
            🏢 {flight_data.get('airline_name', 'Не указано')} ({flight_data.get('airline_iata', 'N/A')})
            🛫 {flight_data.get('departure_airport', 'Не указан')} → {flight_data.get('arrival_airport', 'Не указан')}
            ⏰ {flight_data.get('departure_time', 'Не указано')}
            📊 Статус: {self._get_status_emoji(flight_data.get('status', ''))} {self._get_status_text(flight_data.get('status', ''))}
            """

            embed.add_field(
                name=f"Рейс #{i}",
                value=flight_info,
                inline=False
            )

        # Если рейсов больше 5, добавляем селектор
        if len(filtered_flights) > 5:
            embed.set_footer(text=f"Показано 5 из {len(filtered_flights)} рейсов. Используйте меню ниже для просмотра всех.")
            view = FlightSelectView(filtered_flights)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            view = FlightSelectView(filtered_flights)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="расписание_рейсов", description="Показать расписание рейсов")
    async def show_schedule(self, interaction: discord.Interaction):
        """Показать расписание всех активных рейсов"""
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        db = self.bot.data.db
        flights_ref = db.collection('flights')

        # Получаем активные рейсы (по расписанию, идет регистрация и задержанные)
        query = flights_ref.where('status', 'in', ['scheduled', 'boarding', 'delayed'])
        active_flights = query.get()

        # Преобразуем в список и сортируем по дате вылета
        flights_list = []
        for flight in active_flights:
            flight_data = flight.to_dict()
            flights_list.append((flight.id, flight_data))

        # Сортируем по дате и времени вылета
        flights_list.sort(key=lambda x: x[1].get('departure_datetime', ''))

        if not flights_list:
            await interaction.response.send_message(
                "❌ Активных рейсов не найдено!",
                ephemeral=True
            )
            return

        # Создаем Embed
        embed = discord.Embed(
            title="📅 Расписание рейсов",
            description=f"Найдено активных рейсов: **{len(flights_list)}**",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )

        # Добавляем информацию о статусах
        status_counts = {
            'scheduled': 0,
            'boarding': 0,
            'delayed': 0
        }

        for _, flight_data in flights_list:
            status = flight_data.get('status', 'scheduled')
            if status in status_counts:
                status_counts[status] += 1

        embed.add_field(
            name="📊 Статистика статусов",
            value=f"""
            🟢 По расписанию: **{status_counts['scheduled']}**
            🟡 Идет регистрация: **{status_counts['boarding']}**
            🟠 Задержано: **{status_counts['delayed']}**
            """,
            inline=False
        )

        # Показываем ближайшие рейсы
        today = datetime.now().date()
        today_flights = []
        tomorrow_flights = []
        future_flights = []

        for flight_id, flight_data in flights_list:
            departure_str = flight_data.get('departure_datetime')
            if departure_str:
                try:
                    departure_time = datetime.fromisoformat(departure_str.replace('Z', '+00:00'))
                    flight_date = departure_time.date()

                    if flight_date == today:
                        today_flights.append((flight_id, flight_data))
                    elif flight_date == today + timedelta(days=1):
                        tomorrow_flights.append((flight_id, flight_data))
                    else:
                        future_flights.append((flight_id, flight_data))
                except:
                    future_flights.append((flight_id, flight_data))

        # Сегодняшние рейсы
        if today_flights:
            today_text = ""
            for flight_id, flight_data in today_flights[:3]:
                today_text += f"• **{flight_data.get('flight_number', 'N/A')}** - {flight_data.get('departure_airport', 'N/A')} → {flight_data.get('arrival_airport', 'N/A')} - {flight_data.get('departure_time', 'N/A')}\n"

            if len(today_flights) > 3:
                today_text += f"*...и еще {len(today_flights) - 3} рейсов*"

            embed.add_field(name="📅 Сегодня", value=today_text or "Нет рейсов", inline=False)

        # Завтрашние рейсы
        if tomorrow_flights:
            tomorrow_text = ""
            for flight_id, flight_data in tomorrow_flights[:3]:
                tomorrow_text += f"• **{flight_data.get('flight_number', 'N/A')}** - {flight_data.get('departure_airport', 'N/A')} → {flight_data.get('arrival_airport', 'N/A')} - {flight_data.get('departure_time', 'N/A')}\n"

            if len(tomorrow_flights) > 3:
                tomorrow_text += f"*...и еще {len(tomorrow_flights) - 3} рейсов*"

            embed.add_field(name="📅 Завтра", value=tomorrow_text or "Нет рейсов", inline=False)

        # Создаем View с селектором для выбора рейса
        class ScheduleSelectView(View):
            def __init__(self, flights: list):
                super().__init__(timeout=180)
                self.flights = flights

                # Создаем опции для селектора
                options = []
                for i, (flight_id, flight_data) in enumerate(flights[:25], 1):
                    dep_code = flight_data.get('departure_code', 'N/A')
                    arr_code = flight_data.get('arrival_code', 'N/A')
                    flight_num = flight_data.get('flight_number', 'N/A')
                    airline = flight_data.get('airline_name', 'Неизвестно')

                    option = discord.SelectOption(
                        label=f"{flight_num} ({dep_code} → {arr_code})",
                        description=f"{airline} - {flight_data.get('departure_date', '')} {flight_data.get('departure_time', '')}",
                        value=flight_id,
                        emoji="✈️"
                    )
                    options.append(option)

                self.select = Select(
                    placeholder="Выберите рейс для подробностей...",
                    options=options
                )
                self.select.callback = self.flight_selected
                self.add_item(self.select)

            async def flight_selected(self, interaction: discord.Interaction):
                selected_id = self.select.values[0]

                # Находим выбранный рейс
                selected_flight = None
                selected_data = None

                for flight_id, flight_data in self.flights:
                    if flight_id == selected_id:
                        selected_flight = flight_id
                        selected_data = flight_data
                        break

                if not selected_flight:
                    await interaction.response.send_message(
                        "❌ Рейс не найден!",
                        ephemeral=True
                    )
                    return

                # Создаем Embed с деталями рейса
                if not selected_data:
                    return await interaction.response.send_message("❌ Ошибка данных рейса", ephemeral=True)
                
                details_embed = discord.Embed(
                    title=f"✈️ Детали рейса {selected_data.get('flight_number', '')}",
                    color=discord.Color.blue()
                )

                # Добавляем поля с информацией
                details_embed.add_field(name="🏢 Авиакомпания", value=f"{selected_data.get('airline_name', 'Неизвестно')} ({selected_data.get('airline_iata', 'N/A')})", inline=True)
                details_embed.add_field(name="🛫 Вылет", value=f"{selected_data.get('departure_airport', 'Неизвестно')} ({selected_data.get('departure_code', 'N/A')})", inline=True)
                details_embed.add_field(name="🛬 Прилет", value=f"{selected_data.get('arrival_airport', 'Неизвестно')} ({selected_data.get('arrival_code', 'N/A')})", inline=True)
                details_embed.add_field(name="📅 Дата", value=selected_data.get('departure_date', 'Неизвестно'), inline=True)
                details_embed.add_field(name="⏰ Время вылета", value=selected_data.get('departure_time', 'Неизвестно'), inline=True)
                details_embed.add_field(name="✈️ Воздушное судно", value=selected_data.get('aircraft', 'Неизвестно'), inline=True)

                # Статус рейса
                status = selected_data.get('status', 'scheduled')
                status_emoji = {
                    'scheduled': '🟢',
                    'boarding': '🟡',
                    'departed': '✈️',
                    'delayed': '🟠',
                    'cancelled': '🔴',
                    'completed': '✅'
                }.get(status, '❓')

                status_text = {
                    'scheduled': 'По расписанию',
                    'boarding': 'Идет регистрация',
                    'departed': 'Вылетел',
                    'delayed': 'Задержан',
                    'cancelled': 'Отменен',
                    'completed': 'Завершен'
                }.get(status, 'Неизвестно')

                details_embed.add_field(name="📊 Статус", value=f"{status_emoji} {status_text}", inline=True)

                # Кнопка для напоминания
                class RemindButton(Button):
                    def __init__(self, flight_id: str):
                        super().__init__(label="🔔 Напомнить", style=discord.ButtonStyle.primary, emoji="🔔")
                        self.flight_id = flight_id

                    async def callback(self, interaction: discord.Interaction):
                        db = interaction.client.data.db

                        # Сохраняем подписку
                        subscriptions_ref = db.collection('subscriptions')

                        # Проверяем, есть ли уже подписка
                        query = subscriptions_ref.where('user_id', '==', str(interaction.user.id)).where('flight_id', '==', self.flight_id).limit(1)
                        existing = query.get()

                        if len(existing) > 0:
                            await interaction.response.send_message(
                                "❌ Вы уже подписаны на уведомления об этом рейсе!",
                                ephemeral=True
                            )
                            return

                        subscription_data = {
                            'user_id': str(interaction.user.id),
                            'username': str(interaction.user),
                            'flight_id': self.flight_id,
                            'created_at': datetime.now().isoformat(),
                            'notifications': ['24h', '6h', '1h', '30min', 'server_open'],
                            'notifications_sent': []
                        }

                        subscriptions_ref.add(subscription_data)

                        # Увеличиваем счетчик подписок
                        flights_ref = db.collection('flights')
                        flights_ref.document(self.flight_id).update({
                            'subscriptions': firestore.Increment(1)
                        })

                        await interaction.response.send_message(
                            "✅ Вы подписались на уведомления о рейсе!",
                            ephemeral=True
                        )

                details_view = View(timeout=180)
                details_view.add_item(RemindButton(selected_flight))

                await interaction.response.send_message(embed=details_embed, view=details_view, ephemeral=True)

        view = ScheduleSelectView(flights_list)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    def _get_status_emoji(self, status: str) -> str:
        """Возвращает эмодзи для статуса"""
        emoji_map = {
            'scheduled': '🟢',
            'boarding': '🟡',
            'departed': '✈️',
            'delayed': '🟠',
            'cancelled': '🔴',
            'completed': '✅'
        }
        return emoji_map.get(status, '❓')

    def _get_status_text(self, status: str) -> str:
        """Возвращает текстовое описание статуса"""
        text_map = {
            'scheduled': 'По расписанию',
            'boarding': 'Идет регистрация',
            'departed': 'Вылетел',
            'delayed': 'Задержан',
            'cancelled': 'Отменен',
            'completed': 'Завершен'
        }
        return text_map.get(status, 'Неизвестно')

async def setup(bot):
    await bot.add_cog(Passengers(bot))