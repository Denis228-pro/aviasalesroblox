import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import Button, View, Modal, TextInput, Select
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import firebase_admin
from firebase_admin import firestore

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="админ", description="Админ-панель")
    async def admin_panel(self, interaction: discord.Interaction):
        """Панель администратора"""
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        try:
            db = self.bot.data.db
            
            embed = discord.Embed(
                title="⚙️ Админ-панель Aviasales Roblox",
                color=discord.Color.red()
            )

            # Получаем статистику
            airlines_count = len(list(db.collection('airlines').stream()))
            flights_count = len(list(db.collection('flights').stream()))
            partners_count = len(list(db.collection('partners').stream()))
            pending_apps = len(list(db.collection('airline_applications').where('status', '==', 'pending').stream()))

            embed.add_field(name="🛫 Авиакомпаний", value=f"**{airlines_count}**", inline=True)
            embed.add_field(name="✈️ Рейсов", value=f"**{flights_count}**", inline=True)
            embed.add_field(name="🤝 Партнеров", value=f"**{partners_count}**", inline=True)
            embed.add_field(name="⏳ Ожидают модерации", value=f"**{pending_apps}**", inline=True)

            # Кнопки управления
            class AdminView(View):
                def __init__(self):
                    super().__init__(timeout=180)

                @discord.ui.button(label="👮 Модерация", style=discord.ButtonStyle.primary, emoji="📋")
                async def moderation_button(self, interaction: discord.Interaction, button: Button):
                    try:
                        # Показываем очередь модерации
                        apps_ref = db.collection('airline_applications')
                        pending_apps = apps_ref.where('status', '==', 'pending').get()

                        if not pending_apps:
                            await interaction.response.send_message(
                                "✅ Нет заявок, ожидающих модерации!",
                                ephemeral=True
                            )
                            return

                        apps_text = ""
                        for i, app in enumerate(pending_apps[:5], 1):
                            app_data = app.to_dict()
                            apps_text += f"{i}. **{app_data['airline_name']}** (IATA: {app_data['iata']}) - <@{app_data['user_id']}>\n"

                        mod_embed = discord.Embed(
                            title="📋 Очередь модерации",
                            description=apps_text,
                            color=discord.Color.orange()
                        )

                        await interaction.response.send_message(embed=mod_embed, ephemeral=True)
                    except Exception as e:
                        try:
                            await interaction.response.send_message(
                                f"❌ Ошибка при получении данных: {str(e)}",
                                ephemeral=True
                            )
                        except:
                            await interaction.followup.send(
                                f"❌ Ошибка при получении данных: {str(e)}",
                                ephemeral=True
                            )

                @discord.ui.button(label="🚫 Блокировки", style=discord.ButtonStyle.danger, emoji="🔨")
                async def bans_button(self, interaction: discord.Interaction, button: Button):
                    try:
                        modal = BanModal()
                        await interaction.response.send_modal(modal)
                    except Exception as e:
                        try:
                            await interaction.response.send_message(
                                f"❌ Ошибка при создании формы: {str(e)}",
                                ephemeral=True
                            )
                        except:
                            await interaction.followup.send(
                                f"❌ Ошибка при создании формы: {str(e)}",
                                ephemeral=True
                            )

                @discord.ui.button(label="📊 Статистика", style=discord.ButtonStyle.secondary, emoji="📈")
                async def stats_button(self, interaction: discord.Interaction, button: Button):
                    try:
                        # Детальная статистика
                        stats_embed = discord.Embed(
                            title="📊 Детальная статистика",
                            color=discord.Color.blue()
                        )

                        # Собираем статистику
                        today = datetime.now().date()

                        # Рейсы за сегодня
                        flights_today = 0
                        flights = db.collection('flights').stream()
                        for flight in flights:
                            flight_data = flight.to_dict()
                            flight_date_str = flight_data.get('created_at', '')
                            if flight_date_str:
                                try:
                                    flight_date = datetime.fromisoformat(flight_date_str).date()
                                    if flight_date == today:
                                        flights_today += 1
                                except:
                                    pass

                        # Новые авиакомпании за сегодня
                        new_airlines = 0
                        airlines = db.collection('airlines').stream()
                        for airline in airlines:
                            airline_data = airline.to_dict()
                            created_str = airline_data.get('created_at', '')
                            if created_str:
                                try:
                                    created_date = datetime.fromisoformat(created_str).date()
                                    if created_date == today:
                                        new_airlines += 1
                                except:
                                    pass

                        stats_embed.add_field(name="📅 Сегодня", value=f"Новых рейсов: **{flights_today}**\nНовых авиакомпаний: **{new_airlines}**", inline=False)

                        await interaction.response.send_message(embed=stats_embed, ephemeral=True)
                    except Exception as e:
                        try:
                            await interaction.response.send_message(
                                f"❌ Ошибка при получении статистики: {str(e)}",
                                ephemeral=True
                            )
                        except:
                            await interaction.followup.send(
                                f"❌ Ошибка при получении статистики: {str(e)}",
                                ephemeral=True
                            )

                @discord.ui.button(label="🔄 Обновить", style=discord.ButtonStyle.success, emoji="🔄")
                async def refresh_button(self, interaction: discord.Interaction, button: Button):
                    try:
                        await interaction.response.defer()
                        await interaction.delete_original_response()

                        # Перезапускаем команду
                        await self.admin_panel.callback(self, interaction)
                    except Exception as e:
                        try:
                            await interaction.response.send_message(
                                f"❌ Ошибка при обновлении: {str(e)}",
                                ephemeral=True
                            )
                        except:
                            await interaction.followup.send(
                                f"❌ Ошибка при обновлении: {str(e)}",
                                ephemeral=True
                            )

            view = AdminView()
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            try:
                await interaction.followup.send(
                    f"❌ Произошла ошибка при загрузке админ-панели: {str(e)}",
                    ephemeral=True
                )
            except:
                # Если все провалилось, попробуем отправить обычное сообщение
                channel = interaction.channel
                if channel:
                    await channel.send(
                        f"❌ Произошла ошибка при загрузке админ-панели: {str(e)}",
                        delete_after=10
                    )

class BanModal(Modal, title="🚫 Блокировка пользователя"):
    def __init__(self):
        super().__init__()

        self.user_id = TextInput(
            label="ID пользователя",
            placeholder="Discord ID пользователя",
            required=True
        )

        self.reason = TextInput(
            label="Причина",
            placeholder="Причина блокировки",
            required=True,
            style=discord.TextStyle.paragraph
        )

        self.duration = TextInput(
            label="Длительность (дни)",
            placeholder="0 для перманентной блокировки",
            required=True,
            default="0"
        )

        self.add_item(self.user_id)
        self.add_item(self.reason)
        self.add_item(self.duration)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            db = interaction.client.data.db

            try:
                duration_days = int(self.duration.value)
                if duration_days < 0:
                    await interaction.response.send_message(
                        "❌ Длительность не может быть отрицательной!",
                        ephemeral=True
                    )
                    return
            except:
                await interaction.response.send_message(
                    "❌ Неверный формат длительности! Используйте число дней.",
                    ephemeral=True
                )
                return

            # Сохраняем блокировку
            ban_data = {
                'user_id': self.user_id.value,
                'moderator_id': str(interaction.user.id),
                'moderator_name': str(interaction.user),
                'reason': self.reason.value,
                'duration_days': duration_days,
                'banned_at': datetime.now().isoformat(),
                'status': 'active'
            }

            if duration_days > 0:
                unban_date = datetime.now() + timedelta(days=duration_days)
                ban_data['unban_at'] = unban_date.isoformat()

            bans_ref = db.collection('bans')
            bans_ref.add(ban_data)

            # Логируем в аудит
            audit_channel_id = interaction.client.CHANNEL_IDS.get("AUDIT_CHANNEL")
            if audit_channel_id:
                audit_channel = interaction.guild.get_channel(audit_channel_id)
                if audit_channel:
                    embed = discord.Embed(
                        title="🚫 Пользователь заблокирован",
                        color=discord.Color.red(),
                        timestamp=datetime.now()
                    )

                    embed.add_field(name="👤 Пользователь", value=f"<@{self.user_id.value}> ({self.user_id.value})", inline=True)
                    embed.add_field(name="👮 Модератор", value=interaction.user.mention, inline=True)
                    embed.add_field(name="📝 Причина", value=self.reason.value, inline=False)

                    if duration_days > 0:
                        embed.add_field(name="⏰ Длительность", value=f"{duration_days} дней", inline=True)
                    else:
                        embed.add_field(name="⏰ Длительность", value="Перманентно", inline=True)

                    await audit_channel.send(embed=embed)

            await interaction.response.send_message(
                f"✅ Пользователь <@{self.user_id.value}> заблокирован!",
                ephemeral=True
            )

        except Exception as e:
            try:
                await interaction.response.send_message(
                    f"❌ Ошибка при блокировке пользователя: {str(e)}",
                    ephemeral=True
                )
            except:
                await interaction.followup.send(
                    f"❌ Ошибка при блокировке пользователя: {str(e)}",
                    ephemeral=True
                )

async def setup(bot):
    await bot.add_cog(Admin(bot))