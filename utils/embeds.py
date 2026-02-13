import discord
from datetime import datetime


class Embeds:

    @staticmethod
    def flight_embed(flight_data: dict, airline_data: dict) -> discord.Embed:
        """Создать Embed для рейса"""
        embed = discord.Embed(
            title=f"✈️ Рейс {flight_data.get('flight_number', '')}",
            color=discord.Color.blue(),
            timestamp=datetime.now())

        # Добавляем поля
        embed.add_field(name="🏢 Авиакомпания",
                        value=airline_data.get('name', 'Не указано'),
                        inline=True)
        embed.add_field(name="🏷️ IATA",
                        value=airline_data.get('iata', 'Не указано'),
                        inline=True)
        embed.add_field(name="🛫 Вылет",
                        value=flight_data.get('departure_airport',
                                              'Не указан'),
                        inline=True)
        embed.add_field(name="🛬 Прилет",
                        value=flight_data.get('arrival_airport', 'Не указан'),
                        inline=True)
        embed.add_field(name="📅 Дата",
                        value=flight_data.get('departure_date', 'Не указано'),
                        inline=True)
        embed.add_field(name="⏰ Время",
                        value=flight_data.get('departure_time', 'Не указано'),
                        inline=True)
        embed.add_field(name="✈️ Борт",
                        value=flight_data.get('aircraft', 'Не указано'),
                        inline=True)
        embed.add_field(
            name="🎮 Сервер",
            value=
            f"Открывается в {flight_data.get('server_open_time', 'Не указано')}",
            inline=True)

        # Статус
        status = flight_data.get('status', 'scheduled')
        status_emoji = {
            'scheduled': '🟢',
            'boarding': '🟡',
            'departed': '✈️',
            'delayed': '🟠',
            'cancelled': '🔴',
            'completed': '✅'
        }.get(status, '❓')

        embed.add_field(name="📊 Статус",
                        value=f"{status_emoji} {status}",
                        inline=True)

        # Thumbnail (логотип авиакомпании)
        if 'logo_url' in airline_data:
            embed.set_thumbnail(url=airline_data['logo_url'])

        return embed

    @staticmethod
    def airline_embed(airline_data: dict) -> discord.Embed:
        """Создать Embed для авиакомпании"""
        embed = discord.Embed(
            title=f"🏢 {airline_data.get('name', 'Авиакомпания')}",
            description=airline_data.get('description', ''),
            color=discord.Color.dark_blue())

        stats = airline_data.get('statistics', {})

        embed.add_field(name="🏷️ IATA",
                        value=airline_data.get('iata', 'Не указано'),
                        inline=True)
        embed.add_field(name="🔗 Discord",
                        value=airline_data.get('discord_server', 'Не указан'),
                        inline=True)
        embed.add_field(name="\u200b", value="\u200b",
                        inline=True)  # Пустое поле для выравнивания

        embed.add_field(name="📊 Статистика",
                        value=f"""
            Рейсов создано: **{stats.get('flights_created', 0)}**
            Выполнено: **{stats.get('flights_completed', 0)}**
            Задержано: **{stats.get('flights_delayed', 0)}**
            Отменено: **{stats.get('flights_cancelled', 0)}**
            """,
                        inline=False)

        # Дата регистрации
        if 'created_at' in airline_data:
            try:
                created_date = datetime.fromisoformat(
                    airline_data['created_at'].replace('Z', '+00:00'))
                days_active = (datetime.now() - created_date).days
                embed.add_field(name="📅 На платформе",
                                value=f"{days_active} дней",
                                inline=True)
            except:
                pass

        return embed
