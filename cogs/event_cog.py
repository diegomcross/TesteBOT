# cogs/event_cog.py
import discord
from discord import app_commands, ui
from discord.ext import commands
import asyncio
import datetime
import sqlite3
import pytz
import re
from typing import Literal, Optional, List

import dateparser

# Imports customizados
import database as db
import utils 
import role_utils 
from constants import (
    BRAZIL_TZ, BRAZIL_TZ_STR,
    DIAS_SEMANA_PT_FULL, DIAS_SEMANA_PT_SHORT, MESES_PT
)
from utils import SelectChannelView, SelectActivityDetailsView, ConfirmActivityView


# --- Modals ---
class EditEventModal(discord.ui.Modal, title="✏️ Editar Detalhes Básicos"):
    event_title_input = ui.TextInput(label="Título do Evento", style=discord.TextStyle.short, required=True, max_length=200)
    event_description_input = ui.TextInput(label="Descrição (ou 'x' para remover)", style=discord.TextStyle.paragraph, required=False, max_length=1000)
    event_datetime_input = ui.TextInput(label="Nova Data e Hora (DD/MM HH:MM ou 'x')", placeholder="Ex: 25/12 19:30 ou 'x' para não alterar", required=False, max_length=20)

    def __init__(self, current_title: str, current_description: str | None, current_datetime_utc_str: str, bot_instance: commands.Bot, event_id: int, parent_view_instance):
        super().__init__(timeout=None)
        self.bot = bot_instance
        self.event_id = event_id
        self.original_event_time_utc_str = current_datetime_utc_str
        self.parent_view_instance = parent_view_instance

        self.event_title_input.default = current_title
        self.event_description_input.default = current_description if current_description else ""
        try:
            dt_utc = datetime.datetime.fromisoformat(current_datetime_utc_str.replace('Z', '+00:00'))
            if dt_utc.tzinfo is None: dt_utc = pytz.utc.localize(dt_utc)
            dt_brt = dt_utc.astimezone(BRAZIL_TZ)
            self.event_datetime_input.placeholder = dt_brt.strftime('%d/%m %H:%M')
            self.event_datetime_input.default = dt_brt.strftime('%d/%m %H:%M')
        except Exception as e:
            print(f"Error parsing date for EditEventModal default: {e}")
            self.event_datetime_input.placeholder = "DD/MM HH:MM"
            self.event_datetime_input.default = ""

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        new_title_str = self.event_title_input.value.strip()
        new_description_input = self.event_description_input.value.strip()
        new_datetime_input_str = self.event_datetime_input.value.strip()

        current_event_details = db.db_get_event_details(self.event_id)
        if not current_event_details:
            await interaction.followup.send("Erro: Evento original não pôde ser lido.", ephemeral=True); return

        final_title = current_event_details['title']
        final_description = current_event_details['description']
        final_event_time_utc_str = self.original_event_time_utc_str
        final_event_dt_brt_for_role_name = datetime.datetime.fromisoformat(self.original_event_time_utc_str.replace('Z', '+00:00')).astimezone(BRAZIL_TZ).date()

        title_changed = False
        if new_title_str and new_title_str != final_title:
            final_title = new_title_str
            title_changed = True

        if new_description_input.lower() == 'x': final_description = None
        elif new_description_input: final_description = new_description_input
        elif not new_description_input and self.event_description_input.default : final_description = None

        temp_role_id_to_notify = current_event_details['temp_role_id']
        original_datetime_for_comparison = datetime.datetime.fromisoformat(self.original_event_time_utc_str.replace('Z', '+00:00')).astimezone(BRAZIL_TZ)
        datetime_changed = False
        parsed_dt_brt_for_notification = None 

        if new_datetime_input_str.lower() != 'x' and \
           new_datetime_input_str != '' and \
           new_datetime_input_str != self.event_datetime_input.placeholder:
            now_brt = utils.get_brazil_now()
            current_year = now_brt.year
            parsed_dt_brt = None
            parser_settings = {'TIMEZONE': BRAZIL_TZ_STR, 'RETURN_AS_TIMEZONE_AWARE': True, 'PREFER_DATES_FROM': 'future', 'STRICT_PARSING': False}

            if len(new_datetime_input_str.split('/')) == 2 and ':' in new_datetime_input_str :
                try_datetime_str_current_year = f"{new_datetime_input_str}/{current_year}"
                parsed_dt_brt = dateparser.parse(try_datetime_str_current_year, date_formats=['%d/%m/%Y %H:%M', '%d/%m %H:%M'], languages=['pt'], settings=parser_settings)

            if not parsed_dt_brt: 
                parsed_dt_brt = dateparser.parse(new_datetime_input_str, languages=['pt'], settings=parser_settings)

            if parsed_dt_brt:
                if parsed_dt_brt.tzinfo is None: parsed_dt_brt = BRAZIL_TZ.localize(parsed_dt_brt)

                is_short_date_format = (
                    (len(new_datetime_input_str.split('/')) == 2 and len(new_datetime_input_str.split('/')[1].split(' ')[0]) <=2) or 
                    (len(new_datetime_input_str.split('/')) == 3 and \
                     len(new_datetime_input_str.split('/')[2].split(' ')[0]) <=2 and \
                     (str(current_year) not in new_datetime_input_str and str(current_year+1) not in new_datetime_input_str) )
                )

                if parsed_dt_brt < now_brt and is_short_date_format:
                    try_date_next_year_str = ""
                    parts = new_datetime_input_str.split(' ')
                    date_part = parts[0]; time_part = parts[1] if len(parts) > 1 else "00:00"
                    if len(date_part.split('/')) == 2: 
                        try_date_next_year_str = f"{date_part}/{current_year + 1} {time_part}"
                    if try_date_next_year_str:
                        try_date_next_year = dateparser.parse(try_date_next_year_str, date_formats=['%d/%m/%Y %H:%M'], languages=['pt'], settings=parser_settings)
                        if try_date_next_year and try_date_next_year.tzinfo is None: try_date_next_year = BRAZIL_TZ.localize(try_date_next_year)
                        if try_date_next_year and try_date_next_year > now_brt: parsed_dt_brt = try_date_next_year

                if parsed_dt_brt > now_brt: 
                    final_event_time_utc_str = parsed_dt_brt.astimezone(pytz.utc).isoformat()
                    final_event_dt_brt_for_role_name = parsed_dt_brt.date() 
                    parsed_dt_brt_for_notification = parsed_dt_brt 

                    new_datetime_for_comparison = parsed_dt_brt
                    if new_datetime_for_comparison.date() != original_datetime_for_comparison.date() or \
                       new_datetime_for_comparison.time() != original_datetime_for_comparison.time():
                        datetime_changed = True
                else:
                    await interaction.followup.send(f"A nova data/hora '{new_datetime_input_str}' (interpretada como {parsed_dt_brt.strftime('%d/%m/%Y %H:%M')}) não é válida ou está no passado. A data/hora original foi mantida.", ephemeral=True)
            elif new_datetime_input_str.lower() != 'x' and new_datetime_input_str != '': 
                await interaction.followup.send(f"Formato de data/hora '{new_datetime_input_str}' inválido. A data/hora original foi mantida.", ephemeral=True)

        if datetime_changed and temp_role_id_to_notify and interaction.guild and parsed_dt_brt_for_notification:
            temp_role = interaction.guild.get_role(temp_role_id_to_notify)
            if temp_role:
                event_channel = self.bot.get_channel(current_event_details['channel_id'])
                if event_channel and isinstance(event_channel, discord.TextChannel):
                    try:
                        new_time_formatted = f"<t:{int(parsed_dt_brt_for_notification.timestamp())}:F>"
                        await event_channel.send(f"📢 {temp_role.mention} Atenção! O evento **'{final_title}'** (anteriormente '{current_event_details['title']}') foi reagendado para: {new_time_formatted}")
                        print(f"DEBUG: Notificação de reagendamento enviada para evento {self.event_id}, cargo {temp_role_id_to_notify}.")
                    except Exception as e_notify:
                        print(f"Erro ao notificar mudança de horário para evento {self.event_id}: {e_notify}")

        if (title_changed or datetime_changed) and temp_role_id_to_notify and interaction.guild:
            temp_role_obj = interaction.guild.get_role(temp_role_id_to_notify)
            if temp_role_obj:
                new_role_name_expected = f"Evento ID {self.event_id} - {final_title[:50]} - {final_event_dt_brt_for_role_name.strftime('%d/%m')}"
                if temp_role_obj.name != new_role_name_expected:
                    try:
                        await temp_role_obj.edit(name=new_role_name_expected, reason=f"Título/data do evento {self.event_id} alterado.")
                        print(f"DEBUG: Cargo temporário {temp_role_id_to_notify} renomeado para '{new_role_name_expected}'.")
                    except discord.Forbidden: print(f"WARN: Sem permissão para renomear cargo temporário {temp_role_id_to_notify}.")
                    except discord.HTTPException as e_rename: print(f"WARN: Erro HTTP ao renomear cargo temporário {temp_role_id_to_notify}: {e_rename}")

        db.db_update_event_details(event_id=self.event_id, title=final_title, description=final_description, event_time_utc=final_event_time_utc_str)

        event_details_updated = db.db_get_event_details(self.event_id)
        if event_details_updated and event_details_updated['channel_id'] and event_details_updated['message_id']:
            if self.parent_view_instance:
                 await self.parent_view_instance._update_event_message_embed(self.event_id, event_details_updated['channel_id'], event_details_updated['message_id'])
        await interaction.followup.send("Detalhes básicos do evento atualizados!", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        print(f"Erro no EditEventModal: {error}"); import traceback; traceback.print_exc()
        msg = "Ocorreu um erro crítico ao processar a edição. Verifique o console."
        if interaction.response.is_done(): await interaction.followup.send(msg, ephemeral=True)
        else: await interaction.response.send_message(msg, ephemeral=True, delete_after=10)

class EditOptionsView(discord.ui.View):
    def __init__(self, bot_instance: commands.Bot, event_id: int, original_interaction: discord.Interaction, parent_view_instance):
        super().__init__(timeout=180.0)
        self.bot = bot_instance
        self.event_id = event_id
        self.original_interaction = original_interaction
        self.message_with_options: Optional[discord.Message] = None
        self.parent_view_instance = parent_view_instance

    async def disable_all_buttons(self, interaction_to_edit: Optional[discord.Interaction] = None, content: Optional[str] = None):
        for item in self.children:
            if isinstance(item, discord.ui.Button): item.disabled = True
        final_content = content or "Opções desabilitadas."
        if interaction_to_edit and not interaction_to_edit.response.is_done():
            await interaction_to_edit.response.edit_message(content=final_content, view=self)
        elif self.message_with_options:
            try: await self.message_with_options.edit(content=final_content, view=self)
            except: pass
        self.stop()

    @discord.ui.button(label="Título/Desc/Data/Hora", style=discord.ButtonStyle.green, custom_id="edit_basic_details_opt", emoji="📝")
    async def edit_basic_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        event_details = db.db_get_event_details(self.event_id)
        if not event_details:
            await interaction.response.send_message("Evento não encontrado.", ephemeral=True, delete_after=10)
            await self.disable_all_buttons(interaction, "Erro: Evento não encontrado."); return
        modal = EditEventModal(
            event_details['title'], event_details['description'], event_details['event_time_utc'],
            self.bot, self.event_id, self.parent_view_instance
        )
        await interaction.response.send_modal(modal)
        if self.message_with_options:
            try: await self.message_with_options.edit(content="Modal de edição básica aberto.", view=None)
            except: pass
        self.stop()

    @discord.ui.button(label="Tipo/Vagas", style=discord.ButtonStyle.primary, custom_id="edit_type_spots_opt", emoji="⚙️")
    async def edit_type_spots_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user = interaction.user
        dm_channel = await user.create_dm()
        event_details = db.db_get_event_details(self.event_id)
        if not event_details:
            await dm_channel.send("Erro: Evento não encontrado."); self.stop(); return

        await interaction.followup.send("Edição de Tipo/Vagas continuará na sua DM.", ephemeral=True)
        if self.message_with_options:
             try: await self.message_with_options.edit(content="Edição de Tipo/Vagas movida para DM.", view=None)
             except: pass

        await dm_channel.send(f"Editando Tipo/Vagas para: **{event_details['title']}**\nTipo: `{event_details['activity_type']}`, Vagas: `{event_details['max_attendees']}`")

        type_details_view = utils.SelectActivityDetailsView(self.bot, interaction)
        type_details_msg_dm = await dm_channel.send(
            "Por favor, selecione o novo tipo de atividade:",
            view=type_details_view
        )
        type_details_view.message = type_details_msg_dm
        await type_details_view.wait()

        if type_details_view.selected_activity_type and type_details_view.selected_max_attendees is not None:
            new_activity_type = type_details_view.selected_activity_type
            new_max_attendees = type_details_view.selected_max_attendees

            if new_activity_type != event_details['activity_type'] or new_max_attendees != event_details['max_attendees']:
                db.db_update_event_details(event_id=self.event_id, activity_type=new_activity_type, max_attendees=new_max_attendees)
                await dm_channel.send(f"Tipo/Vagas atualizados para '{new_activity_type}' ({new_max_attendees} vagas).")
                if self.parent_view_instance and event_details['channel_id'] and event_details['message_id']:
                    await self.parent_view_instance._update_event_message_embed(self.event_id, event_details['channel_id'], event_details['message_id'])
            else:
                await dm_channel.send("Tipo/Vagas mantidos como os atuais.")
        else:
            await dm_channel.send("Edição de tipo/vagas cancelada ou tempo esgotado.")
        self.stop()


    @discord.ui.button(label="Cargos Mencionados (em breve)", style=discord.ButtonStyle.secondary, custom_id="edit_mentioned_roles_opt", disabled=True, emoji="🗣️")
    async def edit_mentioned_roles_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Edição de cargos mencionados em breve!", ephemeral=True, delete_after=10); await self.disable_all_buttons(interaction)

    @discord.ui.button(label="Cargos Restritos (em breve)", style=discord.ButtonStyle.secondary, custom_id="edit_restricted_roles_opt", disabled=True, emoji="🔐")
    async def edit_restricted_roles_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Edição de cargos restritos em breve!", ephemeral=True, delete_after=10); await self.disable_all_buttons(interaction)

    @discord.ui.button(label="Cancelar Edição", style=discord.ButtonStyle.grey, custom_id="cancel_edit_flow_opt", emoji="↩️")
    async def cancel_edit_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.response.is_done(): await interaction.response.edit_message(content="Edição cancelada.", view=None)
        elif self.message_with_options: await self.message_with_options.edit(content="Edição cancelada.", view=None)
        self.stop()

    async def on_timeout(self):
        await self.disable_all_buttons(None, "Tempo esgotado para escolher opção de edição.")
        try:
            if self.original_interaction and not self.original_interaction.is_expired():
                await self.original_interaction.followup.send("Tempo esgotado para opções de edição.",ephemeral=True)
        except: pass; self.stop()

class ConfirmDeleteView(discord.ui.View):
    def __init__(self, bot_instance: commands.Bot, event_id: int, original_button_interaction: discord.Interaction, parent_view_instance):
        super().__init__(timeout=60.0)
        self.bot = bot_instance; self.event_id = event_id
        self.original_button_interaction = original_button_interaction
        self.message_sent_for_confirmation: Optional[discord.Message] = None
        self.parent_view_instance = parent_view_instance

    async def disable_all_buttons(self, content: Optional[str] = None):
        for item in self.children:
            if isinstance(item, discord.ui.Button): item.disabled = True
        if self.message_sent_for_confirmation:
            try: await self.message_sent_for_confirmation.edit(content=content or "Ação processada.", view=self)
            except: pass
        self.stop()

    @discord.ui.button(label="Sim, Apagar Evento", style=discord.ButtonStyle.danger, custom_id="confirm_delete_event_yes")
    async def confirm_yes_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer() 
        event_details = db.db_get_event_details(self.event_id)
        if not event_details:
            await self.disable_all_buttons("Erro: Evento não encontrado.");
            await self.original_button_interaction.followup.send("Erro: Evento não encontrado ao apagar.", ephemeral=True); return

        guild = self.bot.get_guild(event_details['guild_id'])
        temp_role_id = event_details['temp_role_id']
        role_deleted_msg = ""
        attendees_to_notify = db.db_get_rsvps_for_event(self.event_id).get('vou', [])

        notification_message = f"ℹ️ O evento **'{event_details['title']}'** para o qual você estava inscrito(a) foi cancelado."
        if attendees_to_notify and guild:
            for user_id_notify in attendees_to_notify:
                try:
                    member_to_notify = guild.get_member(user_id_notify)
                    if not member_to_notify:
                        print(f"INFO_EVENT_COG: Não foi possível encontrar o membro {user_id_notify} na guilda para notificar sobre o cancelamento do evento {self.event_id}. Provavelmente saiu do servidor.")
                        continue

                    if not member_to_notify.bot:
                        await member_to_notify.send(notification_message)
                        print(f"DEBUG: Notificação de cancelamento enviada para {member_to_notify.display_name} (ID: {user_id_notify}) para evento {self.event_id}")
                except discord.Forbidden:
                    print(f"WARN: Não foi possível enviar DM de cancelamento para {user_id_notify} (evento {self.event_id}).")
                except discord.NotFound:
                    print(f"INFO_EVENT_COG: Membro {user_id_notify} não encontrado ao tentar notificar sobre o cancelamento do evento {self.event_id}.")
                except Exception as e_dm_cancel:
                    print(f"ERRO: Erro inesperado ao enviar DM de cancelamento para {user_id_notify}: {e_dm_cancel}")

        if temp_role_id and guild:
            role_deleted = await role_utils.delete_event_role(guild, temp_role_id, f"Evento '{event_details['title']}' (ID: {self.event_id}) cancelado.")
            if role_deleted: role_deleted_msg = " Cargo temporário associado também foi deletado."
            else: role_deleted_msg = " Tentativa de deletar cargo temporário (verifique logs)."

        delete_time = datetime.datetime.now(pytz.utc) + datetime.timedelta(hours=1)
        db.db_update_event_status(self.event_id, 'cancelado', delete_time.isoformat())
        db.db_update_event_details(event_id=self.event_id, temp_role_id=None)

        if event_details['message_id'] and event_details['channel_id'] and self.parent_view_instance:
            await self.parent_view_instance._update_event_message_embed(self.event_id, event_details['channel_id'], event_details['message_id'])

        final_msg = f"Evento '{event_details['title']}' cancelado. Mensagem será apagada em 1h.{role_deleted_msg}"
        await self.disable_all_buttons(final_msg)
        await self.original_button_interaction.followup.send(final_msg, ephemeral=True)
        self.stop()

    @discord.ui.button(label="Não, Manter Evento", style=discord.ButtonStyle.secondary, custom_id="confirm_delete_event_no")
    async def confirm_no_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(); await self.disable_all_buttons("Operação de apagar cancelada.")
        await self.original_button_interaction.followup.send("Cancelamento abortado.", ephemeral=True); self.stop()

    async def on_timeout(self):
        await self.disable_all_buttons("Tempo esgotado. Apagar cancelado.")
        try:
            if self.original_button_interaction and not self.original_button_interaction.is_expired():
                await self.original_button_interaction.followup.send("Tempo esgotado para confirmar. Nada feito.", ephemeral=True)
        except: pass; self.stop()

class PersistentRsvpView(discord.ui.View):
    def __init__(self, bot_instance: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot_instance

    async def _extract_event_id_from_interaction(self, interaction: discord.Interaction) -> int | None:
        if not interaction.message or not interaction.message.embeds or not interaction.message.embeds[0].footer:
            msg = "Não identifico o evento (sem embed/footer)."
            try:
                if not interaction.response.is_done(): await interaction.response.send_message(msg, ephemeral=True, delete_after=10)
                else: await interaction.followup.send(msg, ephemeral=True)
            except discord.HTTPException: pass
            return None
        footer = interaction.message.embeds[0].footer.text
        match = re.search(r"ID do Evento:\s*(\d+)", footer)
        if not match or not match.group(1).isdigit():
            msg = f"Erro ao ler ID do evento: '{footer}'"
            try:
                if not interaction.response.is_done(): await interaction.response.send_message(msg, ephemeral=True, delete_after=10)
                else: await interaction.followup.send(msg, ephemeral=True)
            except discord.HTTPException: pass
            return None
        return int(match.group(1))

    async def _handle_rsvp_logic(self, interaction: discord.Interaction, new_status: str, event_id: int):
        print(f"DEBUG: _handle_rsvp_logic (EventCog) INICIADA para event_id={event_id}, user='{interaction.user.name}', status='{new_status}'")
        user_id = interaction.user.id
        if not interaction.response.is_done():
            try: await interaction.response.defer(ephemeral=True)
            except discord.HTTPException: print(f"DEBUG: Falha ao deferir RSVP para evento {event_id}"); return

        event_details = db.db_get_event_details(event_id)
        if not event_details:
            try: await interaction.followup.send("Evento não encontrado.", ephemeral=True)
            except discord.HTTPException: pass
            return

        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            try: await interaction.followup.send("Erro: contexto de servidor inválido.", ephemeral=True)
            except discord.HTTPException: pass
            return

        member: discord.Member = interaction.user # type: ignore

        member_roles_ids = {role.id for role in member.roles}
        event_restricted_ids_str = event_details['restricted_role_ids']
        event_restricted_ids = {int(rid) for rid in event_restricted_ids_str.split(',') if rid.strip().isdigit()} if event_restricted_ids_str else set()
        default_restricted_ids = set(db.db_get_default_restricted_roles(interaction.guild.id))
        all_restricted_ids = event_restricted_ids.union(default_restricted_ids)

        if all_restricted_ids and not member_roles_ids.isdisjoint(all_restricted_ids):
            try: await interaction.followup.send("Você não pode interagir com este evento (cargo restrito).", ephemeral=True)
            except discord.HTTPException: pass
            return

        max_attendees = event_details['max_attendees']
        current_rsvps = db.db_get_rsvps_for_event(event_id)
        current_vou_list = current_rsvps.get('vou', [])
        user_was_confirmed = user_id in current_vou_list
        user_current_status = None 
        for status_key, user_ids_in_status in current_rsvps.items():
            if user_id in user_ids_in_status:
                user_current_status = status_key
                break

        final_status_for_user = new_status

        if new_status == 'vou':
            if user_id in current_vou_list: pass 
            elif len(current_vou_list) < max_attendees: final_status_for_user = 'vou'
            else: final_status_for_user = 'lista_espera'

        db.db_add_or_update_rsvp(event_id, user_id, final_status_for_user)

        temp_role_id = event_details['temp_role_id']
        temp_role: Optional[discord.Role] = None
        if temp_role_id and interaction.guild:
            temp_role = interaction.guild.get_role(temp_role_id)

        if temp_role: 
            action_for_role = ""
            if final_status_for_user in ['vou', 'lista_espera'] and user_current_status not in ['vou', 'lista_espera']:
                action_for_role = "add"
            elif final_status_for_user not in ['vou', 'lista_espera'] and user_current_status in ['vou', 'lista_espera']:
                action_for_role = "remove"

            if action_for_role: 
                await role_utils.manage_member_event_role(member, temp_role, action_for_role, event_id)

        user_left_confirmed_spot = user_was_confirmed and final_status_for_user != 'vou'
        if user_left_confirmed_spot:
            updated_rsvps = db.db_get_rsvps_for_event(event_id) 
            if len(updated_rsvps.get('vou', [])) < max_attendees and updated_rsvps.get('lista_espera'):
                promoted_id = updated_rsvps['lista_espera'][0]
                db.db_add_or_update_rsvp(event_id, promoted_id, 'vou')
                if temp_role and interaction.guild: 
                    promoted_member_obj = interaction.guild.get_member(promoted_id)
                    if promoted_member_obj:
                        await role_utils.manage_member_event_role(promoted_member_obj, temp_role, "add", event_id)
                try:
                    promoted_user = self.bot.get_user(promoted_id) or await self.bot.fetch_user(promoted_id)
                    if promoted_user: await promoted_user.send(f"🎉 Vaga aberta para '{event_details['title']}'! Você foi confirmado(a)!")
                except Exception as e_dm: print(f"DEBUG: Erro DM promoção: {e_dm}")

        await self._update_event_message_embed(event_id, event_details['channel_id'], event_details['message_id'])
        print(f"DEBUG: _handle_rsvp_logic (EventCog) CONCLUÍDA para event_id={event_id}")

    async def _update_event_message_embed(self, event_id: int, channel_id: int, message_id: int | None):
        print(f"DEBUG: _update_event_message_embed (EventCog) INICIADA event_id={event_id}")
        if message_id is None: print(f"DEBUG: Evento {event_id} sem message_id."); return

        event_details = db.db_get_event_details(event_id)
        if not event_details: 
            print(f"DEBUG: Detalhes do evento {event_id} não encontrados para _update_event_message_embed."); return

        target_channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id) # type: ignore
        if not (target_channel and isinstance(target_channel, discord.TextChannel)):
            print(f"DEBUG: Canal {channel_id} não encontrado/inválido para evento {event_id}."); return

        message_to_edit: Optional[discord.Message] = None
        try: 
            message_to_edit = await target_channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden) as e: 
            print(f"DEBUG: Erro fetch msg {message_id} para evento {event_id}: {e}"); return
        except Exception as e: 
            print(f"DEBUG: Erro desconhecido fetch msg {message_id} para evento {event_id}: {e}"); return

        if event_details['status'] == 'cancelado':
            embed = discord.Embed(title=f"[CANCELADO] {event_details['title']}", description="Este evento foi cancelado.", color=discord.Color.dark_grey())
            dt_utc = datetime.datetime.fromisoformat(event_details['event_time_utc'].replace('Z', '+00:00'))
            embed.add_field(name="🗓️ Data Original", value=f"<t:{int(dt_utc.timestamp())}:F>", inline=False)
            try: await message_to_edit.edit(content="**EVENTO CANCELADO**", embed=embed, view=None)
            except Exception as e: print(f"DEBUG: Erro ao editar msg cancelada {event_id}: {e}")
            return
        elif event_details['status'] == 'concluido':
            embed = discord.Embed(title=f"[CONCLUÍDO] {event_details['title']}", description="Este evento já foi finalizado.", color=discord.Color.light_grey())
            dt_utc = datetime.datetime.fromisoformat(event_details['event_time_utc'].replace('Z', '+00:00'))
            embed.add_field(name="🗓️ Data Original", value=f"<t:{int(dt_utc.timestamp())}:F>", inline=False)
            try: await message_to_edit.edit(content="**EVENTO CONCLUÍDO**", embed=embed, view=None)
            except Exception as e: print(f"DEBUG: Erro ao editar msg concluída {event_id}: {e}")
            return

        rsvps_data = db.db_get_rsvps_for_event(event_id)
        active_event_embed = await utils.build_event_embed(event_details, rsvps_data, self.bot)

        try: 
            await message_to_edit.edit(embed=active_event_embed, view=self) 
            print(f"DEBUG: Embed do evento {event_id} ATUALIZADO usando build_event_embed.")
        except Exception as e: 
            print(f"DEBUG: ERRO ao editar msg {event_id} no final do _update_event_message_embed: {e}")
        print(f"DEBUG: _update_event_message_embed (EventCog) CONCLUÍDA event_id={event_id}")

    @discord.ui.button(label=None, emoji="✅", style=discord.ButtonStyle.secondary, custom_id="persistent_rsvp_vou")
    async def vou_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        event_id = await self._extract_event_id_from_interaction(interaction)
        if event_id is not None: await self._handle_rsvp_logic(interaction, "vou", event_id)

    @discord.ui.button(label=None, emoji="❌", style=discord.ButtonStyle.secondary, custom_id="persistent_rsvp_nao_vou")
    async def nao_vou_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        event_id = await self._extract_event_id_from_interaction(interaction)
        if event_id is not None: await self._handle_rsvp_logic(interaction, "nao_vou", event_id)

    @discord.ui.button(label=None, emoji="🔷", style=discord.ButtonStyle.secondary, custom_id="persistent_rsvp_talvez")
    async def talvez_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        event_id = await self._extract_event_id_from_interaction(interaction)
        if event_id is not None: await self._handle_rsvp_logic(interaction, "talvez", event_id)

    @discord.ui.button(label="Editar", emoji="📝", style=discord.ButtonStyle.secondary, custom_id="persistent_event_edit")
    async def edit_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.response.is_done(): await interaction.response.defer(ephemeral=True)
        event_id = await self._extract_event_id_from_interaction(interaction)
        if event_id is None: await interaction.followup.send("Não obtive ID do evento.", ephemeral=True); return
        event_details = db.db_get_event_details(event_id)
        if not event_details: await interaction.followup.send("Evento não encontrado.", ephemeral=True); return

        if not await utils.is_user_event_manager(interaction, event_details['creator_id'], 'editar_qualquer_evento'):
            await interaction.followup.send("Você não tem permissão para editar este evento.", ephemeral=True)
            return

        edit_opts_view = EditOptionsView(self.bot, event_id, interaction, self)
        msg = await interaction.followup.send(f"Editar '{event_details['title']}'?", view=edit_opts_view, ephemeral=True)
        edit_opts_view.message_with_options = msg

    @discord.ui.button(label="Apagar", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id="persistent_event_delete")
    async def delete_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.response.is_done(): await interaction.response.defer(ephemeral=True)
        event_id = await self._extract_event_id_from_interaction(interaction)
        if event_id is None: await interaction.followup.send("Não obtive ID do evento.", ephemeral=True); return
        event_details = db.db_get_event_details(event_id)
        if not event_details: await interaction.followup.send("Evento não encontrado.", ephemeral=True); return

        if not await utils.is_user_event_manager(interaction, event_details['creator_id'], 'apagar_qualquer_evento'):
            await interaction.followup.send("Você não tem permissão para apagar este evento.", ephemeral=True)
            return

        confirm_v = ConfirmDeleteView(self.bot, event_id, interaction, self)
        msg = await interaction.followup.send(f"Apagar '{event_details['title']}'?", view=confirm_v, ephemeral=True)
        confirm_v.message_sent_for_confirmation = msg

class EventCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="criar_evento", description="Cria um novo evento de Destiny 2 (via DM).")
    @app_commands.guild_only()
    async def criar_evento(self, interaction: discord.Interaction):
        if not await utils.check_event_permission(interaction, 'criar_eventos'):
            await interaction.response.send_message("Você não tem permissão para criar eventos.", ephemeral=True)
            return

        user = interaction.user
        try:
            await interaction.response.defer(ephemeral=True, thinking=False)
            await user.send(f"Olá {user.mention}! Vou te ajudar a configurar os detalhes do evento via DM.")
            await interaction.followup.send("DM enviada para configurar os detalhes do evento!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("Não consegui te enviar uma DM. Verifique suas configurações de privacidade.", ephemeral=True); return
        except Exception as e:
            await interaction.followup.send(f"Erro ao iniciar criação do evento: {e}", ephemeral=True); return

        dm_channel = user.dm_channel or await user.create_dm()
        event_data = {'role_mentions_ids': [], 'restricted_role_ids_list': []} 

        # ... (restante da lógica do criar_evento, como na versão anterior) ...
        pass

    @app_commands.command(name="lista", description="Lista os eventos dos próximos 3 dias.")
    @app_commands.guild_only()
    async def lista_command(self, interaction: discord.Interaction):
        if not interaction.guild_id:
            await interaction.response.send_message("Comando apenas para servidores.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        content = await utils.generate_event_list_message_content(interaction.guild_id, 3, self.bot)
        header = "**Eventos Agendados (Próximos 3 Dias):**\n"
        full_msg = header + content
        if len(full_msg) > 1950:
            await interaction.followup.send("Lista muito longa. Resumo diário pode ter mais detalhes.", ephemeral=True)
        else:
            await interaction.followup.send(full_msg, ephemeral=True)

    @app_commands.command(name="gerenciar_rsvp", description="Adiciona, remove ou altera o status de RSVP de um usuário.")
    @app_commands.guild_only()
    async def gerenciar_rsvp(self, interaction: discord.Interaction, id_do_evento: int, acao: str, usuario: discord.Member):
        await interaction.response.defer(ephemeral=True)
        event_details = db.db_get_event_details(id_do_evento)
        if not event_details:
            await interaction.followup.send(f"Evento ID {id_do_evento} não encontrado.", ephemeral=True); return

        if not await utils.is_user_event_manager(interaction, event_details['creator_id'], 'gerir_rsvp_qualquer_evento'):
            await interaction.followup.send("Você não tem permissão para gerenciar os RSVPs deste evento.", ephemeral=True)
            return

        # ... (restante da lógica do gerenciar_rsvp, como na versão anterior) ...
        pass

async def setup(bot: commands.Cog):
    await bot.add_cog(EventCog(bot))
