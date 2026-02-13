# [file name]: flights.py
import firebase_admin
from firebase_admin import firestore
import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import Button, View, Modal, TextInput, Select
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import asyncio
import pytz
import re

class FlightStyles:
    """Стили для оформления рейсов"""
    COLORS = {
        'success': 0x2ecc71,
        'error': 0xe74c3c,
        'warning': 0xf1c40f,
        'info': 0x3498db,
        'primary': 0x5865f2,
        'purple': 0x9b59b6,
        'dark': 0x2b2d31,
    }

class FlightCard:
    """Карточка для отображения информации о рейсе"""
    @staticmethod
    def create_embed(title: str, description: str = "", color: int = FlightStyles.COLORS['info']):
        embed = discord.Embed(
            title=f"✈️ {title}",
            description=description,
            color=color,
            timestamp=datetime.now()
        )
        embed.set_footer(text="Aviasales Roblox • Система управления", icon_url="https://i.imgur.com/8fX8YfX.png")
        return embed

    @staticmethod
    def create_status_badge(status: str):
        status_emojis = {
            'scheduled': '📅 Запланирован',
            'boarding': '🎫 Посадка',
            'departed': '🛫 Взлетел',
            'delayed': '🕒 Задержан',
            'cancelled': '❌ Отменен',
            'completed': '🛬 Приземлился'
        }
        return status_emojis.get(status, '❓ Неизвестно')

class EnhancedFlightCreationView(View):
    """Создание рейса с автоматическим определением кодов и генерацией номера рейса"""

    def __init__(self, airline_id: str, airline_data: dict, bot):
        super().__init__(timeout=300)
        self.airline_id = airline_id
        self.airline_data = airline_data
        self.bot = bot
        self.db = bot.data.db
        self.db_handler = bot.data # Предполагаем, что bot.data это DatabaseHandler

        # Получаем сервис аэропортов из кога Airlines
        self.airport_service = None
        airlines_cog = self.bot.get_cog('Airlines')
        if airlines_cog:
            self.airport_service = airlines_cog.airport_service

        self.routes = airline_data.get('routes', [])
        self.airports = airline_data.get('airports', [])

        self.timing_profiles = airline_data.get('timing_profiles', [
            {
                'name': 'Стандартный',
                'checkin_open': 55,
                'checkin_close': 15,
                'server_open': 50,
                'server_close': 10,
            },
            {
                'name': 'Экспресс',
                'checkin_open': 40,
                'checkin_close': 10,
                'server_open': 35,
                'server_close': 5,
            }
        ])

        self.selected_route = None
        self.selected_date = None
        self.selected_time = None
        self.selected_profile = self.timing_profiles[0] if self.timing_profiles else None
        self.custom_flight_number = None

        self.create_ui()

    def create_ui(self):
        """Создание интерфейса с двумя режимами: выбор маршрута или создание с нуля"""

        # Селектор режима
        mode_select = Select(
            placeholder="Выберите режим создания",
            options=[
                discord.SelectOption(label="🚀 Быстрый (из маршрутов)", description="Создать из предустановленных маршрутов", value="quick"),
                discord.SelectOption(label="✨ Авто (определение кодов)", description="Автоматическое определение кодов аэропортов", value="auto"),
                discord.SelectOption(label="🎫 Ручной ввод", description="Полностью ручное создание", value="manual")
            ],
            min_values=1,
            max_values=1,
            row=0
        )
        mode_select.callback = self.mode_selected
        self.add_item(mode_select)

        # Контейнер для динамических элементов
        self.dynamic_row = 1

    async def mode_selected(self, interaction: discord.Interaction):
        """Обработка выбора режима"""
        if not interaction.data or 'values' not in interaction.data:
            mode = 'quick'
        else:
            mode = interaction.data['values'][0]

        # Удаляем старые динамические элементы
        for item in self.children[:]:
            if hasattr(item, 'row') and item.row is not None and item.row >= 1:
                self.remove_item(item)

        if mode == 'quick':
            await self.create_quick_mode_ui()
        elif mode == 'auto':
            await self.create_auto_mode_ui()
        elif mode == 'manual':
            await self.create_manual_mode_ui()

        await interaction.response.edit_message(view=self)

    async def create_quick_mode_ui(self):
        """Создание UI для быстрого режима (из маршрутов)"""

        # Селектор маршрута
        if self.routes:
            route_options = []
            for route in self.routes[:25]:
                route_name = route.get('name', 'Без названия')
                flight_number = route.get('flight_number', 'N/A')
                departure_code = route.get('departure_code', '???')
                arrival_code = route.get('arrival_code', '???')

                route_options.append(discord.SelectOption(
                    label=f"{flight_number} - {route_name[:30]}",
                    description=f"{departure_code} → {arrival_code}",
                    value=route.get('code', '')
                ))

            route_select = Select(
                placeholder=f"Выберите маршрут ({len(self.routes)} доступно)",
                options=route_options,
                min_values=1,
                max_values=1,
                row=1
            )
            route_select.callback = self.route_selected_quick
            self.add_item(route_select)
        else:
            self.add_item(Button(
                label="❌ Нет маршрутов",
                style=discord.ButtonStyle.secondary,
                disabled=True,
                row=1
            ))

        # Добавляем общие элементы
        await self.add_common_elements(2)

    async def create_auto_mode_ui(self):
        """Создание UI для автоматического режима"""

        # Поле для номера рейса
        flight_number_input = TextInput(
            label="Номер рейса (только цифры)",
            placeholder="Например: 123",
            required=True,
            max_length=4,
            row=1
        )

        # Поля для аэропортов
        departure_input = TextInput(
            label="Аэропорт вылета",
            placeholder="Шереметьево или SVO",
            required=True,
            row=2
        )

        arrival_input = TextInput(
            label="Аэропорт прилета",
            placeholder="Пулково или LED",
            required=True,
            row=3
        )

        # Кнопка для поиска кодов
        find_codes_button = Button(
            label="🔍 Найти коды аэропортов",
            style=discord.ButtonStyle.primary,
            row=4
        )
        async def find_codes_callback(interaction: discord.Interaction):
            await self.find_airport_codes(interaction, departure_input, arrival_input)
        find_codes_button.callback = find_codes_callback

        self.add_item(flight_number_input)
        self.add_item(departure_input)
        self.add_item(arrival_input)
        self.add_item(find_codes_button)

        # Добавляем общие элементы
        await self.add_common_elements(5)

    async def create_manual_mode_ui(self):
        """Создание UI для ручного режима"""

        # Поля для ручного ввода
        flight_number_input = TextInput(
            label="Полный номер рейса",
            placeholder="Например: SU123",
            required=True,
            max_length=10,
            row=1
        )

        departure_input = TextInput(
            label="Код аэропорта вылета (IATA)",
            placeholder="SVO",
            required=True,
            max_length=3,
            row=2
        )

        arrival_input = TextInput(
            label="Код аэропорта прилета (IATA)",
            placeholder="LED",
            required=True,
            max_length=3,
            row=3
        )

        departure_name_input = TextInput(
            label="Название аэропорта вылета",
            placeholder="Шереметьево",
            required=True,
            row=4
        )

        arrival_name_input = TextInput(
            label="Название аэропорта прилета",
            placeholder="Пулково",
            required=True,
            row=5
        )

        self.add_item(flight_number_input)
        self.add_item(departure_input)
        self.add_item(arrival_input)
        self.add_item(departure_name_input)
        self.add_item(arrival_name_input)

        # Добавляем общие элементы
        await self.add_common_elements(6)

    async def add_common_elements(self, start_row: int):
        """Добавление общих элементов (дата, время, профиль)"""

        # Селектор даты
        date_options = []
        today = datetime.now()

        for i in range(1, 25):
            date = today + timedelta(days=i)
            date_str = date.strftime("%d.%m.%Y")
            weekday = date.strftime("%A")

            date_options.append(discord.SelectOption(
                label=date_str,
                description=weekday,
                value=date_str
            ))

        date_select = Select(
            placeholder="Выберите дату вылета",
            options=date_options,
            min_values=1,
            max_values=1,
            row=start_row
        )
        date_select.callback = self.date_selected
        self.add_item(date_select)

        # Селектор времени
        time_options = []
        for hour in range(6, 24):
            for minute in [0, 30]:
                time_str = f"{hour:02d}:{minute:02d}"
                time_options.append(discord.SelectOption(
                    label=time_str,
                    value=time_str
                ))

        time_select = Select(
            placeholder="Выберите время вылета",
            options=time_options[:25],
            min_values=1,
            max_values=1,
            row=start_row + 1
        )
        time_select.callback = self.time_selected
        self.add_item(time_select)

        # Селектор профиля таймингов
        if self.timing_profiles:
            profile_options = []
            for profile in self.timing_profiles:
                profile_options.append(discord.SelectOption(
                    label=profile.get('name', 'Стандартный'),
                    description=f"Регистрация: {profile.get('checkin_open')} → {profile.get('checkin_close')} мин",
                    value=profile.get('name', 'Стандартный')
                ))

            profile_select = Select(
                placeholder="Выберите профиль таймингов",
                options=profile_options,
                min_values=1,
                max_values=1,
                row=start_row + 2
            )
            profile_select.callback = self.profile_selected
            self.add_item(profile_select)

        # Кнопки действий
        preview_button = Button(
            label="👁️ Предпросмотр",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            row=start_row + 3
        )
        preview_button.callback = self.preview_flight

        create_button = Button(
            label="✅ Создать рейс",
            style=discord.ButtonStyle.success,
            disabled=True,
            row=start_row + 3
        )
        create_button.callback = self.create_flight

        reset_button = Button(
            label="🔄 Сбросить",
            style=discord.ButtonStyle.secondary,
            row=start_row + 3
        )
        reset_button.callback = self.reset_selection

        self.add_item(preview_button)
        self.add_item(create_button)
        self.add_item(reset_button)

        # Сохраняем ссылки на кнопки
        self.preview_button = preview_button
        self.create_button = create_button

    async def route_selected_quick(self, interaction: discord.Interaction):
        """Обработка выбора маршрута в быстром режиме"""
        if not interaction.data or 'values' not in interaction.data:
            return await interaction.response.send_message("❌ Ошибка получения данных маршрута", ephemeral=True)
        
        route_code = interaction.data['values'][0]

        for route in self.routes:
            if route.get('code') == route_code:
                self.selected_route = route
                break

        # Номер рейса берется из маршрута
        self.custom_flight_number = self.selected_route.get('flight_number') if self.selected_route else None

        await self.update_ui_state(interaction)
        if not interaction.response.is_done():
            await interaction.response.defer()

    async def date_selected(self, interaction: discord.Interaction):
        """Обработка выбора даты"""
        if interaction.data and 'values' in interaction.data:
            self.selected_date = interaction.data['values'][0]
        
        await self.update_ui_state(interaction)
        if not interaction.response.is_done():
            await interaction.response.defer()

    async def time_selected(self, interaction: discord.Interaction):
        """Обработка выбора времени"""
        if interaction.data and 'values' in interaction.data:
            self.selected_time = interaction.data['values'][0]
        
        await self.update_ui_state(interaction)
        if not interaction.response.is_done():
            await interaction.response.defer()

    async def profile_selected(self, interaction: discord.Interaction):
        """Обработка выбора профиля таймингов"""
        if not interaction.data or 'values' not in interaction.data:
            if not interaction.response.is_done():
                await interaction.response.defer()
            return

        profile_name = interaction.data['values'][0]

        for profile in self.timing_profiles:
            if profile.get('name') == profile_name:
                self.selected_profile = profile
                break

        if not interaction.response.is_done():
            await interaction.response.defer()

    async def find_airport_codes(self, interaction: discord.Interaction, departure_input, arrival_input):
        """Поиск кодов аэропортов через сервис"""
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            if not self.airport_service:
                await interaction.followup.send(
                    "❌ Сервис определения аэропортов недоступен",
                    ephemeral=True
                )
                return

            # Получаем значения из полей
            departure_value = None
            arrival_value = None

            for child in self.children:
                if hasattr(child, 'label') and child.label == departure_input.label:
                    departure_value = child.value
                elif hasattr(child, 'label') and child.label == arrival_input.label:
                    arrival_value = child.value

            if not departure_value or not arrival_value:
                await interaction.followup.send(
                    "❌ Введите названия аэропортов",
                    ephemeral=True
                )
                return

            # Ищем коды
            departure_info = await self.airport_service.search_airport_by_name(departure_value)
            arrival_info = await self.airport_service.search_airport_by_name(arrival_value)

            if not departure_info or not arrival_info:
                await interaction.followup.send(
                    "❌ Не удалось определить коды аэропортов. Проверьте названия.",
                    ephemeral=True
                )
                return

            # Обновляем UI с найденными кодами
            embed = discord.Embed(
                title="✅ Коды аэропортов найдены",
                color=discord.Color.green()
            )

            embed.add_field(
                name=f"🛫 {departure_info.get('name', 'Неизвестно')}",
                value=f"**IATA:** `{departure_info['iata']}`\n**ICAO:** `{departure_info.get('icao', 'N/A')}`\n**Город:** {departure_info.get('city', 'Неизвестно')}",
                inline=True
            )

            embed.add_field(
                name=f"🛬 {arrival_info.get('name', 'Неизвестно')}",
                value=f"**IATA:** `{arrival_info['iata']}`\n**ICAO:** `{arrival_info.get('icao', 'N/A')}`\n**Город:** {arrival_info.get('city', 'Неизвестно')}",
                inline=True
            )

            # Генерируем номер рейса
            airline_iata = self.airline_data.get('iata', 'SU')

            # Ищем поле с номером рейса
            flight_number_input = None
            for child in self.children:
                if hasattr(child, 'label') and 'номер рейса' in child.label.lower():
                    if hasattr(child, 'value') and child.value:
                        flight_number_input = child.value
                        break

            if flight_number_input and flight_number_input.isdigit():
                flight_number = self.airport_service.generate_flight_number(airline_iata, flight_number_input)
                embed.add_field(
                    name="✈️ Номер рейса",
                    value=f"`{flight_number}`",
                    inline=False
                )
                self.custom_flight_number = flight_number

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(
                f"❌ Ошибка при поиске кодов: {str(e)}",
                ephemeral=True
            )

    async def update_ui_state(self, interaction: discord.Interaction):
        """Обновление состояния UI"""
        # Проверяем, все ли обязательные поля заполнены
        required_fields_filled = all([
            self.selected_date,
            self.selected_time,
            self.selected_profile
        ])

        # Дополнительные проверки в зависимости от режима
        if hasattr(self, 'selected_route') and self.selected_route:
            # Быстрый режим: нужен выбранный маршрут
            all_filled = required_fields_filled and self.selected_route
        else:
            # Авто/ручной режим: нужен номер рейса
            all_filled = required_fields_filled and self.custom_flight_number

        if self.preview_button:
            self.preview_button.disabled = not all_filled

        if self.create_button:
            self.create_button.disabled = not all_filled

        try:
            await interaction.response.edit_message(view=self)
        except:
            pass

    async def reset_selection(self, interaction: discord.Interaction):
        """Сброс выбора"""
        self.selected_route = None
        self.selected_date = None
        self.selected_time = None
        self.selected_profile = self.timing_profiles[0] if self.timing_profiles else None
        self.custom_flight_number = None

        # Сбрасываем значения в UI
        for item in self.children:
            if isinstance(item, Select):
                # We can't easily reset values of Select in discord.py UI from here,
                # so we just let the update_ui_state handle the disabled buttons.
                pass
            elif isinstance(item, TextInput):
                # Same for TextInput
                pass

        if self.preview_button:
            self.preview_button.disabled = True

        if self.create_button:
            self.create_button.disabled = True

        await interaction.response.edit_message(view=self)

        embed = FlightCard.create_embed(
            "Выбор сброшен",
            "Все выбранные параметры были сброшены.",
            FlightStyles.COLORS['info']
        )
        await interaction.followup.send(embed=success_embed if 'success_embed' in locals() else embed, ephemeral=True)

    async def preview_flight(self, interaction: discord.Interaction):
        """Предпросмотр рейса"""
        if not all([self.selected_date, self.selected_time, self.selected_profile]):
            await interaction.response.send_message(
                embed=FlightCard.create_embed(
                    "Не все поля заполнены",
                    "Пожалуйста, заполните все поля перед просмотром.",
                    FlightStyles.COLORS['error']
                ),
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            try:
                departure_datetime = datetime.strptime(f"{self.selected_date} {self.selected_time}", "%d.%m.%Y %H:%M")
            except (ValueError, TypeError):
                await interaction.followup.send("❌ Некорректная дата или время", ephemeral=True)
                return

            profile = self.selected_profile or {
                'checkin_open': 55, 'checkin_close': 15,
                'server_open': 50, 'server_close': 10
            }

            # Определяем информацию о маршруте
            if self.selected_route:
                # Быстрый режим: используем данные из маршрута
                route = self.selected_route
                flight_number = route.get('flight_number', 'N/A')
                departure_code = route.get('departure_code', '???')
                arrival_code = route.get('arrival_code', '???')
                departure_name = route.get('departure_airport', 'Неизвестно')
                arrival_name = route.get('arrival_airport', 'Неизвестно')
                flight_time = route.get('flight_time', 120)
                aircraft = route.get('aircraft', 'Неизвестно')
            else:
                # Авто/ручной режим
                flight_number = self.custom_flight_number or "N/A"
                departure_code = "???"
                arrival_code = "???"
                departure_name = "Неизвестно"
                arrival_name = "Неизвестно"
                flight_time = 120
                aircraft = "Неизвестно"

            # Рассчитываем времена
            checkin_open = departure_datetime - timedelta(minutes=profile.get('checkin_open', 55))
            checkin_close = departure_datetime - timedelta(minutes=profile.get('checkin_close', 15))
            server_open = departure_datetime - timedelta(minutes=profile.get('server_open', 50))
            server_close = departure_datetime - timedelta(minutes=profile.get('server_close', 10))
            arrival_time = departure_datetime + timedelta(minutes=flight_time)

            # Создаем embed
            embed = FlightCard.create_embed(
                f"Предпросмотр рейса {flight_number}",
                f"**{self.airline_data['name']}** • `{self.airline_data['iata']}`",
                FlightStyles.COLORS['primary']
            )

            embed.add_field(
                name="✈️ Номер рейса",
                value=f"`{flight_number}`",
                inline=True
            )

            embed.add_field(
                name="🛣️ Маршрут",
                value=f"`{departure_code}` → `{arrival_code}`",
                inline=True
            )

            embed.add_field(
                name="🏢 Аэропорты",
                value=f"🛫 **Вылет:** {departure_name}\n🛬 **Прилет:** {arrival_name}",
                inline=False
            )

            embed.add_field(
                name="📅 Дата",
                value=self.selected_date,
                inline=True
            )

            embed.add_field(
                name="⏰ Время",
                value=f"**Вылет:** {self.selected_time}\n**Прилет:** {arrival_time.strftime('%H:%M')}",
                inline=True
            )

            embed.add_field(
                name="🛩️ Воздушное судно",
                value=aircraft,
                inline=True
            )

            embed.add_field(
                name="⏱️ Тайминги",
                value=f"**📋 Регистрация:** `{checkin_open.strftime('%H:%M')} — {checkin_close.strftime('%H:%M')}`\n**🎮 Сервер:** `{server_open.strftime('%H:%M')} — {server_close.strftime('%H:%M')}`",
                inline=False
            )

            embed.add_field(
                name="⏳ В пути",
                value=f"{flight_time} минут",
                inline=True
            )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            error_embed = FlightCard.create_embed(
                "Ошибка предпросмотра",
                f"Произошла ошибка при создании предпросмотра:\n```{str(e)}```",
                FlightStyles.COLORS['error']
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)

    async def create_flight(self, interaction: discord.Interaction):
        """Создание рейса"""
        if not all([self.selected_date, self.selected_time, self.selected_profile]):
            await interaction.response.send_message(
                embed=FlightCard.create_embed(
                    "Не все поля заполнены",
                    "Пожалуйста, заполните все поля перед созданием рейса.",
                    FlightStyles.COLORS['error']
                ),
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            try:
                departure_datetime = datetime.strptime(f"{self.selected_date} {self.selected_time}", "%d.%m.%Y %H:%M")
            except (ValueError, TypeError):
                await interaction.followup.send("❌ Некорректная дата или время", ephemeral=True)
                return

            profile = self.selected_profile or {
                'checkin_open': 55, 'checkin_close': 15,
                'server_open': 50, 'server_close': 10
            }

            # Определяем информацию в зависимости от режима
            if self.selected_route:
                # Быстрый режим: используем данные из маршрута
                route = self.selected_route
                flight_number = route.get('flight_number')
                route_name = route.get('name', 'Неизвестно')
                departure_airport = route.get('departure_airport', 'Неизвестно')
                departure_code = route.get('departure_code', '???')
                departure_icao = route.get('departure_icao', '')
                arrival_airport = route.get('arrival_airport', 'Неизвестно')
                arrival_code = route.get('arrival_code', '???')
                arrival_icao = route.get('arrival_icao', '')
                flight_time = route.get('flight_time', 120)
                aircraft = route.get('aircraft', 'Неизвестно')

                # Получаем ссылки на игры из аэропортов
                departure_game_link = ""
                arrival_game_link = ""

                for airport in self.airports:
                    if airport.get('code') == departure_code:
                        departure_game_link = airport.get('game_link', '')
                    elif airport.get('code') == arrival_code:
                        arrival_game_link = airport.get('game_link', '')

            else:
                # Авто/ручной режим
                if not self.custom_flight_number:
                    await interaction.followup.send(
                        embed=FlightCard.create_embed(
                            "Отсутствует номер рейса",
                            "Пожалуйста, укажите номер рейса.",
                            FlightStyles.COLORS['error']
                        ),
                        ephemeral=True
                    )
                    return

                flight_number = self.custom_flight_number

                # Получаем данные из полей ввода
                departure_code = "???"
                arrival_code = "???"
                departure_airport = "Неизвестно"
                arrival_airport = "Неизвестно"
                departure_icao = ""
                arrival_icao = ""
                aircraft = "Неизвестно"
                flight_time = 120

                # Пытаемся получить данные из полей
                for child in self.children:
                    if isinstance(child, TextInput):
                        if 'вылета' in child.label.lower() and 'код' in child.label.lower():
                            departure_code = child.value.upper()
                        elif 'прилета' in child.label.lower() and 'код' in child.label.lower():
                            arrival_code = child.value.upper()
                        elif 'вылета' in child.label.lower() and 'название' in child.label.lower():
                            departure_airport = child.value
                        elif 'прилета' in child.label.lower() and 'название' in child.label.lower():
                            arrival_airport = child.value
                        elif 'судно' in child.label.lower():
                            aircraft = child.value

                # Если в авто режиме, пытаемся определить коды через сервис
                if self.airport_service and (departure_code == '???' or arrival_code == '???'):
                    # Ищем названия аэропортов
                    departure_name = ""
                    arrival_name = ""

                    for child in self.children:
                        if isinstance(child, TextInput):
                            if 'вылета' in child.label.lower() and 'код' not in child.label.lower():
                                departure_name = child.value
                            elif 'прилета' in child.label.lower() and 'код' not in child.label.lower():
                                arrival_name = child.value

                    if departure_name:
                        dep_info = await self.airport_service.search_airport_by_name(departure_name)
                        if dep_info:
                            departure_code = dep_info['iata']
                            departure_icao = dep_info.get('icao', '')
                            departure_airport = dep_info.get('name', departure_name)

                    if arrival_name:
                        arr_info = await self.airport_service.search_airport_by_name(arrival_name)
                        if arr_info:
                            arrival_code = arr_info['iata']
                            arrival_icao = arr_info.get('icao', '')
                            arrival_airport = arr_info.get('name', arrival_name)

                route_name = f"{departure_airport} - {arrival_airport}"
                departure_game_link = ""
                arrival_game_link = ""

                # Ищем ссылки на игры в аэропортах
                for airport in self.airports:
                    if airport.get('code') == departure_code:
                        departure_game_link = airport.get('game_link', '')
                    elif airport.get('code') == arrival_code:
                        arrival_game_link = airport.get('game_link', '')

            # Проверяем номер рейса
            if not flight_number:
                await interaction.followup.send(
                    embed=FlightCard.create_embed(
                        "Ошибка номера рейса",
                        "Не удалось определить номер рейса.",
                        FlightStyles.COLORS['error']
                    ),
                    ephemeral=True
                )
                return

            # Проверяем формат номера рейса
            if not self._validate_flight_number(flight_number):
                # Пытаемся исправить формат
                airline_iata = self.airline_data.get('iata', 'SU')
                # Извлекаем цифры из номера
                numbers = re.findall(r'\d+', flight_number)
                if numbers:
                    flight_number = f"{airline_iata}{numbers[0]}"
                else:
                    flight_number = f"{airline_iata}001"

            # Рассчитываем времена
            checkin_open = departure_datetime - timedelta(minutes=profile.get('checkin_open', 55))
            checkin_close = departure_datetime - timedelta(minutes=profile.get('checkin_close', 15))
            server_open = departure_datetime - timedelta(minutes=profile.get('server_open', 50))
            server_close = departure_datetime - timedelta(minutes=profile.get('server_close', 10))
            arrival_time = departure_datetime + timedelta(minutes=flight_time)

            # Создаем рейс в базе данных
            flight_ref = self.db.collection('flights')

            flight_data = {
                'airline_id': self.airline_id,
                'airline_name': self.airline_data['name'],
                'airline_iata': self.airline_data['iata'],
                'flight_number': flight_number,
                'route_name': route_name,
                'departure_airport': departure_airport,
                'departure_code': departure_code,
                'departure_icao': departure_icao,
                'departure_game_link': departure_game_link,
                'arrival_airport': arrival_airport,
                'arrival_code': arrival_code,
                'arrival_icao': arrival_icao,
                'arrival_game_link': arrival_game_link,
                'aircraft': aircraft,
                'departure_date': self.selected_date,
                'departure_datetime': departure_datetime.isoformat(),
                'departure_time': self.selected_time,
                'arrival_datetime': arrival_time.isoformat(),
                'arrival_time': arrival_time.strftime("%H:%M"),
                'flight_time': flight_time,
                'checkin_open': checkin_open.strftime("%H:%M"),
                'checkin_close': checkin_close.strftime("%H:%M"),
                'server_open': server_open.strftime("%H:%M"),
                'server_close': server_close.strftime("%H:%M"),
                'timing_profile': profile.get('name'),
                'status': 'scheduled',
                'created_at': datetime.now().isoformat(),
                'created_by': str(interaction.user.id),
                'subscriptions': 0,
            }

            flight_doc = flight_ref.add(flight_data)
            flight_id = flight_doc[1].id

            # Обновляем статистику авиакомпании
            airline_ref = self.db.collection('airlines').document(self.airline_id)
            airline_ref.update({
                'statistics.flights_created': firestore.Increment(1)
            })

            # Публикуем рейс у партнеров
            published_count = await self.publish_to_partners(interaction, flight_data, flight_id)

            # Создаем Embed для подтверждения
            embed = FlightCard.create_embed(
                f"Рейс {flight_number} успешно создан!",
                f"**{self.airline_data['name']}**",
                FlightStyles.COLORS['success']
            )

            embed.add_field(
                name="Основная информация",
                value=f"**Рейс:** {flight_number}\n**Маршрут:** {departure_code} → {arrival_code}\n**ВС:** {aircraft}",
                inline=False
            )

            embed.add_field(
                name="Расписание",
                value=f"**Дата:** {self.selected_date}\n**Вылет:** {self.selected_time}\n**Прилет:** {arrival_time.strftime('%H:%M')}\n**В пути:** {flight_time} мин",
                inline=False
            )

            if published_count > 0:
                embed.add_field(
                    name="📢 Публикация",
                    value=f"Рейс опубликован у **{published_count}** партнеров",
                    inline=False
                )

            # Создаем View для управления рейсом
            class FlightManagementView(View):
                def __init__(self, flight_id: str, bot):
                    super().__init__(timeout=180)
                    self.flight_id = flight_id
                    self.bot = bot

                @discord.ui.button(label="👁️ Просмотр", style=discord.ButtonStyle.primary, row=0)
                async def view_button(self, interaction: discord.Interaction, button: Button):
                    flight_doc = self.bot.data.db.collection('flights').document(self.flight_id).get()
                    if flight_doc.exists:
                        flight_data = flight_doc.to_dict()

                        embed = FlightCard.create_embed(
                            f"Информация о рейсе {flight_data['flight_number']}",
                            f"**{flight_data['airline_name']}**",
                            FlightStyles.COLORS['info']
                        )

                        embed.add_field(
                            name="Маршрут",
                            value=f"{flight_data['departure_airport']} → {flight_data['arrival_airport']}",
                            inline=False
                        )

                        embed.add_field(
                            name="Статус",
                            value=FlightCard.create_status_badge(flight_data['status']),
                            inline=True
                        )

                        embed.add_field(
                            name="Дата",
                            value=flight_data['departure_date'],
                            inline=True
                        )

                        await interaction.response.send_message(embed=embed, ephemeral=True)

            view = FlightManagementView(flight_id, self.bot)

            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            error_embed = FlightCard.create_embed(
                "Ошибка при создании",
                f"Произошла ошибка при создании рейса:\n```{str(e)[:500]}```",
                FlightStyles.COLORS['error']
            )
            await interaction.followup.send(embed=error_embed, ephemeral=True)

    def _validate_flight_number(self, flight_number: str) -> bool:
        """Валидация номера рейса"""
        # Формат: 2-3 буквы IATA + 1-4 цифры
        pattern = r'^[A-Z]{2,3}\d{1,4}$'
        return bool(re.match(pattern, flight_number.upper()))

    async def publish_to_partners(self, interaction: discord.Interaction, flight_data: dict, flight_id: str):
        """Публикация рейса у партнеров"""
        try:
            db = self.db
            partners_ref = db.collection('partners')
            partners = partners_ref.where('status', '==', 'active').get()

            published_count = 0

            # Создаем красивое сообщение для партнеров
            partner_embed = discord.Embed(
                title=f"✈️ Новый рейс: {flight_data['flight_number']}",
                description=f"**{flight_data['airline_name']}** объявляет новый рейс!",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )

            # Основная информация
            partner_embed.add_field(
                name="Маршрут",
                value=f"**{flight_data['departure_airport']}** ({flight_data['departure_code']}) → **{flight_data['arrival_airport']}** ({flight_data['arrival_code']})",
                inline=False
            )

            partner_embed.add_field(
                name="Расписание",
                value=f"**📅 Дата:** {flight_data['departure_date']}\n**🕐 Вылет:** {flight_data['departure_time']}\n**🛬 Прилет:** {flight_data['arrival_time']}",
                inline=True
            )

            partner_embed.add_field(
                name="Детали",
                value=f"**✈️ Рейс:** {flight_data['flight_number']}\n**🛩️ ВС:** {flight_data['aircraft']}\n**⏱️ В пути:** {flight_data['flight_time']} мин",
                inline=True
            )

            # Тайминги
            partner_embed.add_field(
                name="⏰ Тайминги",
                value=f"**📋 Регистрация:** {flight_data['checkin_open']} - {flight_data['checkin_close']}\n**🎮 Сервер:** {flight_data['server_open']} - {flight_data['server_close']}",
                inline=False
            )

            # Создаем View для пассажиров
            class PassengerActions(View):
                def __init__(self, flight_id: str, bot):
                    super().__init__(timeout=None)
                    self.flight_id = flight_id
                    self.bot = bot

                @discord.ui.button(label="🔔 Подписаться", style=discord.ButtonStyle.success, emoji="🔔", row=0)
                async def subscribe_button(self, interaction: discord.Interaction, button: Button):
                    if interaction.is_expired(): return
                    try: await interaction.response.defer(ephemeral=True)
                    except: return
                    await self.handle_subscription(interaction)

                @discord.ui.button(label="ℹ️ Информация", style=discord.ButtonStyle.secondary, emoji="ℹ️", row=0)
                async def info_button(self, interaction: discord.Interaction, button: Button):
                    if interaction.is_expired(): return
                    try: await interaction.response.defer(ephemeral=True)
                    except: return
                    await self.show_info(interaction)

                async def handle_subscription(self, interaction: discord.Interaction):
                    subscriptions_ref = self.bot.data.db.collection('subscriptions')

                    # Проверяем, есть ли уже подписка
                    query = subscriptions_ref.where(
                        'user_id', '==', str(interaction.user.id)
                    ).where(
                        'flight_id', '==', self.flight_id
                    ).limit(1)
                    existing = query.get()

                    if len(existing) > 0:
                        embed = discord.Embed(
                            title="ℹ️ Уже подписаны",
                            description="Вы уже подписаны на уведомления об этом рейсе.",
                            color=discord.Color.blue()
                        )
                        await interaction.followup.send(embed=embed, ephemeral=True)
                        return

                    # Создаем подписку
                    subscription_data = {
                        'user_id': str(interaction.user.id),
                        'username': str(interaction.user),
                        'flight_id': self.flight_id,
                        'created_at': datetime.now().isoformat(),
                        'notifications': ['24h', '6h', '1h', '30min', 'server_open'],
                        'notifications_sent': []
                    }

                    self.bot.data.db.collection('subscriptions').add(subscription_data)

                    # Обновляем счетчик подписок
                    flight_ref = self.bot.data.db.collection('flights').document(self.flight_id)
                    flight_ref.update({
                        'subscriptions': firestore.Increment(1)
                    })

                    # Отправляем подтверждение
                    success_embed = discord.Embed(
                        title="✅ Подписка активирована",
                        description="Вы успешно подписались на уведомления о рейсе!",
                        color=discord.Color.green()
                    )

                    await interaction.followup.send(embed=success_embed, ephemeral=True)

                async def show_info(self, interaction: discord.Interaction):
                    flight_doc = self.bot.data.db.collection('flights').document(self.flight_id).get()
                    if flight_doc.exists:
                        flight_data = flight_doc.to_dict()

                        embed = discord.Embed(
                            title=f"ℹ️ Информация о рейсе {flight_data['flight_number']}",
                            description=f"**{flight_data['airline_name']}**",
                            color=discord.Color.blue()
                        )

                        embed.add_field(
                            name="Маршрут",
                            value=f"{flight_data['departure_airport']} → {flight_data['arrival_airport']}",
                            inline=False
                        )

                        embed.add_field(
                            name="Расписание",
                            value=f"Дата: {flight_data['departure_date']}\nВылет: {flight_data['departure_time']}\nПрилет: {flight_data['arrival_time']}",
                            inline=True
                        )

                        await interaction.followup.send(embed=embed, ephemeral=True)

            passenger_view = PassengerActions(flight_id, self.bot)

            # Публикуем у каждого партнера
            for partner in partners:
                partner_data = partner.to_dict()
                channel_id = partner_data.get('channel_id')

                if channel_id:
                    try:
                        channel = interaction.guild.get_channel(int(channel_id))
                        if channel and isinstance(channel, discord.TextChannel):
                            # Отправляем сообщение партнеру
                            await channel.send(embed=partner_embed, view=passenger_view)

                            # Обновляем статистику партнера
                            partner_ref = partners_ref.document(partner.id)
                            partner_ref.update({
                                'published_flights': firestore.Increment(1),
                                'last_published': datetime.now().isoformat()
                            })

                            published_count += 1

                    except Exception as e:
                        print(f"Ошибка публикации у партнера {channel_id}: {e}")

            # Логируем публикацию
            audit_channel_id = self.bot.CHANNEL_IDS.get("AUDIT_CHANNEL")
            if audit_channel_id and published_count > 0:
                audit_channel = interaction.guild.get_channel(audit_channel_id)
                if audit_channel:
                    audit_embed = discord.Embed(
                        title="📢 Публикация рейса",
                        description=f"Рейс опубликован в партнерской сети",
                        color=discord.Color.gold(),
                        timestamp=datetime.now()
                    )

                    audit_embed.add_field(name="✈️ Рейс", value=flight_data['flight_number'], inline=True)
                    audit_embed.add_field(name="🏢 Авиакомпания", value=flight_data['airline_name'], inline=True)
                    audit_embed.add_field(name="🤝 Партнеров", value=str(published_count), inline=True)

                    await audit_channel.send(embed=audit_embed)

            return published_count

        except Exception as e:
            print(f"Ошибка публикации у партнеров: {e}")
            return 0

class Flights(commands.Cog):
    """Управление рейсами авиакомпании"""

    def __init__(self, bot):
        self.bot = bot
        self.flight_status_updater.start()
        self.notification_sender.start()

    @app_commands.command(name="рейс", description="Создать новый рейс")
    async def create_flight_command(self, interaction: discord.Interaction):
        """Создание нового рейса с улучшенным интерфейсом"""
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)

        db = self.bot.data.db

        # Получаем авиакомпанию пользователя
        airlines_ref = db.collection('airlines')
        query = airlines_ref.where('owner_id', '==', str(interaction.user.id)).limit(1)
        results = query.get()

        if len(results) == 0:
            # Проверяем как сотрудник
            user_airlines = []
            all_airlines = airlines_ref.stream()

            for airline in all_airlines:
                airline_data = airline.to_dict()
                employees = airline_data.get('employees', [])

                if any(emp.get('user_id') == str(interaction.user.id) for emp in employees):
                    user_airlines.append((airline.id, airline_data))

            if not user_airlines:
                error_embed = FlightCard.create_embed(
                    "Доступ запрещен",
                    "У вас нет доступа к управлению авиакомпаниями.",
                    FlightStyles.COLORS['error']
                )
                await interaction.followup.send(embed=error_embed, ephemeral=True)
                return

            airline_id, airline_data = user_airlines[0]
        else:
            airline_data = results[0].to_dict()
            airline_id = results[0].id

        # Проверяем наличие маршрутов
        routes = airline_data.get('routes', [])
        timing_profiles = airline_data.get('timing_profiles', [])

        if not timing_profiles:
            timing_profiles = [
                {
                    'name': 'Стандартный',
                    'checkin_open': 55,
                    'checkin_close': 15,
                    'server_open': 50,
                    'server_close': 10,
                }
            ]

            airlines_ref.document(airline_id).update({
                'timing_profiles': timing_profiles,
                'default_timing_profile': 'Стандартный'
            })

        # Создаем улучшенный View
        view = EnhancedFlightCreationView(airline_id, airline_data, self.bot)

        # Создаем Embed
        embed = FlightCard.create_embed(
            "Создание рейса",
            "Выберите способ создания рейса",
            FlightStyles.COLORS['primary']
        )

        embed.add_field(
            name="🚀 Быстрый (из маршрутов)",
            value="Создать рейс из предустановленных маршрутов вашей авиакомпании",
            inline=False
        )

        embed.add_field(
            name="✨ Авто (определение кодов)",
            value="Система автоматически определит коды аэропортов по названиям",
            inline=False
        )

        embed.add_field(
            name="🎫 Ручной ввод",
            value="Полностью ручное создание рейса",
            inline=False
        )

        embed.add_field(
            name="ℹ️ Информация",
            value=f"**Авиакомпания:** {airline_data['name']} ({airline_data['iata']})\n**Маршрутов:** {len(routes)}\n**Профилей таймингов:** {len(timing_profiles)}",
            inline=False
        )

        if airline_data.get('logo_url'):
            embed.set_thumbnail(url=airline_data['logo_url'])

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="рейсы", description="Просмотр всех рейсов авиакомпании")
    async def list_flights_command(self, interaction: discord.Interaction):
        """Просмотр всех рейсов авиакомпании"""
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)

        db = self.bot.data.db

        # Получаем авиакомпанию пользователя
        airlines_ref = db.collection('airlines')
        query = airlines_ref.where('owner_id', '==', str(interaction.user.id)).limit(1)
        results = query.get()

        if len(results) == 0:
            # Проверяем как сотрудник
            user_airlines = []
            all_airlines = airlines_ref.stream()

            for airline in all_airlines:
                airline_data = airline.to_dict()
                employees = airline_data.get('employees', [])

                if any(emp.get('user_id') == str(interaction.user.id) for emp in employees):
                    user_airlines.append((airline.id, airline_data))

            if not user_airlines:
                error_embed = FlightCard.create_embed(
                    "Доступ запрещен",
                    "У вас нет доступа к управлению авиакомпаниями.",
                    FlightStyles.COLORS['error']
                )
                await interaction.followup.send(embed=error_embed, ephemeral=True)
                return

            airline_id, airline_data = user_airlines[0]
        else:
            airline_data = results[0].to_dict()
            airline_id = results[0].id

        # Получаем рейсы авиакомпании
        flights_ref = db.collection('flights')
        flights_query = flights_ref.where('airline_id', '==', airline_id)
        flights = flights_query.get()

        if len(flights) == 0:
            embed = FlightCard.create_embed(
                "Рейсы не найдены",
                "У вашей авиакомпании пока нет созданных рейсов.",
                FlightStyles.COLORS['warning']
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Сортируем рейсы по дате вылета
        flights_list = []
        for flight in flights:
            flight_data = flight.to_dict()
            flights_list.append({
                'id': flight.id,
                'data': flight_data
            })

        flights_list.sort(key=lambda x: x['data'].get('departure_datetime', ''))

        # Создаем Embed со списком рейсов
        embed = FlightCard.create_embed(
            f"Рейсы {airline_data['name']}",
            f"Всего рейсов: **{len(flights_list)}**",
            FlightStyles.COLORS['info']
        )

        # Группируем рейсы по статусу
        status_groups = {}
        for flight in flights_list:
            status = flight['data'].get('status', 'scheduled')
            if status not in status_groups:
                status_groups[status] = []
            status_groups[status].append(flight)

        # Показываем ближайшие рейсы
        today = datetime.now().date()
        upcoming_flights = []

        for flight in flights_list:
            flight_data = flight['data']
            departure_str = flight_data.get('departure_datetime')
            if departure_str:
                try:
                    departure_time = datetime.fromisoformat(departure_str.replace('Z', '+00:00'))
                    if departure_time.date() >= today:
                        upcoming_flights.append(flight)
                except:
                    pass

        # Ближайшие рейсы
        if upcoming_flights[:5]:
            upcoming_text = ""
            for flight in upcoming_flights[:5]:
                flight_data = flight['data']
                upcoming_text += f"• **{flight_data['flight_number']}** - {flight_data['departure_code']} → {flight_data['arrival_code']}\n"
                upcoming_text += f"  📅 {flight_data['departure_date']} {flight_data['departure_time']} | {FlightCard.create_status_badge(flight_data.get('status', 'scheduled'))}\n\n"

            embed.add_field(
                name="📅 Ближайшие рейсы",
                value=upcoming_text,
                inline=False
            )

        # Статистика по статусам
        status_text = ""
        for status, flights_in_status in status_groups.items():
            status_emoji = {
                'scheduled': '📅',
                'boarding': '🎫',
                'departed': '🛫',
                'delayed': '🕒',
                'cancelled': '❌',
                'completed': '✅'
            }.get(status, '❓')

            status_name = {
                'scheduled': 'По расписанию',
                'boarding': 'Посадка',
                'departed': 'В пути',
                'delayed': 'Задержано',
                'cancelled': 'Отменено',
                'completed': 'Завершено'
            }.get(status, 'Неизвестно')

            status_text += f"{status_emoji} {status_name}: **{len(flights_in_status)}**\n"

        embed.add_field(
            name="📊 Статистика",
            value=status_text,
            inline=True
        )

        # Создаем View для навигации
        class FlightListView(View):
            def __init__(self, flights: list, airline_name: str):
                super().__init__(timeout=180)
                self.flights = flights
                self.airline_name = airline_name
                self.current_page = 0
                self.page_size = 5

            @discord.ui.button(label="⬅️ Назад", style=discord.ButtonStyle.secondary, row=0)
            async def prev_button(self, interaction: discord.Interaction, button: Button):
                if self.current_page > 0:
                    self.current_page -= 1
                    await self.update_embed(interaction)

            @discord.ui.button(label="➡️ Вперед", style=discord.ButtonStyle.secondary, row=0)
            async def next_button(self, interaction: discord.Interaction, button: Button):
                if (self.current_page + 1) * self.page_size < len(self.flights):
                    self.current_page += 1
                    await self.update_embed(interaction)

            @discord.ui.button(label="🔍 Поиск", style=discord.ButtonStyle.primary, row=0)
            async def search_button(self, interaction: discord.Interaction, button: Button):
                await interaction.response.send_modal(FlightSearchModal(self.flights))

            async def update_embed(self, interaction: discord.Interaction):
                start_idx = self.current_page * self.page_size
                end_idx = min(start_idx + self.page_size, len(self.flights))

                page_embed = FlightCard.create_embed(
                    f"Рейсы {self.airline_name}",
                    f"Страница {self.current_page + 1}/{(len(self.flights) + self.page_size - 1) // self.page_size}",
                    FlightStyles.COLORS['info']
                )

                for i in range(start_idx, end_idx):
                    flight = self.flights[i]
                    flight_data = flight['data']

                    flight_text = f"**{flight_data['flight_number']}** - {flight_data['departure_code']} → {flight_data['arrival_code']}\n"
                    flight_text += f"📅 {flight_data['departure_date']} {flight_data['departure_time']}\n"
                    flight_text += f"✈️ {FlightCard.create_status_badge(flight_data.get('status', 'scheduled'))}\n"
                    flight_text += f"🛩️ {flight_data.get('aircraft', 'Неизвестно')}\n"

                    page_embed.add_field(
                        name=f"Рейс #{i+1}",
                        value=flight_text,
                        inline=True
                    )

                await interaction.response.edit_message(embed=page_embed, view=self)

        view = FlightListView(flights_list, airline_data['name'])
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @tasks.loop(minutes=5)
    async def flight_status_updater(self):
        """Автоматическое обновление статусов рейсов"""
        try:
            db = self.bot.data.db
            flights_ref = db.collection('flights')

            now = datetime.now()

            scheduled_flights = flights_ref.where('status', '==', 'scheduled').get()
            boarding_flights = flights_ref.where('status', '==', 'boarding').get()
            departed_flights = flights_ref.where('status', '==', 'departed').get()

            all_flights = list(scheduled_flights) + list(boarding_flights) + list(departed_flights)

            for flight in all_flights:
                flight_data = flight.to_dict()
                flight_id = flight.id

                try:
                    departure_str = flight_data.get('departure_datetime')
                    if not departure_str:
                        continue

                    departure_time = datetime.fromisoformat(departure_str.replace('Z', '+00:00'))

                    checkin_close_str = flight_data.get('checkin_close')
                    departure_date_str = flight_data.get('departure_date')

                    if checkin_close_str and departure_date_str:
                        try:
                            close_hour, close_minute = map(int, checkin_close_str.split(':'))
                            dep_date = datetime.strptime(departure_date_str, "%d.%m.%Y")
                            checkin_close_time = dep_date.replace(hour=close_hour, minute=close_minute)

                            if now >= checkin_close_time and departure_time > now:
                                if flight_data.get('status') == 'scheduled':
                                    flights_ref.document(flight_id).update({
                                        'status': 'boarding',
                                        'updated_at': datetime.now().isoformat()
                                    })
                        except Exception as e:
                            print(f"Ошибка обработки времени регистрации: {e}")

                    if now >= departure_time:
                        if flight_data.get('status') != 'departed':
                            flights_ref.document(flight_id).update({
                                'status': 'departed',
                                'updated_at': datetime.now().isoformat(),
                                'actual_departure': now.isoformat()
                            })

                    if flight_data.get('status') == 'departed':
                        actual_departure_str = flight_data.get('actual_departure')
                        flight_time = flight_data.get('flight_time', 120)

                        if actual_departure_str:
                            try:
                                actual_departure = datetime.fromisoformat(actual_departure_str.replace('Z', '+00:00'))
                                completion_time = actual_departure + timedelta(minutes=flight_time)

                                if now >= completion_time:
                                    flights_ref.document(flight_id).update({
                                        'status': 'completed',
                                        'updated_at': datetime.now().isoformat()
                                    })

                                    airline_id = flight_data.get('airline_id')
                                    if airline_id:
                                        airline_ref = db.collection('airlines').document(airline_id)
                                        airline_ref.update({
                                            'statistics.flights_completed': firestore.Increment(1)
                                        })
                            except:
                                pass

                except Exception as e:
                    print(f"Ошибка обновления статуса рейса {flight_id}: {e}")

        except Exception as e:
            print(f"Ошибка в flight_status_updater: {e}")

    @tasks.loop(minutes=1)
    async def notification_sender(self):
        """Отправка уведомлений о рейсах"""
        try:
            db = self.bot.data.db

            subscriptions_ref = db.collection('subscriptions')
            flights_ref = db.collection('flights')

            now = datetime.now()

            subscriptions = list(subscriptions_ref.stream())

            for sub in subscriptions:
                try:
                    sub_data = sub.to_dict()
                    user_id = sub_data.get('user_id')
                    flight_id = sub_data.get('flight_id')
                    notifications_sent = sub_data.get('notifications_sent', [])

                    flight_doc = flights_ref.document(flight_id).get()
                    if not flight_doc.exists:
                        continue

                    flight_data = flight_doc.to_dict()

                    if flight_data.get('status') in ['cancelled', 'completed']:
                        continue

                    departure_str = flight_data.get('departure_datetime')
                    if not departure_str:
                        continue

                    departure_time = datetime.fromisoformat(departure_str.replace('Z', '+00:00'))

                    notifications_to_send = []

                    if '24h' not in notifications_sent:
                        time_until = (departure_time - now).total_seconds()
                        if 23.5 * 3600 < time_until <= 24.5 * 3600:
                            notifications_to_send.append(('24h', "24 часа"))

                    if '6h' not in notifications_sent:
                        time_until = (departure_time - now).total_seconds()
                        if 5.5 * 3600 < time_until <= 6.5 * 3600:
                            notifications_to_send.append(('6h', "6 часов"))

                    if '1h' not in notifications_sent:
                        time_until = (departure_time - now).total_seconds()
                        if 0.5 * 3600 < time_until <= 1.5 * 3600:
                            notifications_to_send.append(('1h', "1 час"))

                    if '30min' not in notifications_sent:
                        time_until = (departure_time - now).total_seconds()
                        if 25 * 60 < time_until <= 35 * 60:
                            notifications_to_send.append(('30min', "30 минут"))

                    for notification_type, text in notifications_to_send:
                        try:
                            user = await self.bot.fetch_user(int(user_id))
                            if user:
                                embed = FlightCard.create_embed(
                                    f"Напоминание о рейсе",
                                    f"До {text} до вылета!",
                                    FlightStyles.COLORS['info']
                                )

                                embed.add_field(
                                    name="Рейс",
                                    value=f"{flight_data.get('flight_number', '')} - {flight_data.get('airline_name', '')}",
                                    inline=False
                                )

                                embed.add_field(
                                    name="Детали",
                                    value=f"Вылет: {flight_data.get('departure_airport', '')}\nПрилет: {flight_data.get('arrival_airport', '')}\nДата: {flight_data.get('departure_date', '')}\nВремя: {flight_data.get('departure_time', '')}",
                                    inline=False
                                )

                                await user.send(embed=embed)

                                subscriptions_ref.document(sub.id).update({
                                    'notifications_sent': firestore.ArrayUnion([notification_type])
                                })

                        except Exception as e:
                            print(f"Ошибка отправки уведомления: {e}")

                except Exception as e:
                    print(f"Ошибка обработки подписки: {e}")

        except Exception as e:
            print(f"Ошибка в notification_sender: {e}")

    @flight_status_updater.before_loop
    async def before_flight_status_updater(self):
        await self.bot.wait_until_ready()

    @notification_sender.before_loop
    async def before_notification_sender(self):
        await self.bot.wait_until_ready()

class FlightSearchModal(Modal, title="🔍 Поиск рейса"):
    def __init__(self, flights: list):
        super().__init__()
        self.flights = flights

        self.flight_number = TextInput(
            label="Номер рейса",
            placeholder="Например: SU123",
            required=False,
            max_length=10
        )

        self.departure_code = TextInput(
            label="Код вылета",
            placeholder="Например: SVO",
            required=False,
            max_length=3
        )

        self.arrival_code = TextInput(
            label="Код прилета",
            placeholder="Например: LED",
            required=False,
            max_length=3
        )

        self.add_item(self.flight_number)
        self.add_item(self.departure_code)
        self.add_item(self.arrival_code)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        # Фильтруем рейсы
        filtered_flights = []

        for flight in self.flights:
            flight_data = flight['data']
            matches = True

            if self.flight_number.value:
                if self.flight_number.value.upper() not in flight_data.get('flight_number', '').upper():
                    matches = False

            if self.departure_code.value:
                if self.departure_code.value.upper() != flight_data.get('departure_code', '').upper():
                    matches = False

            if self.arrival_code.value:
                if self.arrival_code.value.upper() != flight_data.get('arrival_code', '').upper():
                    matches = False

            if matches:
                filtered_flights.append(flight)

        if not filtered_flights:
            embed = FlightCard.create_embed(
                "Рейсы не найдены",
                "По вашему запросу рейсов не найдено.",
                FlightStyles.COLORS['warning']
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        # Создаем Embed с результатами
        embed = FlightCard.create_embed(
            "Результаты поиска",
            f"Найдено рейсов: **{len(filtered_flights)}**",
            FlightStyles.COLORS['info']
        )

        for i, flight in enumerate(filtered_flights[:5], 1):
            flight_data = flight['data']

            flight_text = f"**{flight_data['flight_number']}** - {flight_data['departure_code']} → {flight_data['arrival_code']}\n"
            flight_text += f"📅 {flight_data['departure_date']} {flight_data['departure_time']}\n"
            flight_text += f"✈️ {FlightCard.create_status_badge(flight_data.get('status', 'scheduled'))}\n"
            flight_text += f"🛩️ {flight_data.get('aircraft', 'Неизвестно')}\n"

            embed.add_field(
                name=f"Рейс #{i}",
                value=flight_text,
                inline=True
            )

        if len(filtered_flights) > 5:
            embed.set_footer(text=f"Показано 5 из {len(filtered_flights)} найденных рейсов")

        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Flights(bot))