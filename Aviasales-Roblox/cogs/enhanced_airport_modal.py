# [file name]: enhanced_airport_modal.py
import discord
from discord.ui import Modal, TextInput, Select
from typing import Optional
import asyncio

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

        # Поля будут заполнены автоматически
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

        # Переменные для хранения найденных данных
        self.found_airport = None

    async def on_submit(self, interaction: discord.Interaction):
        # Определяем коды аэропорта
        await self._detect_airport_codes(interaction)

        # Проверяем, что коды найдены
        if not self.found_airport:
            await interaction.response.send_message(
                "❌ Не удалось определить коды аэропорта. Проверьте название или введите коды вручную.",
                ephemeral=True
            )
            return

        # Сохраняем аэропорт в базу
        db = interaction.client.data.db
        airline_ref = db.collection('airlines').document(self.airline_id)
        airline = airline_ref.get()

        if airline.exists:
            current_data = airline.to_dict()
            airports = current_data.get('airports', [])

            # Проверяем, нет ли уже такого аэропорта
            for airport in airports:
                if airport.get('code') == self.found_airport['iata']:
                    await interaction.response.send_message(
                        f"❌ Аэропорт с кодом {self.found_airport['iata']} уже добавлен!",
                        ephemeral=True
                    )
                    return

            airports.append({
                'name': self.found_airport.get('name', self.airport_name.value),
                'game_link': self.airport_game_link.value,
                'code': self.found_airport['iata'],
                'icao': self.found_airport.get('icao', ''),
                'city': self.found_airport.get('city', ''),
                'country': self.found_airport.get('country', ''),
                'detected_at': datetime.now().isoformat(),
                'added_at': datetime.now().isoformat()
            })

            airline_ref.update({'airports': airports})

            await interaction.response.send_message(
                f"✅ Аэропорт **{self.found_airport['name']}** добавлен!\n"
                f"• IATA: `{self.found_airport['iata']}`\n"
                f"• ICAO: `{self.found_airport.get('icao', 'N/A')}`\n"
                f"• Город: {self.found_airport.get('city', 'Неизвестно')}",
                ephemeral=True
            )

    async def _detect_airport_codes(self, interaction: discord.Interaction):
        """Определение кодов аэропорта"""
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            # Сначала пробуем найти по названию
            self.found_airport = await self.airport_service.search_airport_by_name(self.airport_name.value)

            # Если не нашли, пробуем по коду (если пользователь ввел код)
            if not self.found_airport:
                # Проверяем, не ввел ли пользователь код вместо названия
                code = self.airport_name.value.upper().strip()
                if len(code) == 3 or len(code) == 4:
                    self.found_airport = await self.airport_service.search_airport_by_code(code)

            if self.found_airport:
                # Обновляем поля формы
                self.iata_code.default = self.found_airport.get('iata', '')
                self.icao_code.default = self.found_airport.get('icao', '')
            else:
                await interaction.followup.send(
                    "⚠️ Не удалось автоматически определить коды аэропорта. "
                    "Вы можете ввести их вручную ниже.",
                    ephemeral=True
                )

        except Exception as e:
            print(f"Ошибка определения кодов: {e}")
            await interaction.followup.send(
                f"⚠️ Произошла ошибка при определении кодов: {str(e)}",
                ephemeral=True
            )