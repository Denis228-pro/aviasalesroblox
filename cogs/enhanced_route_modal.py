# [file name]: enhanced_route_modal.py
import discord
from discord.ui import Modal, TextInput, Select, View, Button
from datetime import datetime
import asyncio

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

        # Для хранения найденных аэропортов
        self.departure_info = None
        self.arrival_info = None

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            # 1. Определяем коды аэропортов
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

            # 2. Генерируем код маршрута
            airline_iata = self.airline_data.get('iata', 'SU')
            flight_number = self.airport_service.generate_flight_number(
                airline_iata, 
                self.route_number.value
            )

            # 3. Создаем код маршрута в формате IATA-IATA
            route_code = f"{self.departure_info['iata']}-{self.arrival_info['iata']}"

            # 4. Сохраняем маршрут в базу
            db = interaction.client.data.db
            airline_ref = db.collection('airlines').document(self.airline_id)
            airline = airline_ref.get()

            if airline.exists:
                current_data = airline.to_dict()
                routes = current_data.get('routes', [])

                # Проверяем уникальность кода маршрута
                for route in routes:
                    if route.get('code') == route_code:
                        await interaction.followup.send(
                            f"❌ Маршрут {route_code} уже существует!",
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
                    'departure_game_link': '',  # Можно добавить позже
                    'arrival_airport': self.arrival_info['name'],
                    'arrival_code': self.arrival_info['iata'],
                    'arrival_icao': self.arrival_info.get('icao', ''),
                    'arrival_city': self.arrival_info.get('city', ''),
                    'arrival_country': self.arrival_info.get('country', ''),
                    'arrival_game_link': '',  # Можно добавить позже
                    'aircraft': self.aircraft.value,
                    'flight_time': int(self.flight_time.value),
                    'created_at': datetime.now().isoformat(),
                    'active': True
                }

                routes.append(new_route)
                airline_ref.update({'routes': routes})

                # 5. Отправляем результат
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
                    value=f"**{self.departure_info['name']}** ({self.departure_info['iata']}) → "
                          f"**{self.arrival_info['name']}** ({self.arrival_info['iata']})",
                    inline=False
                )

                embed.add_field(
                    name="⏱️ Время полета",
                    value=f"{self.flight_time.value} минут",
                    inline=True
                )

                embed.add_field(
                    name="🛩️ ВС",
                    value=self.aircraft.value,
                    inline=True
                )

                embed.set_footer(text="Маршрут готов для создания рейсов")

                await interaction.followup.send(embed=embed, ephemeral=True)

        except ValueError as e:
            await interaction.followup.send(
                f"❌ Ошибка: {str(e)}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ Произошла ошибка при создании маршрута: {str(e)}",
                ephemeral=True
            )