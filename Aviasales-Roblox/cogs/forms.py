import discord
from discord.ui import Modal, TextInput
from datetime import datetime
import firebase_admin
from firebase_admin import firestore

class AirlineRegistrationModal(Modal, title="📝 Регистрация авиакомпании"):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

        self.name = TextInput(
            label="Название авиакомпании",
            placeholder="Введите полное название",
            required=True,
            max_length=100
        )

        self.iata = TextInput(
            label="Код IATA",
            placeholder="Например: SU, AFL, S7 (2-3 символа)",
            required=True,
            min_length=2,
            max_length=3
        )

        self.discord_server = TextInput(
            label="Ссылка на Discord-сервер",
            placeholder="https://discord.gg/...",
            required=True
        )

        self.description = TextInput(
            label="Описание авиакомпании",
            placeholder="Краткое описание вашей компании",
            required=False,
            style=discord.TextStyle.paragraph,
            max_length=500
        )

        self.logo_url = TextInput(
            label="Ссылка на логотип (URL)",
            placeholder="https://i.imgur.com/...",
            required=False,
            max_length=200
        )

        self.add_item(self.name)
        self.add_item(self.iata)
        self.add_item(self.discord_server)
        self.add_item(self.logo_url)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            db = self.bot.data.db

            # Проверяем уникальность IATA
            airlines_ref = db.collection('airlines')
            query = airlines_ref.where(filter=firestore.FieldFilter('iata', '==', self.iata.value.upper())).limit(1)
            existing = query.get()

            if len(existing) > 0:
                await interaction.response.send_message(
                    f"❌ Код IATA `{self.iata.value.upper()}` уже используется другой авиакомпанией!",
                    ephemeral=True
                )
                return

            # Проверяем, нет ли у пользователя уже авиакомпании
            user_query = airlines_ref.where(filter=firestore.FieldFilter('owner_id', '==', str(interaction.user.id))).limit(1)
            user_airlines = user_query.get()

            if len(user_airlines) > 0:
                await interaction.response.send_message(
                    "❌ У вас уже есть зарегистрированная авиакомпания!",
                    ephemeral=True
                )
                return

            # Создаем заявку
            application_data = {
                'user_id': str(interaction.user.id),
                'username': str(interaction.user),
                'airline_name': self.name.value,
                'iata': self.iata.value.upper(),
                'discord_server': self.discord_server.value,
                'logo_url': self.logo_url.value if self.logo_url.value else "",
                'description': self.description.value if self.description.value else "",
                'status': 'pending',
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }

            # Сохраняем в Firebase
            apps_ref = db.collection('airline_applications')
            new_doc = apps_ref.add(application_data)
            app_id = new_doc[1].id

            # Создаем Embed для модерации
            embed = discord.Embed(
                title="🆕 Новая заявка на регистрацию",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )

            embed.add_field(name="👤 Пользователь", value=f"{interaction.user.mention}\nID: {interaction.user.id}", inline=True)
            embed.add_field(name="✈️ Название", value=self.name.value, inline=True)
            embed.add_field(name="🏷️ IATA", value=self.iata.value.upper(), inline=True)
            if self.logo_url.value:
                embed.set_thumbnail(url=self.logo_url.value)
            embed.add_field(name="🔗 Discord", value=self.discord_server.value, inline=False)
            embed.add_field(name="📝 Описание", value=self.description.value[:100] + "..." if self.description.value and len(self.description.value) > 100 else self.description.value or "Не указано", inline=False)
            embed.add_field(name="📋 ID заявки", value=f"`{app_id}`", inline=False)

            # Создаем View с кнопками для модерации
            class ModerationView(discord.ui.View):
                def __init__(self, application_id: str, applicant_id: int, bot, original_message_id: int = None):
                    super().__init__(timeout=None)
                    self.application_id = application_id
                    self.applicant_id = applicant_id
                    self.bot = bot
                    self.original_message_id = original_message_id

                @discord.ui.button(label="✅ Принять", style=discord.ButtonStyle.success, emoji="✅")
                async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                    # Обновляем статус заявки
                    app_doc = apps_ref.document(self.application_id)
                    app_doc.update({
                        'status': 'accepted',
                        'moderator_id': str(interaction.user.id),
                        'moderator_name': str(interaction.user),
                        'processed_at': datetime.now().isoformat()
                    })

                    # Получаем данные заявки
                    app_data = app_doc.get().to_dict()

                    # Создаем запись авиакомпании
                    airline_data = {
                        'owner_id': str(self.applicant_id),
                        'name': app_data['airline_name'],
                        'iata': app_data['iata'],
                        'discord_server': app_data['discord_server'],
                        'logo_url': app_data.get('logo_url', ''),
                        'description': app_data['description'],
                        'status': 'active',
                        'created_at': datetime.now().isoformat(),
                        'aircraft': [],
                        'airports': [],
                        'employees': [],
                        'statistics': {
                            'flights_created': 0,
                            'flights_completed': 0,
                            'flights_delayed': 0,
                            'flights_cancelled': 0,
                            'days_active': 0
                        }
                    }

                    airlines_ref.add(airline_data)

                    # Отправляем уведомление пользователю
                    try:
                        user = await self.bot.fetch_user(self.applicant_id)

                        agreement_embed = discord.Embed(
                            title="✅ Ваша авиакомпания одобрена!",
                            description="Пожалуйста, ознакомьтесь с договором-офертой",
                            color=discord.Color.green()
                        )

                        agreement_embed.add_field(
                            name="📄 Условия соглашения",
                            value="""
                            1. Вы обязуетесь соблюдать правила платформы
                            2. Рейсы должны соответствовать реальному расписанию
                            3. Запрещена публикация ложной информации
                            4. Платформа оставляет за собой право на модерацию
                            5. Вы несете ответственность за публикуемый контент
                            6. Администрация может приостановить работу авиакомпании при нарушении правил
                            """,
                            inline=False
                        )

                        class AgreementView(discord.ui.View):
                            def __init__(self, user_id: int, airline_name: str, bot, guild_id: int):
                                super().__init__(timeout=None)
                                self.user_id = user_id
                                self.airline_name = airline_name
                                self.bot = bot
                                self.guild_id = guild_id

                            @discord.ui.button(label="✅ Согласен", style=discord.ButtonStyle.success, emoji="✍️")
                            async def agree_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                                # Получаем сервер
                                guild = self.bot.get_guild(self.guild_id)
                                if guild:
                                    member = guild.get_member(self.user_id)
                                    if member:
                                        role = discord.utils.get(guild.roles, name="Авиационное предприятие")
                                        if not role:
                                            # Создаем роль если ее нет
                                            role = await guild.create_role(
                                                name="Авиационное предприятие",
                                                color=discord.Color.blue(),
                                                reason="Роль для зарегистрированных авиакомпаний"
                                            )
                                        await member.add_roles(role)

                                await interaction.response.send_message(
                                    "🎉 Вы успешно зарегистрировали авиакомпанию! Используйте `/настройка` для управления.",
                                    ephemeral=True
                                )

                                # Логируем в аудит
                                audit_channel_id = self.bot.CHANNEL_IDS.get("AUDIT_CHANNEL")
                                if audit_channel_id and guild:
                                    audit_channel = guild.get_channel(audit_channel_id)
                                    if audit_channel:
                                        audit_embed = discord.Embed(
                                            title="✅ Регистрация авиакомпании завершена",
                                            color=discord.Color.green(),
                                            timestamp=datetime.now()
                                        )
                                        audit_embed.add_field(name="👤 Пользователь", value=f"<@{self.user_id}>", inline=True)
                                        audit_embed.add_field(name="✈️ Авиакомпания", value=self.airline_name, inline=True)
                                        await audit_channel.send(embed=audit_embed)

                            @discord.ui.button(label="❌ Не согласен", style=discord.ButtonStyle.danger, emoji="❌")
                            async def disagree_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                                # Отклоняем заявку
                                app_doc.update({'status': 'rejected_agreement'})
                                await interaction.response.send_message(
                                    "❌ Регистрация отменена. Условия оферты не были приняты.",
                                    ephemeral=True
                                )

                        agreement_view = AgreementView(self.applicant_id, app_data['airline_name'], self.bot, interaction.guild.id)
                        await user.send(embed=agreement_embed, view=agreement_view)

                    except Exception as e:
                        print(f"Ошибка отправки сообщения пользователю: {e}")

                    # Обновляем Embed
                    embed.color = discord.Color.green()
                    embed.add_field(name="✅ Статус", value="Принято", inline=False)
                    embed.add_field(name="👮 Модератор", value=interaction.user.mention, inline=False)
                    embed.set_footer(text=f"Обработано: {datetime.now().strftime('%d.%m.%Y %H:%M')}")

                    try:
                        await interaction.response.edit_message(embed=embed, view=None)
                    except discord.errors.NotFound:
                        await interaction.followup.send("✅ Заявка одобрена!", ephemeral=True)

                @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.danger, emoji="❌")
                async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                    # Запрашиваем причину отклонения
                    class RejectReasonModal(Modal, title="Укажите причину отклонения"):
                        def __init__(self, application_id: str, applicant_id: int):
                            super().__init__()
                            self.application_id = application_id
                            self.applicant_id = applicant_id

                            self.reason = TextInput(
                                label="Причина отклонения",
                                placeholder="Укажите причину отклонения заявки...",
                                required=True,
                                style=discord.TextStyle.paragraph,
                                max_length=500
                            )
                            self.add_item(self.reason)

                        async def on_submit(self, interaction: discord.Interaction):
                            # Обновляем статус заявки
                            app_doc = apps_ref.document(self.application_id)
                            app_doc.update({
                                'status': 'rejected',
                                'moderator_id': str(interaction.user.id),
                                'moderator_name': str(interaction.user),
                                'rejection_reason': self.reason.value,
                                'processed_at': datetime.now().isoformat()
                            })

                            # Уведомляем пользователя
                            try:
                                user = await interaction.client.fetch_user(self.applicant_id)
                                reject_embed = discord.Embed(
                                    title="❌ Ваша заявка отклонена",
                                    description=f"Заявка на регистрацию авиакомпании была отклонена модератором.",
                                    color=discord.Color.red()
                                )
                                reject_embed.add_field(name="Причина", value=self.reason.value, inline=False)
                                await user.send(embed=reject_embed)
                            except:
                                pass

                            # Обновляем Embed
                            embed.color = discord.Color.red()
                            embed.add_field(name="❌ Статус", value="Отклонено", inline=False)
                            embed.add_field(name="👮 Модератор", value=interaction.user.mention, inline=False)
                            embed.add_field(name="📝 Причина", value=self.reason.value[:200], inline=False)
                            embed.set_footer(text=f"Обработано: {datetime.now().strftime('%d.%m.%Y %H:%M')}")

                            try:
                                await interaction.response.edit_message(embed=embed, view=None)
                            except discord.errors.NotFound:
                                await interaction.followup.send("❌ Заявка отклонена!", ephemeral=True)

                    modal = RejectReasonModal(self.application_id, self.applicant_id)
                    await interaction.response.send_modal(modal)

            view = ModerationView(app_id, interaction.user.id, self.bot)

            # Отправляем в канал модерации
            guild = interaction.guild
            mod_channel_id = self.bot.CHANNEL_IDS.get("AIRLINE_MODERATION_CHANNEL")
            if mod_channel_id:
                mod_channel = guild.get_channel(mod_channel_id)
                if mod_channel:
                    message = await mod_channel.send(embed=embed, view=view)
                    # Сохраняем ID сообщения для возможного редактирования
                    view.original_message_id = message.id

            await interaction.response.send_message(
                "✅ Ваша заявка отправлена на модерацию! Ожидайте рассмотрения.",
                ephemeral=True
            )

        except Exception as e:
            try:
                await interaction.response.send_message(
                    f"❌ Произошла ошибка при отправке заявки: {str(e)}",
                    ephemeral=True
                )
            except:
                await interaction.followup.send(
                    f"❌ Произошла ошибка при отправке заявки: {str(e)}",
                    ephemeral=True
                )

class PartnerApplicationModal(Modal, title="🤝 Заявка на партнерство"):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

        self.server_name = TextInput(
            label="Название сервера",
            placeholder="Официальное название сервера Discord",
            required=True,
            max_length=100
        )

        self.server_link = TextInput(
            label="Ссылка на сервер",
            placeholder="https://discord.gg/...",
            required=True
        )

        self.channel_id = TextInput(
            label="ID канала для рейсов",
            placeholder="ID канала, где будут публиковаться рейсы",
            required=True
        )

        self.contact = TextInput(
            label="Контактное лицо",
            placeholder="Discord username (например: username#1234)",
            required=True
        )

        self.add_item(self.server_name)
        self.add_item(self.server_link)
        self.add_item(self.channel_id)
        self.add_item(self.contact)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            db = self.bot.data.db

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
            app_id = application_doc[1].id

            # Отправляем в канал модерации партнеров
            guild = interaction.guild
            mod_channel_id = self.bot.CHANNEL_IDS.get("PARTNER_MODERATION_CHANNEL")

            if mod_channel_id:
                mod_channel = guild.get_channel(mod_channel_id)
                if mod_channel:
                    embed = discord.Embed(
                        title="🤝 Новая заявка на партнерство",
                        color=discord.Color.blue(),
                        timestamp=datetime.now()
                    )

                    embed.add_field(name="👤 Заявитель", value=f"{interaction.user.mention}\nID: {interaction.user.id}", inline=True)
                    embed.add_field(name="🏢 Сервер", value=self.server_name.value, inline=True)
                    embed.add_field(name="🔗 Ссылка", value=self.server_link.value, inline=True)
                    embed.add_field(name="📺 Канал", value=f"ID: `{self.channel_id.value}`", inline=True)
                    embed.add_field(name="📞 Контакт", value=self.contact.value, inline=True)
                    embed.add_field(name="📋 ID заявки", value=f"`{app_id}`", inline=False)

                    class PartnerModerationView(discord.ui.View):
                        def __init__(self, app_id: str, applicant_id: int, bot, original_message_id: int = None):
                            super().__init__(timeout=None)
                            self.app_id = app_id
                            self.applicant_id = applicant_id
                            self.bot = bot
                            self.original_message_id = original_message_id

                        @discord.ui.button(label="✅ Одобрить", style=discord.ButtonStyle.success)
                        async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                            # Обновляем статус заявки
                            app_ref = partners_ref.document(self.app_id)
                            app_ref.update({
                                'status': 'approved',
                                'moderator_id': str(interaction.user.id),
                                'moderator_name': str(interaction.user),
                                'approved_at': datetime.now().isoformat()
                            })

                            # Создаем партнера
                            app_data = app_ref.get().to_dict()

                            partner_data = {
                                'server_name': app_data['server_name'],
                                'server_link': app_data['server_link'],
                                'channel_id': app_data['channel_id'],
                                'contact': app_data['contact'],
                                'applicant_id': app_data['applicant_id'],
                                'applicant_name': app_data['applicant_name'],
                                'status': 'active',
                                'joined_at': datetime.now().isoformat(),
                                'published_flights': 0,
                                'last_published': None
                            }

                            db.collection('partners').add(partner_data)

                            # Выдаем роль партнера
                            guild = interaction.guild
                            user = guild.get_member(self.applicant_id)
                            if user:
                                role = discord.utils.get(guild.roles, name="Партнер")
                                if not role:
                                    role = await guild.create_role(
                                        name="Партнер",
                                        color=discord.Color.green(),
                                        reason="Роль для партнеров платформы"
                                    )
                                await user.add_roles(role)

                            # Отправляем сообщение заявителю
                            try:
                                user = await self.bot.fetch_user(self.applicant_id)
                                await user.send(f"✅ Ваша заявка на партнерство для сервера **{app_data['server_name']}** одобрена!")
                            except:
                                pass

                            # Логируем в аудит
                            audit_channel_id = self.bot.CHANNEL_IDS.get("AUDIT_CHANNEL")
                            if audit_channel_id:
                                audit_channel = guild.get_channel(audit_channel_id)
                                if audit_channel:
                                    audit_embed = discord.Embed(
                                        title="✅ Партнерская заявка одобрена",
                                        color=discord.Color.green(),
                                        timestamp=datetime.now()
                                    )
                                    audit_embed.add_field(name="👤 Заявитель", value=f"<@{self.applicant_id}>", inline=True)
                                    audit_embed.add_field(name="🏢 Сервер", value=app_data['server_name'], inline=True)
                                    audit_embed.add_field(name="👮 Модератор", value=interaction.user.mention, inline=True)
                                    await audit_channel.send(embed=audit_embed)

                            embed.color = discord.Color.green()
                            embed.add_field(name="✅ Статус", value="Одобрено", inline=False)
                            embed.add_field(name="👮 Модератор", value=interaction.user.mention, inline=False)

                            try:
                                await interaction.response.edit_message(embed=embed, view=None)
                            except discord.errors.NotFound:
                                await interaction.followup.send("✅ Заявка одобрена!", ephemeral=True)

                        @discord.ui.button(label="❌ Отклонить", style=discord.ButtonStyle.danger)
                        async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                            class RejectReasonModal(Modal, title="Причина отклонения партнерства"):
                                def __init__(self, app_id: str, applicant_id: int):
                                    super().__init__()
                                    self.app_id = app_id
                                    self.applicant_id = applicant_id

                                    self.reason = TextInput(
                                        label="Причина отклонения",
                                        placeholder="Укажите причину отклонения заявки...",
                                        required=True,
                                        style=discord.TextStyle.paragraph
                                    )
                                    self.add_item(self.reason)

                                async def on_submit(self, interaction: discord.Interaction):
                                    app_ref = partners_ref.document(self.app_id)
                                    app_ref.update({
                                        'status': 'rejected',
                                        'moderator_id': str(interaction.user.id),
                                        'moderator_name': str(interaction.user),
                                        'rejection_reason': self.reason.value
                                    })

                                    app_data = app_ref.get().to_dict()

                                    # Уведомляем заявителя
                                    try:
                                        user = await interaction.client.fetch_user(self.applicant_id)
                                        await user.send(f"❌ Ваша заявка на партнерство для сервера **{app_data['server_name']}** отклонена. Причина: {self.reason.value}")
                                    except:
                                        pass

                                    embed.color = discord.Color.red()
                                    embed.add_field(name="❌ Статус", value="Отклонено", inline=False)
                                    embed.add_field(name="👮 Модератор", value=interaction.user.mention, inline=False)
                                    embed.add_field(name="📝 Причина", value=self.reason.value[:200], inline=False)

                                    try:
                                        await interaction.response.edit_message(embed=embed, view=None)
                                    except discord.errors.NotFound:
                                        await interaction.followup.send("❌ Заявка отклонена!", ephemeral=True)

                            modal = RejectReasonModal(self.app_id, self.applicant_id)
                            await interaction.response.send_modal(modal)

                    view = PartnerModerationView(app_id, interaction.user.id, self.bot)
                    message = await mod_channel.send(embed=embed, view=view)
                    view.original_message_id = message.id

            await interaction.response.send_message(
                "✅ Ваша заявка на партнерство отправлена на модерацию!",
                ephemeral=True
            )

        except Exception as e:
            try:
                await interaction.response.send_message(
                    f"❌ Произошла ошибка при отправке заявки: {str(e)}",
                    ephemeral=True
                )
            except:
                await interaction.followup.send(
                    f"❌ Произошла ошибка при отправке заявки: {str(e)}",
                    ephemeral=True
                )

class SupportTicketModal(Modal, title="🆘 Обращение в поддержку"):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

        self.issue_type = TextInput(
            label="Тип проблемы",
            placeholder="Техническая, Вопрос по рейсу, Другое",
            required=True,
            max_length=50
        )

        self.description = TextInput(
            label="Подробное описание",
            placeholder="Опишите вашу проблему как можно подробнее...",
            required=True,
            style=discord.TextStyle.paragraph,
            max_length=1000
        )

        self.add_item(self.issue_type)
        self.add_item(self.description)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            db = self.bot.data.db

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
            ticket_id = ticket_doc[1].id

            # Отправляем в канал поддержки
            guild = interaction.guild
            support_channel_id = self.bot.CHANNEL_IDS.get("SUPPORT_TICKETS_CHANNEL")

            if support_channel_id:
                support_channel = guild.get_channel(support_channel_id)

                if support_channel:
                    embed = discord.Embed(
                        title=f"🆘 Новый тикет #{ticket_id[:8]}",
                        color=discord.Color.orange(),
                        timestamp=datetime.now()
                    )

                    embed.add_field(name="👤 Пользователь", value=f"{interaction.user.mention}\nID: {interaction.user.id}", inline=True)
                    embed.add_field(name="📋 Тип", value=self.issue_type.value, inline=True)
                    embed.add_field(name="📝 Описание", value=self.description.value[:500] + "..." if len(self.description.value) > 500 else self.description.value, inline=False)
                    embed.add_field(name="⏰ Время создания", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=True)

                    class TicketView(discord.ui.View):
                        def __init__(self, ticket_id: str, user_id: int, bot, original_message_id: int = None):
                            super().__init__(timeout=None)
                            self.ticket_id = ticket_id
                            self.user_id = user_id
                            self.bot = bot
                            self.original_message_id = original_message_id

                        @discord.ui.button(label="📥 Взять тикет", style=discord.ButtonStyle.primary, emoji="👮")
                        async def take_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
                            # Проверяем, не взят ли уже тикет
                            ticket_ref = tickets_ref.document(self.ticket_id)
                            ticket_data = ticket_ref.get().to_dict()

                            if ticket_data['assigned_to']:
                                try:
                                    await interaction.response.send_message(
                                        "❌ Этот тикет уже взят другим модератором!",
                                        ephemeral=True
                                    )
                                except:
                                    await interaction.followup.send(
                                        "❌ Этот тикет уже взят другим модератором!",
                                        ephemeral=True
                                    )
                                return

                            # Назначаем модератора
                            ticket_ref.update({
                                'assigned_to': str(interaction.user.id),
                                'assigned_name': str(interaction.user),
                                'status': 'in_progress',
                                'assigned_at': datetime.now().isoformat()
                            })

                            # Отправляем сообщение пользователю
                            try:
                                user = await self.bot.fetch_user(self.user_id)

                                user_embed = discord.Embed(
                                    title="👮 Ваш тикет взят в работу",
                                    description=f"Модератор {interaction.user.mention} взял ваш тикет в работу. Ожидайте ответа.",
                                    color=discord.Color.green()
                                )
                                user_embed.add_field(name="Тикет", value=f"`#{self.ticket_id[:8]}`", inline=True)
                                user_embed.add_field(name="Тип проблемы", value=ticket_data['issue_type'], inline=True)

                                class UserResponseView(discord.ui.View):
                                    def __init__(self, ticket_id: str, moderator_id: int, bot):
                                        super().__init__(timeout=None)
                                        self.ticket_id = ticket_id
                                        self.moderator_id = moderator_id
                                        self.bot = bot

                                    @discord.ui.button(label="💬 Ответить", style=discord.ButtonStyle.primary, emoji="✍️")
                                    async def respond_button(self, interaction: discord.Interaction, button: discord.ui.Button):
                                        class ResponseModal(Modal, title="Ответ на тикет"):
                                            def __init__(self, ticket_id: str, moderator_id: int):
                                                super().__init__()
                                                self.ticket_id = ticket_id
                                                self.moderator_id = moderator_id

                                                self.response = TextInput(
                                                    label="Ваш ответ",
                                                    placeholder="Введите ваш ответ модератору...",
                                                    required=True,
                                                    style=discord.TextStyle.paragraph,
                                                    max_length=1000
                                                )
                                                self.add_item(self.response)

                                            async def on_submit(self, interaction: discord.Interaction):
                                                # Добавляем сообщение в историю тикета
                                                ticket_ref = tickets_ref.document(self.ticket_id)
                                                ticket_ref.update({
                                                    'messages': firestore.ArrayUnion([{
                                                        'from': 'user',
                                                        'user_id': str(interaction.user.id),
                                                        'message': self.response.value,
                                                        'timestamp': datetime.now().isoformat()
                                                    }])
                                                })

                                                # Отправляем ответ модератору
                                                try:
                                                    moderator = await interaction.client.fetch_user(self.moderator_id)
                                                    await moderator.send(f"💬 Пользователь ответил на тикет #{self.ticket_id[:8]}:\n\n{self.response.value}")
                                                except:
                                                    pass

                                                await interaction.response.send_message(
                                                    "✅ Ваш ответ отправлен модератору!",
                                                    ephemeral=True
                                                )

                                        modal = ResponseModal(self.ticket_id, self.moderator_id)
                                        await interaction.response.send_modal(modal)

                                user_view = UserResponseView(self.ticket_id, interaction.user.id, self.bot)
                                await user.send(embed=user_embed, view=user_view)
                            except Exception as e:
                                print(f"Ошибка отправки сообщения пользователю: {e}")

                            # Обновляем Embed
                            embed.color = discord.Color.green()
                            embed.add_field(name="👮 Модератор", value=interaction.user.mention, inline=False)

                            try:
                                await interaction.response.edit_message(embed=embed, view=None)
                            except discord.errors.NotFound:
                                await interaction.followup.send("✅ Тикет взят в работу!", ephemeral=True)

                        @discord.ui.button(label="🔒 Закрыть", style=discord.ButtonStyle.secondary, emoji="🔒")
                        async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
                            class CloseReasonModal(Modal, title="Причина закрытия тикета"):
                                def __init__(self, ticket_id: str, bot):
                                    super().__init__()
                                    self.ticket_id = ticket_id
                                    self.bot = bot

                                    self.reason = TextInput(
                                        label="Причина закрытия",
                                        placeholder="Укажите причину закрытия тикета...",
                                        required=True,
                                        style=discord.TextStyle.paragraph
                                    )
                                    self.add_item(self.reason)

                                async def on_submit(self, interaction: discord.Interaction):
                                    ticket_ref = tickets_ref.document(self.ticket_id)
                                    ticket_data = ticket_ref.get().to_dict()

                                    ticket_ref.update({
                                        'status': 'closed',
                                        'closed_by': str(interaction.user.id),
                                        'closed_at': datetime.now().isoformat(),
                                        'close_reason': self.reason.value
                                    })

                                    # Уведомляем пользователя
                                    try:
                                        user = await self.bot.fetch_user(int(ticket_data['user_id']))
                                        await user.send(f"🔒 Ваш тикет #{self.ticket_id[:8]} закрыт. Причина: {self.reason.value}")
                                    except:
                                        pass

                                    # Логируем в аудит
                                    audit_channel_id = self.bot.CHANNEL_IDS.get("AUDIT_CHANNEL")
                                    if audit_channel_id:
                                        audit_channel = guild.get_channel(audit_channel_id)
                                        if audit_channel:
                                            audit_embed = discord.Embed(
                                                title="🔒 Тикет закрыт",
                                                color=discord.Color.greyple(),
                                                timestamp=datetime.now()
                                            )
                                            audit_embed.add_field(name="Тикет", value=f"`#{self.ticket_id[:8]}`", inline=True)
                                            audit_embed.add_field(name="Пользователь", value=f"<@{ticket_data['user_id']}>", inline=True)
                                            audit_embed.add_field(name="Модератор", value=interaction.user.mention, inline=True)
                                            audit_embed.add_field(name="Причина", value=self.reason.value[:200], inline=False)
                                            await audit_channel.send(embed=audit_embed)

                                    embed.color = discord.Color.greyple()
                                    embed.add_field(name="🔒 Статус", value="Закрыт", inline=False)
                                    embed.add_field(name="👮 Модератор", value=interaction.user.mention, inline=False)
                                    embed.add_field(name="📝 Причина", value=self.reason.value[:200], inline=False)

                                    try:
                                        await interaction.response.edit_message(embed=embed, view=None)
                                    except discord.errors.NotFound:
                                        await interaction.followup.send("🔒 Тикет закрыт!", ephemeral=True)

                            modal = CloseReasonModal(self.ticket_id, self.bot)
                            await interaction.response.send_modal(modal)

                    view = TicketView(ticket_id, interaction.user.id, self.bot)
                    message = await support_channel.send(embed=embed, view=view)
                    view.original_message_id = message.id

            await interaction.response.send_message(
                "✅ Ваше обращение отправлено в поддержку! Ожидайте ответа.",
                ephemeral=True
            )

        except Exception as e:
            try:
                await interaction.response.send_message(
                    f"❌ Произошла ошибка при создании тикета: {str(e)}",
                    ephemeral=True
                )
            except:
                await interaction.followup.send(
                    f"❌ Произошла ошибка при создании тикета: {str(e)}",
                    ephemeral=True
                )