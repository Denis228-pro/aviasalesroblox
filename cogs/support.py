import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import Button, View, Modal, TextInput
from datetime import datetime


class SupportTicketModal(Modal, title="🆘 Обращение в поддержку"):

    def __init__(self):
        super().__init__()

        self.issue_type = TextInput(
            label="Тип проблемы",
            placeholder="Например: Техническая, Вопрос по рейсу, Другое",
            required=True,
            max_length=50)

        self.description = TextInput(
            label="Подробное описание",
            placeholder="Опишите вашу проблему как можно подробнее...",
            required=True,
            style=discord.TextStyle.paragraph,
            max_length=1000)

        self.add_item(self.issue_type)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction):
        db = interaction.client.data.db

        # Создаем тикет
        ticket_data = {
            'user_id': str(interaction.user.id),
            'username': str(interaction.user),
            'issue_type': self.issue_type.value,
            'description': self.description.value,
            'status': 'open',
            'created_at': datetime.now().isoformat(),
            'assigned_to': None,
            'messages': []
        }

        tickets_ref = db.collection('support_tickets')
        ticket_doc = tickets_ref.add(ticket_data)

        # Отправляем в канал поддержки
        guild = interaction.guild
        support_channel = discord.utils.get(guild.channels,
                                            name="тикеты-поддержки")

        if support_channel:
            embed = discord.Embed(
                title=f"🆘 Новый тикет #{ticket_doc[1].id[:8]}",
                color=discord.Color.orange(),
                timestamp=datetime.now())

            embed.add_field(
                name="👤 Пользователь",
                value=f"{interaction.user.mention}\n{interaction.user.id}",
                inline=True)
            embed.add_field(name="📋 Тип",
                            value=self.issue_type.value,
                            inline=True)
            embed.add_field(
                name="📝 Описание",
                value=self.description.value[:500] + "..." if len(
                    self.description.value) > 500 else self.description.value,
                inline=False)

            class TicketView(View):

                def __init__(self, ticket_id: str):
                    super().__init__(timeout=None)
                    self.ticket_id = ticket_id

                @discord.ui.button(label="📥 Взять тикет",
                                   style=discord.ButtonStyle.primary)
                async def take_ticket(self, interaction: discord.Interaction,
                                      button: Button):
                    # Проверяем, не взят ли уже тикет
                    ticket_ref = tickets_ref.document(self.ticket_id)
                    ticket_data = ticket_ref.get().to_dict()

                    if ticket_data['assigned_to']:
                        await interaction.response.send_message(
                            "❌ Этот тикет уже взят другим модератором!",
                            ephemeral=True)
                        return

                    # Назначаем модератора
                    ticket_ref.update({
                        'assigned_to': str(interaction.user.id),
                        'assigned_name': str(interaction.user),
                        'status': 'in_progress'
                    })

                    # Отправляем сообщение пользователю
                    try:
                        user = await interaction.client.fetch_user(
                            int(ticket_data['user_id']))

                        user_embed = discord.Embed(
                            title="👮 Ваш тикет взят в работу",
                            description=
                            f"Модератор {interaction.user.mention} взял ваш тикет в работу. Ожидайте ответа.",
                            color=discord.Color.green())

                        await user.send(embed=user_embed)
                    except:
                        pass

                    # Обновляем Embed
                    embed.color = discord.Color.green()
                    embed.add_field(name="👮 Модератор",
                                    value=interaction.user.mention,
                                    inline=False)

                    await interaction.response.edit_message(embed=embed,
                                                            view=None)

            view = TicketView(ticket_doc[1].id)
            await support_channel.send(embed=embed, view=view)

        await interaction.response.send_message(
            "✅ Ваше обращение отправлено в поддержку! Ожидайте ответа.",
            ephemeral=True)


class Support(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="поддержка",
                          description="Обратиться в поддержку")
    async def create_ticket(self, interaction: discord.Interaction):
        """Создание тикета в поддержку"""
        # Modals MUST be sent as the first response to an interaction.
        # We cannot use defer() here if we want to send a modal directly.
        # To avoid timeouts, we just send the modal immediately.
        modal = SupportTicketModal()
        await interaction.response.send_modal(modal)


async def setup(bot):
    await bot.add_cog(Support(bot))
