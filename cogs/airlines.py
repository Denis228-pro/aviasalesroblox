# [file name]: airlines.py
import firebase_admin
from firebase_admin import firestore
import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord.ui import Button, View, Modal, TextInput, Select
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import asyncio
import re

# Импортируем сервис аэропортов
try:
    from .airport_service import AirportService
except ImportError:
    class AirportService:
        def __init__(self, bot):
            self.bot = bot

        async def initialize(self):
            pass

        async def close(self):
            pass

        async def search_airport_by_name(self, name: str):
            return None

        async def search_airport_by_code(self, code: str):
            return None

        def generate_flight_number(self, airline_iata: str, route_number: str):
            return f"{airline_iata}{route_number}"

from utils.decorators import handle_errors
from firebase_admin import firestore

class Airlines(commands.Cog):
    """Управление авиакомпаниями с автоматизацией"""

    def __init__(self, bot):
        self.bot = bot
        self.airport_service = None
        self.db = None

    async def cog_load(self):
        """Загрузка сервиса при инициализации кога"""
        self.db = self.bot.data.db
        self.airport_service = AirportService(self.bot)
        await self.airport_service.initialize()
        print("✅ Сервис аэропортов инициализирован")

    async def cog_unload(self):
        """Выгрузка сервиса"""
        if self.airport_service:
            await self.airport_service.close()

    async def _get_user_airline(self, user_id: Any) -> Optional[Dict]:
        """Получение авиакомпании пользователя"""
        # Попробуем получить из кэша через DatabaseHandler
        airline = await self.bot.data.get_airline_by_owner(str(user_id))
        if airline:
            return {'id': airline['id'], 'data': airline}

        # Если не нашли как владельца, ищем как сотрудника
        airlines_ref = self.db.collection('airlines')
        all_airlines = airlines_ref.stream()
        for airline_doc in all_airlines:
            airline_data = airline_doc.to_dict()
            employees = airline_data.get('employees', [])

            if any(emp.get('user_id') == str(user_id) for emp in employees):
                return {'id': airline_doc.id, 'data': airline_data}

        return None

    @app_commands.command(name="настройка", description="Настройки вашей авиакомпании")
    @handle_errors("Ошибка при открытии настроек авиакомпании")
    async def airline_settings(self, interaction: discord.Interaction):
        """Панель управления авиакомпанией"""
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            
            try:
                airline_info = await self._get_user_airline(str(interaction.user.id))
            except Exception as e:
                print(f"Error getting airline: {e}")
                airline_info = None

            if not airline_info:
                await interaction.followup.send(
                    "❌ У вас нет зарегистрированной авиакомпании!",
                    ephemeral=True
                )
                return

            airline_data = airline_info['data']
            airline_id = airline_info['id']

            days_active = 0
            if 'created_at' in airline_data:
                try:
                    created_date = datetime.fromisoformat(
                        airline_data['created_at'].replace('Z', '+00:00'))
                    days_active = (datetime.now() - created_date).days
                except:
                    pass

            embed = discord.Embed(
                title=f"⚙️ Панель управления: {airline_data['name']}",
                description="Управляйте вашей авиакомпанией и просматривайте статистику",
                color=discord.Color.from_rgb(46, 204, 113))

            if airline_data.get('logo_url'):
                embed.set_thumbnail(url=airline_data['logo_url'])

            embed.add_field(name="📋 Основная информация",
                           value=f"**IATA:** `{airline_data['iata']}`\n**Discord:** [Сервер]({airline_data['discord_server']})",
                           inline=True)

            embed.add_field(name="📅 Дата основания",
                           value=f"{days_active} дней назад",
                           inline=True)

            embed.add_field(name="📝 Описание",
                           value=f"```\n{airline_data.get('description', 'Не указано')}\n```",
                           inline=False)

            stats = airline_data.get('statistics', {})
            embed.add_field(
                name="📊 Статистика полетов",
                value=f"✅ Выполнено: **{stats.get('flights_completed', 0)}**\n"
                     f"🕒 Задержано: **{stats.get('flights_delayed', 0)}**\n"
                     f"❌ Отменено: **{stats.get('flights_cancelled', 0)}**\n"
                     f"🛫 Всего: **{stats.get('flights_created', 0)}**",
                inline=False)

            embed.set_footer(text="Aviasales Roblox • Система управления")

            class SettingsView(View):
                def __init__(self, airline_id: str, airline_data: dict, cog):
                    super().__init__(timeout=300)
                    self.airline_id = airline_id
                    self.airline_data = airline_data
                    self.cog = cog

                @discord.ui.button(label="✏️ Редактировать", style=discord.ButtonStyle.primary, emoji="📝", row=0)
                async def edit_button(self, interaction: discord.Interaction, button: Button):
                    modal = EditAirlineModal(self.airline_id, self.cog.bot)
                    await interaction.response.send_modal(modal)

                @discord.ui.button(label="🏢 Аэропорты (авто)", style=discord.ButtonStyle.success, emoji="🏢", row=0)
                async def airports_auto_button(self, interaction: discord.Interaction, button: Button):
                    airport_embed = discord.Embed(
                        title="🏢 Управление аэропортами",
                        description="Система автоматически определит коды аэропортов",
                        color=discord.Color.blue())

                    class AirportAutoView(View):
                        def __init__(self, airline_id: str, cog):
                            super().__init__(timeout=180)
                            self.airline_id = airline_id
                            self.cog = cog

                        @discord.ui.button(label="➕ Добавить аэропорт (авто)", style=discord.ButtonStyle.success, emoji="🔍")
                        async def add_airport_auto(self, interaction: discord.Interaction, button: Button):
                            modal = EnhancedAirportModal(self.airline_id, self.cog.airport_service)
                            await interaction.response.send_modal(modal)

                        @discord.ui.button(label="📋 Список аэропортов", style=discord.ButtonStyle.primary, emoji="📋")
                        async def list_airports(self, interaction: discord.Interaction, button: Button):
                            airline_ref = self.cog.db.collection('airlines').document(self.airline_id)
                            airline = airline_ref.get()

                            if airline.exists:
                                airline_data = airline.to_dict()
                                airports = airline_data.get('airports', [])

                                if not airports:
                                    await interaction.response.send_message(
                                        "❌ У вас нет добавленных аэропортов.",
                                        ephemeral=True
                                    )
                                    return

                                airports_text = ""
                                for i, airport in enumerate(airports, 1):
                                    icao_code = airport.get('icao', 'N/A')
                                    airports_text += f"{i}. **{airport.get('name', 'Без названия')}** (IATA: `{airport.get('code', 'N/A')}`, ICAO: `{icao_code}`)\n"

                                list_embed = discord.Embed(
                                    title=f"🏢 Аэропорты {airline_data['name']}",
                                    description=airports_text,
                                    color=discord.Color.blue())

                                await interaction.response.send_message(embed=list_embed, ephemeral=True)

                    airport_view = AirportAutoView(self.airline_id, self.cog)
                    await interaction.response.send_message(embed=airport_embed, view=airport_view, ephemeral=True)

                @discord.ui.button(label="🛣️ Маршруты", style=discord.ButtonStyle.secondary, emoji="🛣️", row=1)
                async def routes_button(self, interaction: discord.Interaction, button: Button):
                    routes_embed = discord.Embed(
                        title="🛣️ Управление маршрутами",
                        description="Автоматическое создание маршрутов с определением кодов аэропортов",
                        color=discord.Color.green())

                    class RoutesView(View):
                        def __init__(self, airline_id: str, airline_data: dict, cog):
                            super().__init__(timeout=180)
                            self.airline_id = airline_id
                            self.airline_data = airline_data
                            self.cog = cog

                        @discord.ui.button(label="➕ Добавить маршрут (авто)", style=discord.ButtonStyle.success, emoji="🔍")
                        async def add_route_auto(self, interaction: discord.Interaction, button: Button):
                            modal = EnhancedRouteModal(self.airline_id, self.airline_data, self.cog.airport_service)
                            await interaction.response.send_modal(modal)

                        @discord.ui.button(label="📋 Список маршрутов", style=discord.ButtonStyle.primary, emoji="📋")
                        async def list_routes(self, interaction: discord.Interaction, button: Button):
                            airline_ref = self.cog.db.collection('airlines').document(self.airline_id)
                            airline = airline_ref.get()

                            if airline.exists:
                                airline_data = airline.to_dict()
                                routes = airline_data.get('routes', [])

                                if not routes:
                                    await interaction.response.send_message(
                                        "❌ У вас нет добавленных маршрутов.",
                                        ephemeral=True
                                    )
                                    return

                                routes_text = ""
                                for i, route in enumerate(routes, 1):
                                    routes_text += f"{i}. **{route.get('name', 'Без названия')}**\n"
                                    routes_text += f"   ✈️ Рейс: `{route.get('flight_number', 'N/A')}`\n"
                                    routes_text += f"   🛣️ Маршрут: `{route.get('departure_code', 'N/A')}` → `{route.get('arrival_code', 'N/A')}`\n"
                                    routes_text += f"   🛩️ ВС: {route.get('aircraft', 'N/A')}\n"
                                    routes_text += f"   ⏱️ Время: {route.get('flight_time', 0)} мин\n\n"

                                list_embed = discord.Embed(
                                    title=f"🛣️ Маршруты {airline_data['name']}",
                                    description=routes_text,
                                    color=discord.Color.green())

                                list_embed.set_footer(text=f"Всего маршрутов: {len(routes)}")
                                await interaction.response.send_message(embed=list_embed, ephemeral=True)

                    routes_view = RoutesView(self.airline_id, self.airline_data, self.cog)
                    await interaction.response.send_message(embed=routes_embed, view=routes_view, ephemeral=True)

                @discord.ui.button(label="👥 Сотрудники", style=discord.ButtonStyle.secondary, emoji="👥", row=1)
                async def employees_button(self, interaction: discord.Interaction, button: Button):
                    employee_embed = discord.Embed(
                        title="👥 Управление сотрудниками",
                        description="Добавьте сотрудников для управления авиакомпанией",
                        color=discord.Color.blue())

                    class AddEmployeeButton(Button):
                        def __init__(self, airline_id: str):
                            super().__init__(label="➕ Добавить сотрудника", style=discord.ButtonStyle.success, emoji="➕")
                            self.airline_id = airline_id

                        async def callback(self, interaction: discord.Interaction):
                            modal = EmployeeModal(self.airline_id)
                            await interaction.response.send_modal(modal)

                    class ListEmployeesButton(Button):
                        def __init__(self, airline_id: str, airline_data: dict):
                            super().__init__(label="📋 Список сотрудников", style=discord.ButtonStyle.primary, emoji="📋")
                            self.airline_id = airline_id
                            self.airline_data = airline_data

                        async def callback(self, interaction: discord.Interaction):
                            db = interaction.client.data.db
                            airline_ref = db.collection('airlines').document(self.airline_id)
                            airline = airline_ref.get()

                            if airline.exists:
                                airline_data = airline.to_dict()
                                employees = airline_data.get('employees', [])

                                if not employees:
                                    await interaction.response.send_message(
                                        "❌ У вас нет добавленных сотрудников.",
                                        ephemeral=True
                                    )
                                    return

                                employees_text = ""
                                for i, employee in enumerate(employees, 1):
                                    employees_text += f"{i}. <@{employee.get('user_id')}>\n"

                                list_embed = discord.Embed(
                                    title=f"👥 Сотрудники {airline_data['name']}",
                                    description=employees_text,
                                    color=discord.Color.blue())

                                await interaction.response.send_message(embed=list_embed, ephemeral=True)

                    employee_view = View(timeout=180)
                    employee_view.add_item(AddEmployeeButton(self.airline_id))
                    employee_view.add_item(ListEmployeesButton(self.airline_id, self.airline_data))

                    await interaction.response.send_message(embed=employee_embed, view=employee_view, ephemeral=True)

                @discord.ui.button(label="🗑️ Удалить", style=discord.ButtonStyle.danger, emoji="⚠️", row=2)
                async def delete_button(self, interaction: discord.Interaction, button: Button):
                    await interaction.response.defer(ephemeral=True)
                    confirm_embed = discord.Embed(
                        title="⚠️ Подтверждение удаления",
                        description="Вы уверены, что хотите удалить авиакомпанию?",
                        color=discord.Color.red())

                    class ConfirmView(View):
                        def __init__(self, airline_id: str, airline_data: dict, bot):
                            super().__init__(timeout=180)
                            self.airline_id = airline_id
                            self.airline_data = airline_data
                            self.bot = bot

                        @discord.ui.button(label="✅ Да, удалить", style=discord.ButtonStyle.danger, emoji="🗑️")
                        async def confirm_delete(self, interaction: discord.Interaction, button: Button):
                            try:
                                mod_channel_id = self.bot.CHANNEL_IDS.get("AIRLINE_MODERATION_CHANNEL")

                                if mod_channel_id:
                                    mod_channel = interaction.guild.get_channel(mod_channel_id)
                                    if mod_channel:
                                        embed = discord.Embed(
                                            title="🗑️ Запрос на удаление авиакомпании",
                                            color=discord.Color.orange(),
                                            timestamp=datetime.now())

                                        embed.add_field(name="👤 Владелец", value=interaction.user.mention, inline=True)
                                        embed.add_field(name="✈️ Авиакомпания", value=self.airline_data['name'], inline=True)
                                        embed.add_field(name="🏷️ IATA", value=self.airline_data['iata'], inline=True)

                                        class DeleteModerationView(View):
                                            def __init__(self, airline_id: str, owner_id: str, bot, airline_data: dict):
                                                super().__init__(timeout=None)
                                                self.airline_id = airline_id
                                                self.owner_id = owner_id
                                                self.bot = bot
                                                self.airline_data = airline_data

                                            @discord.ui.button(label="✅ Подтвердить удаление", style=discord.ButtonStyle.danger)
                                            async def confirm_button(self, interaction: discord.Interaction, button: Button):
                                                db = interaction.client.data.db

                                                airlines_ref = db.collection('airlines')
                                                airline_ref = airlines_ref.document(self.airline_id)
                                                airline_data = airline_ref.get().to_dict()

                                                airline_ref.delete()

                                                flights_ref = db.collection('flights')
                                                flights_query = flights_ref.where('airline_id', '==', self.airline_id)
                                                flights = flights_query.get()

                                                for flight in flights:
                                                    flight.reference.delete()

                                                guild = interaction.guild
                                                member = guild.get_member(int(self.owner_id))
                                                if member:
                                                    role = discord.utils.get(guild.roles, name="Авиационное предприятие")
                                                    if role:
                                                        await member.remove_roles(role)

                                                try:
                                                    user = await interaction.client.fetch_user(int(self.owner_id))
                                                    await user.send(f"🗑️ Ваша авиакомпания **{airline_data['name']}** была удалена.")
                                                except:
                                                    pass

                                                audit_channel_id = self.bot.CHANNEL_IDS.get("AUDIT_CHANNEL")
                                                if audit_channel_id:
                                                    audit_channel = guild.get_channel(audit_channel_id)
                                                    if audit_channel:
                                                        audit_embed = discord.Embed(
                                                            title="🗑️ Авиакомпания удалена",
                                                            color=discord.Color.red(),
                                                            timestamp=datetime.now())
                                                        audit_embed.add_field(name="👤 Владелец", value=f"<@{self.owner_id}>", inline=True)
                                                        audit_embed.add_field(name="✈️ Авиакомпания", value=airline_data['name'], inline=True)
                                                        audit_embed.add_field(name="🏷️ IATA", value=airline_data['iata'], inline=True)
                                                        audit_embed.add_field(name="👮 Администратор", value=interaction.user.mention, inline=False)
                                                        await audit_channel.send(embed=audit_embed)

                                                embed.color = discord.Color.red()
                                                embed.add_field(name="🗑️ Статус", value="Удалено", inline=False)
                                                embed.add_field(name="👮 Администратор", value=interaction.user.mention, inline=False)

                                                try:
                                                    await interaction.response.edit_message(embed=embed, view=None)
                                                except discord.errors.NotFound:
                                                    await interaction.followup.send("✅ Авиакомпания удалена!", ephemeral=True)

                                            @discord.ui.button(label="❌ Отклонить удаление", style=discord.ButtonStyle.secondary)
                                            async def reject_button(self, interaction: discord.Interaction, button: Button):
                                                try:
                                                    user = await interaction.client.fetch_user(int(self.owner_id))
                                                    await user.send(f"❌ Ваш запрос на удаление авиакомпании **{self.airline_data['name']}** отклонен.")
                                                except:
                                                    pass

                                                embed.color = discord.Color.green()
                                                embed.add_field(name="❌ Статус", value="Удаление отклонено", inline=False)
                                                embed.add_field(name="👮 Администратор", value=interaction.user.mention, inline=False)

                                                try:
                                                    await interaction.response.edit_message(embed=embed, view=None)
                                                except discord.errors.NotFound:
                                                    await interaction.followup.send("❌ Удаление отклонено!", ephemeral=True)

                                        view = DeleteModerationView(self.airline_id, self.airline_data['owner_id'], self.bot, self.airline_data)
                                        await mod_channel.send(embed=embed, view=view)

                                await interaction.response.send_message(
                                    "✅ Запрос на удаление отправлен модераторам.",
                                    ephemeral=True
                                )
                            except Exception as e:
                                await interaction.response.send_message(
                                    f"❌ Ошибка при отправке запроса на удаление: {str(e)}",
                                    ephemeral=True
                                )

                        @discord.ui.button(label="❌ Отмена", style=discord.ButtonStyle.secondary)
                        async def cancel_delete(self, interaction: discord.Interaction, button: Button):
                            await interaction.response.send_message("❌ Удаление отменено.", ephemeral=True)

                    await interaction.response.send_message(
                        embed=confirm_embed,
                        view=ConfirmView(self.airline_id, self.airline_data, self.bot),
                        ephemeral=True
                    )

            view = SettingsView(airline_id, airline_data, self)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Ошибка при загрузке настроек: {str(e)}", ephemeral=True
            )

    @app_commands.command(name="маршрут", description="Добавить новый маршрут (автоматически)")
    async def add_route_command(self, interaction: discord.Interaction):
        """Добавление маршрута с автоматическим определением кодов аэропортов"""
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        airline_info = await self._get_user_airline(str(interaction.user.id))

        if not airline_info:
            await interaction.followup.send(
                "❌ У вас нет доступа к управлению авиакомпанией!",
                ephemeral=True
            )
            return

        modal = EnhancedRouteModal(airline_info['id'], airline_info['data'], self.airport_service)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="аэропорт", description="Добавить аэропорт (автоматически)")
    async def add_airport_command(self, interaction: discord.Interaction):
        """Добавление аэропорта с автоматическим определением кодов"""
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        airline_info = await self._get_user_airline(str(interaction.user.id))

        if not airline_info:
            await interaction.followup.send(
                "❌ У вас нет доступа к управлению авиакомпанией!",
                ephemeral=True
            )
            return

        modal = EnhancedAirportModal(airline_info['id'], self.airport_service)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="статистика", description="Статистика авиакомпании")
    async def airline_stats(self, interaction: discord.Interaction):
        """Статистика авиакомпании"""
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            db = self.bot.data.db

            airlines_ref = db.collection('airlines')
            query = airlines_ref.where('owner_id', '==', str(interaction.user.id)).limit(1)
            results = query.get()

            if len(results) == 0:
                await interaction.followup.send(
                    "❌ У вас нет зарегистрированной авиакомпании!",
                    ephemeral=True)
                return

            airline_data = results[0].to_dict()
            airline_id = results[0].id
            stats = airline_data.get('statistics', {})

            flights_ref = db.collection('flights')
            flights_query = flights_ref.where(filter=firestore.FieldFilter('airline_id', '==', airline_id))
            airline_flights = flights_query.get()

            status_counts = {
                'scheduled': 0,
                'boarding': 0,
                'departed': 0,
                'delayed': 0,
                'cancelled': 0,
                'completed': 0
            }

            for flight in airline_flights:
                flight_data = flight.to_dict()
                status = flight_data.get('status', 'scheduled')
                if status in status_counts:
                    status_counts[status] += 1

            subscriptions_ref = db.collection('subscriptions')
            total_subscriptions = 0

            for flight in airline_flights:
                flight_id = flight.id
                subs_query = subscriptions_ref.where(filter=firestore.FieldFilter('flight_id', '==', flight_id))
                subs = subs_query.get()
                total_subscriptions += len(subs)

            embed = discord.Embed(title=f"📊 Статистика {airline_data['name']}", color=discord.Color.blue())

            embed.add_field(name="📈 Общая статистика",
                           value=f"""Всего рейсов: **{len(airline_flights)}**
Выполнено: **{stats.get('flights_completed', 0)}**
Отменено: **{stats.get('flights_cancelled', 0)}**
Задержано: **{stats.get('flights_delayed', 0)}**
Подписок: **{total_subscriptions}**""",
                           inline=False)

            embed.add_field(
                name="🔄 Текущие статусы",
                value=f"""По расписанию: **{status_counts['scheduled']}**
Регистрация: **{status_counts['boarding']}**
Вылетел: **{status_counts['departed']}**
Задержан: **{status_counts['delayed']}**
Отменен: **{status_counts['cancelled']}**
Завершен: **{status_counts['completed']}**""",
                inline=False)

            if 'created_at' in airline_data:
                try:
                    created_date = datetime.fromisoformat(
                        airline_data['created_at'].replace('Z', '+00:00'))
                    days_active = (datetime.now() - created_date).days
                    embed.add_field(name="📅 Дней на платформе",
                                   value=f"**{days_active} дней**",
                                   inline=True)

                    if days_active > 0:
                        avg_flights = len(airline_flights) / days_active
                        embed.add_field(name="📊 Среднее рейсов в день",
                                       value=f"**{avg_flights:.1f}**",
                                       inline=True)
                except:
                    pass

            thirty_days_ago = datetime.now() - timedelta(days=30)
            recent_flights = 0

            for flight in airline_flights:
                flight_data = flight.to_dict()
                created_str = flight_data.get('created_at', '')
                if created_str:
                    try:
                        created_date = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                        if created_date > thirty_days_ago:
                            recent_flights += 1
                    except:
                        pass

            embed.add_field(name="📅 Рейсов за 30 дней",
                           value=f"**{recent_flights}**",
                           inline=True)

            # Добавляем статистику маршрутов
            routes = airline_data.get('routes', [])
            airports = airline_data.get('airports', [])

            embed.add_field(name="🛣️ Маршруты и аэропорты",
                           value=f"Маршрутов: **{len(routes)}**\nАэропортов: **{len(airports)}**",
                           inline=True)

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.response.send_message(
                f"❌ Ошибка при загрузке статистики: {str(e)}", ephemeral=True
            )

class EnhancedAirportModal(Modal, title="🏢 Добавить аэропорт (автоматически)"):
    def __init__(self, airline_id: str, airport_service):
        super().__init__()
        self.airline_id = airline_id
        self.airport_service = airport_service

        self.airport_name = TextInput(
            label="Название аэропорта",
            placeholder="Например: Шереметьево или SVO",
            required=True,
            max_length=100
        )

        self.airport_game_link = TextInput(
            label="Ссылка на игру Roblox",
            placeholder="https://www.roblox.com/games/...",
            required=True
        )

        self.iata_code = TextInput(
            label="Код IATA (определится автоматически)",
            placeholder="Автоматически",
            required=False,
            max_length=3,
            style=discord.TextStyle.short
        )

        self.icao_code = TextInput(
            label="Код ICAO (определится автоматически)",
            placeholder="Автоматически",
            required=False,
            max_length=4,
            style=discord.TextStyle.short
        )

        self.add_item(self.airport_name)
        self.add_item(self.airport_game_link)
        self.add_item(self.iata_code)
        self.add_item(self.icao_code)

        self.found_airport = None

    async def on_submit(self, interaction: discord.Interaction):
        # Отложенный ответ для поиска
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            # 1. Определяем коды аэропорта
            airport_name = self.airport_name.value.strip()

            if len(airport_name) == 3 and airport_name.isalpha():
                # Пользователь ввел IATA код
                self.found_airport = await self.airport_service.search_airport_by_code(airport_name.upper())
            elif len(airport_name) == 4 and airport_name.isalpha():
                # Пользователь ввел ICAO код
                self.found_airport = await self.airport_service.search_airport_by_code(airport_name.upper())
            else:
                # Пользователь ввел название
                self.found_airport = await self.airport_service.search_airport_by_name(airport_name)

            # 2. Проверяем результат
            if not self.found_airport:
                await interaction.followup.send(
                    "❌ Не удалось определить коды аэропорта.\n"
                    "Пожалуйста, уточните название или введите коды вручную:\n"
                    "- Для IATA кода: 3 заглавные буквы (например: SVO)\n"
                    "- Для ICAO кода: 4 заглавные буквы (например: UUEE)",
                    ephemeral=True
                )
                return

            # 3. Сохраняем аэропорт в базу
            db = interaction.client.data.db
            airline_ref = db.collection('airlines').document(self.airline_id)
            airline = airline_ref.get()

            if airline.exists:
                current_data = airline.to_dict()
                airports = current_data.get('airports', [])

                # Проверяем, нет ли уже такого аэропорта
                for airport in airports:
                    if airport.get('code') == self.found_airport['iata']:
                        await interaction.followup.send(
                            f"❌ Аэропорт с кодом {self.found_airport['iata']} уже добавлен!",
                            ephemeral=True
                        )
                        return

                # Добавляем новый аэропорт
                airports.append({
                    'name': self.found_airport.get('name', self.airport_name.value),
                    'game_link': self.airport_game_link.value,
                    'code': self.found_airport['iata'],
                    'icao': self.found_airport.get('icao', ''),
                    'city': self.found_airport.get('city', ''),
                    'country': self.found_airport.get('country', ''),
                    'latitude': self.found_airport.get('latitude', ''),
                    'longitude': self.found_airport.get('longitude', ''),
                    'detected_at': datetime.now().isoformat(),
                    'added_at': datetime.now().isoformat()
                })

                airline_ref.update({'airports': airports})

                # 4. Отправляем результат
                embed = discord.Embed(
                    title="✅ Аэропорт успешно добавлен!",
                    description=f"Коды определены автоматически",
                    color=discord.Color.green()
                )

                embed.add_field(
                    name="🏢 Название",
                    value=self.found_airport.get('name', self.airport_name.value),
                    inline=True
                )

                embed.add_field(
                    name="📍 Город",
                    value=self.found_airport.get('city', 'Неизвестно'),
                    inline=True
                )

                embed.add_field(
                    name="🌍 Страна",
                    value=self.found_airport.get('country', 'Неизвестно'),
                    inline=True
                )

                embed.add_field(
                    name="✈️ IATA код",
                    value=f"`{self.found_airport['iata']}`",
                    inline=True
                )

                embed.add_field(
                    name="🛩️ ICAO код",
                    value=f"`{self.found_airport.get('icao', 'N/A')}`",
                    inline=True
                )

                if self.airport_game_link.value:
                    embed.add_field(
                        name="🎮 Ссылка на игру",
                        value=self.airport_game_link.value,
                        inline=False
                    )

                await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            print(f"Ошибка добавления аэропорта: {e}")
            await interaction.followup.send(
                f"❌ Произошла ошибка: {str(e)}",
                ephemeral=True
            )

class EnhancedRouteModal(Modal, title="🛣️ Добавить маршрут"):
    def __init__(self, airline_id: str, airline_data: dict, airport_service):
        super().__init__()
        self.airline_id = airline_id
        self.airline_data = airline_data
        self.airport_service = airport_service

        self.route_name = TextInput(
            label="Название маршрута",
            placeholder="Например: Москва - Санкт-Петербург",
            required=True,
            max_length=100
        )

        self.route_number = TextInput(
            label="Номер маршрута (только цифры)",
            placeholder="Например: 123, 4567, 89",
            required=True,
            max_length=4
        )

        self.departure_airport = TextInput(
            label="Аэропорт вылета",
            placeholder="Шереметьево или SVO",
            required=True,
            max_length=100
        )

        self.arrival_airport = TextInput(
            label="Аэропорт прилета",
            placeholder="Пулково или LED",
            required=True,
            max_length=100
        )

        self.flight_time = TextInput(
            label="Время полета (минуты)",
            placeholder="Например: 120",
            required=True,
            default="120"
        )

        self.aircraft = TextInput(
            label="Воздушное судно",
            placeholder="Например: Airbus A320, Boeing 737",
            required=True
        )

        self.add_item(self.route_name)
        self.add_item(self.route_number)
        self.add_item(self.departure_airport)
        self.add_item(self.arrival_airport)
        self.add_item(self.flight_time)
        self.add_item(self.aircraft)

        self.departure_info = None
        self.arrival_info = None

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            # 1. Проверяем номер маршрута
            if not self.route_number.value.isdigit():
                await interaction.followup.send(
                    "❌ Номер маршрута должен содержать только цифры!",
                    ephemeral=True
                )
                return

            # 2. Определяем коды аэропортов
            self.departure_info = await self.airport_service.search_airport_by_name(self.departure_airport.value)
            self.arrival_info = await self.airport_service.search_airport_by_name(self.arrival_airport.value)

            if not self.departure_info or not self.arrival_info:
                missing = []
                if not self.departure_info:
                    missing.append("аэропорта вылета")
                if not self.arrival_info:
                    missing.append("аэропорта прилета")

                await interaction.followup.send(
                    f"❌ Не удалось определить коды для {', '.join(missing)}.\n"
                    "Пожалуйста, уточните названия или используйте коды (SVO, LED и т.д.)",
                    ephemeral=True
                )
                return

            # 3. Генерируем номер рейса
            airline_iata = self.airline_data.get('iata', 'SU')
            flight_number = self.airport_service.generate_flight_number(
                airline_iata, 
                self.route_number.value
            )

            # 4. Создаем код маршрута
            route_code = f"{self.departure_info['iata']}-{self.arrival_info['iata']}"

            # 5. Проверяем, что время полета - число
            try:
                flight_time = int(self.flight_time.value)
                if flight_time <= 0:
                    raise ValueError
            except ValueError:
                await interaction.followup.send(
                    "❌ Время полета должно быть положительным числом!",
                    ephemeral=True
                )
                return

            # 6. Сохраняем маршрут в базу
            db = interaction.client.data.db
            airline_ref = db.collection('airlines').document(self.airline_id)
            airline = airline_ref.get()

            if airline.exists:
                current_data = airline.to_dict()
                routes = current_data.get('routes', [])

                # Проверяем уникальность
                for route in routes:
                    if route.get('code') == route_code and route.get('flight_number') == flight_number:
                        await interaction.followup.send(
                            f"❌ Маршрут {route_code} с номером {flight_number} уже существует!",
                            ephemeral=True
                        )
                        return

                # Создаем новый маршрут
                new_route = {
                    'name': self.route_name.value,
                    'code': route_code,
                    'flight_number': flight_number,
                    'departure_airport': self.departure_info['name'],
                    'departure_code': self.departure_info['iata'],
                    'departure_icao': self.departure_info.get('icao', ''),
                    'departure_city': self.departure_info.get('city', ''),
                    'departure_country': self.departure_info.get('country', ''),
                    'arrival_airport': self.arrival_info['name'],
                    'arrival_code': self.arrival_info['iata'],
                    'arrival_icao': self.arrival_info.get('icao', ''),
                    'arrival_city': self.arrival_info.get('city', ''),
                    'arrival_country': self.arrival_info.get('country', ''),
                    'aircraft': self.aircraft.value,
                    'flight_time': flight_time,
                    'created_at': datetime.now().isoformat(),
                    'active': True
                }

                routes.append(new_route)
                airline_ref.update({'routes': routes})

                # 7. Отправляем результат
                embed = discord.Embed(
                    title="✅ Маршрут успешно создан!",
                    description=f"**{self.route_name.value}**",
                    color=discord.Color.green()
                )

                embed.add_field(
                    name="✈️ Номер рейса",
                    value=f"`{flight_number}`",
                    inline=True
                )

                embed.add_field(
                    name="🛣️ Код маршрута",
                    value=f"`{route_code}`",
                    inline=True
                )

                embed.add_field(
                    name="📍 Маршрут",
                    value=f"**{self.departure_info['name']}** ({self.departure_info['iata']}/{self.departure_info.get('icao', 'N/A')}) → "
                         f"**{self.arrival_info['name']}** ({self.arrival_info['iata']}/{self.arrival_info.get('icao', 'N/A')})",
                    inline=False
                )

                embed.add_field(
                    name="🏙️ Города",
                    value=f"{self.departure_info.get('city', 'Неизвестно')} → {self.arrival_info.get('city', 'Неизвестно')}",
                    inline=True
                )

                embed.add_field(
                    name="⏱️ Время полета",
                    value=f"{flight_time} минут",
                    inline=True
                )

                embed.add_field(
                    name="🛩️ ВС",
                    value=self.aircraft.value,
                    inline=True
                )

                embed.set_footer(text=f"Автоматически создано: {datetime.now().strftime('%d.%m.%Y %H:%M')}")

                await interaction.followup.send(embed=embed, ephemeral=True)

        except ValueError as e:
            await interaction.followup.send(
                f"❌ Ошибка в данных: {str(e)}",
                ephemeral=True
            )
        except Exception as e:
            print(f"Ошибка создания маршрута: {e}")
            await interaction.followup.send(
                f"❌ Произошла ошибка при создании маршрута: {str(e)}",
                ephemeral=True
            )

class EmployeeModal(Modal, title="Добавить сотрудника"):
    def __init__(self, airline_id: str):
        super().__init__()
        self.airline_id = airline_id

        self.user_id = TextInput(
            label="Discord ID сотрудника",
            placeholder="Цифровой ID пользователя Discord",
            required=True
        )

        self.role = TextInput(
            label="Роль сотрудника",
            placeholder="Например: Диспетчер",
            required=True
        )

        self.add_item(self.user_id)
        self.add_item(self.role)

    async def on_submit(self, interaction: discord.Interaction):
        db = interaction.client.data.db
        airline_ref = db.collection('airlines').document(self.airline_id)

        airline = airline_ref.get()
        if airline.exists:
            current_data = airline.to_dict()
            employees = current_data.get('employees', [])

            if any(emp.get('user_id') == self.user_id.value for emp in employees):
                await interaction.response.send_message(
                    "❌ Этот пользователь уже добавлен в сотрудники!",
                    ephemeral=True
                )
                return

            employees.append({
                'user_id': self.user_id.value,
                'role': self.role.value,
                'added_by': str(interaction.user.id),
                'added_at': datetime.now().isoformat()
            })

            airline_ref.update({'employees': employees})

            await interaction.response.send_message(
                f"✅ Сотрудник с ID {self.user_id.value} добавлен!",
                ephemeral=True
            )

class EditAirlineModal(Modal, title="✏️ Редактирование авиакомпании"):
    def __init__(self, airline_id: str, bot):
        super().__init__()
        self.airline_id = airline_id
        self.bot = bot

        self.name = TextInput(
            label="Название авиакомпании",
            placeholder="Введите новое название",
            required=False,
            max_length=100
        )

        self.description = TextInput(
            label="Описание",
            placeholder="Новое описание авиакомпании",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=500
        )

        self.discord_server = TextInput(
            label="Ссылка на Discord сервер",
            placeholder="Новая ссылка на Discord сервер",
            required=False
        )

        self.add_item(self.name)
        self.add_item(self.description)
        self.add_item(self.discord_server)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            db = interaction.client.data.db
            airline_ref = db.collection('airlines').document(self.airline_id)

            updates = {}
            if self.name.value:
                updates['name'] = self.name.value
            if self.description.value:
                updates['description'] = self.description.value
            if self.discord_server.value:
                updates['discord_server'] = self.discord_server.value

            if updates:
                updates['updated_at'] = datetime.now().isoformat()
                airline_ref.update(updates)

                audit_channel_id = self.bot.CHANNEL_IDS.get("AUDIT_CHANNEL")
                if audit_channel_id:
                    audit_channel = interaction.guild.get_channel(audit_channel_id)
                    if audit_channel:
                        audit_embed = discord.Embed(
                            title="✏️ Авиакомпания обновлена",
                            color=discord.Color.blue(),
                            timestamp=datetime.now()
                        )

                        airline = airline_ref.get()
                        if airline.exists:
                            airline_data = airline.to_dict()
                            audit_embed.add_field(name="✈️ Авиакомпания", value=airline_data['name'], inline=True)
                            audit_embed.add_field(name="👤 Владелец", value=f"<@{airline_data['owner_id']}>", inline=True)

                        await audit_channel.send(embed=audit_embed)

            await interaction.response.send_message(
                "✅ Настройки успешно обновлены!", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Ошибка при обновлении настроек: {str(e)}", ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(Airlines(bot))