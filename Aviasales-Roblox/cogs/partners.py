import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import Button, View, Modal, TextInput
from datetime import datetime


class PartnerApplicationModal(Modal, title="🤝 Заявка на партнерство"):

    def __init__(self):
        super().__init__()

        self.server_name = TextInput(
            label="Название сервера",
            placeholder="Официальное название сервера Discord",
            required=True,
            max_length=100)

        self.server_link = TextInput(label="Ссылка на сервер",
                                     placeholder="https://discord.gg/...",
                                     required=True)

        self.channel_id = TextInput(
            label="ID канала для рейсов",
            placeholder="ID канала, где будут публиковаться рейсы",
            required=True)

        self.contact = TextInput(label="Контактное лицо",
                                 placeholder="Discord username или ID",
                                 required=True)

        self.add_item(self.server_name)
        self.add_item(self.server_link)
        self.add_item(self.channel_id)
        self.add_item(self.contact)

    async def on_submit(self, interaction: discord.Interaction):
        db = interaction.client.data.db

        # Создаем заявку
        application_data = {
            'applicant_id': str(interaction.user.id),
            'applicant_name': str(interaction.user),
            'server_name': self.server_name.value,
            'server_link': self.server_link.value,
            'channel_id': self.channel_id.value,
            'contact': self.contact.value,
            'status': 'pending',
            'created_at': datetime.now().isoformat()
        }

        partners_ref = db.collection('partner_applications')
        application_doc = partners_ref.add(application_data)

        # Отправляем в канал модерации
        guild = interaction.guild
        mod_channel = discord.utils.get(guild.channels,
                                        name="модерация-партнеров")

        if mod_channel:
            embed = discord.Embed(title="🤝 Новая заявка на партнерство",
                                  color=discord.Color.blue(),
                                  timestamp=datetime.now())

            embed.add_field(
                name="👤 Заявитель",
                value=f"{interaction.user.mention}\n{interaction.user.id}",
                inline=True)
            embed.add_field(name="🏢 Сервер",
                            value=self.server_name.value,
                            inline=True)
            embed.add_field(name="🔗 Ссылка",
                            value=self.server_link.value,
                            inline=True)
            embed.add_field(name="📺 Канал",
                            value=f"ID: {self.channel_id.value}",
                            inline=True)
            embed.add_field(name="📞 Контакт",
                            value=self.contact.value,
                            inline=True)

            class PartnerModerationView(View):

                def __init__(self, app_id: str):
                    super().__init__(timeout=None)
                    self.app_id = app_id

                @discord.ui.button(label="✅ Одобрить",
                                   style=discord.ButtonStyle.success)
                async def approve_button(self,
                                         interaction: discord.Interaction,
                                         button: Button):
                    # Обновляем статус заявки
                    app_ref = partners_ref.document(self.app_id)
                    app_ref.update({
                        'status': 'approved',
                        'moderator_id': str(interaction.user.id),
                        'moderator_name': str(interaction.user)
                    })

                    # Создаем партнера
                    app_data = app_ref.get().to_dict()

                    partner_data = {
                        'server_name': app_data['server_name'],
                        'server_link': app_data['server_link'],
                        'channel_id': app_data['channel_id'],
                        'contact': app_data['contact'],
                        'applicant_id': app_data['applicant_id'],
                        'status': 'active',
                        'joined_at': datetime.now().isoformat(),
                        'published_flights': 0
                    }

                    db.collection('partners').add(partner_data)

                    # Выдаем роль партнера
                    guild = interaction.guild
                    user = guild.get_member(int(app_data['applicant_id']))
                    if user:
                        role = discord.utils.get(guild.roles, name="Партнер")
                        if role:
                            await user.add_roles(role)

                    # Отправляем сообщение заявителю
                    try:
                        user = await interaction.client.fetch_user(
                            int(app_data['applicant_id']))
                        await user.send(
                            f"✅ Ваша заявка на партнерство для сервера **{app_data['server_name']}** одобрена!"
                        )
                    except:
                        pass

                    embed.color = discord.Color.green()
                    embed.add_field(name="✅ Статус",
                                    value="Одобрено",
                                    inline=False)
                    await interaction.response.edit_message(embed=embed,
                                                            view=None)

                @discord.ui.button(label="❌ Отклонить",
                                   style=discord.ButtonStyle.danger)
                async def reject_button(self, interaction: discord.Interaction,
                                        button: Button):
                    app_ref = partners_ref.document(self.app_id)
                    app_ref.update({
                        'status': 'rejected',
                        'moderator_id': str(interaction.user.id),
                        'moderator_name': str(interaction.user)
                    })

                    app_data = app_ref.get().to_dict()

                    # Уведомляем заявителя
                    try:
                        user = await interaction.client.fetch_user(
                            int(app_data['applicant_id']))
                        await user.send(
                            f"❌ Ваша заявка на партнерство для сервера **{app_data['server_name']}** отклонена."
                        )
                    except:
                        pass

                    embed.color = discord.Color.red()
                    embed.add_field(name="❌ Статус",
                                    value="Отклонено",
                                    inline=False)
                    await interaction.response.edit_message(embed=embed,
                                                            view=None)

            view = PartnerModerationView(application_doc[1].id)
            await mod_channel.send(embed=embed, view=view)

        await interaction.response.send_message(
            "✅ Ваша заявка на партнерство отправлена на модерацию!",
            ephemeral=True)


class Partners(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="партнерство",
                          description="Подать заявку на партнерство")
    async def become_partner(self, interaction: discord.Interaction):
        """Подача заявки на партнерство"""
        # Modals MUST be sent as the first response to an interaction.
        # We cannot use defer() here if we want to send a modal directly.
        modal = PartnerApplicationModal()
        await interaction.response.send_modal(modal)


async def setup(bot):
    await bot.add_cog(Partners(bot))
