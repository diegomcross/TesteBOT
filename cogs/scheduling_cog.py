# cogs/scheduling_cog.py
import discord
from discord import app_commands, ui
from discord.ext import commands
import datetime
import pytz
import dateparser
from typing import Optional, List

# Imports de outros módulos do projeto
import database as db
import utils 
import role_utils
from constants import BRAZIL_TZ, BRAZIL_TZ_STR
# Views agora vêm de utils
from utils import SelectActivityDetailsView, SelectChannelView, ConfirmActivityView
from cogs.event_cog import PersistentRsvpView


# --- Modal de Agendamento de Evento ---
class AgendarEventoModal(discord.ui.Modal, title="📅 Agendar Novo Evento"):
    nome_evento_input = ui.TextInput(
        label="Nome do Evento",
        placeholder="Ex: Limiar da Salvação, Profecia, Desafios de Osíris",
        style=discord.TextStyle.short,
        required=True,
        max_length=150
    )
    descricao_input = ui.TextInput(
        label="Descrição/Observações (Opcional)",
        placeholder="Ex: Raid escola, foco em farm, levar mods de sobrecarga...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000
    )
    data_input = ui.TextInput(
        label="Data do Evento (DD/MM ou DD/MM/YYYY)",
        placeholder="Ex: 25/12 ou 25/12/2025",
        style=discord.TextStyle.short,
        required=True,
        max_length=10
    )
    hora_input = ui.TextInput(
        label="Hora do Evento",
        placeholder="Ex: 19:00, 7pm, 21h30, 10:30am",
        style=discord.TextStyle.short,
        required=True,
        min_length=3,
        max_length=10 
    )

    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        event_name_original_input = self.nome_evento_input.value.strip()
        event_description = self.descricao_input.value.strip() if self.descricao_input.value else None
        date_str = self.data_input.value.strip()
        time_str_input = self.hora_input.value.strip()

        now_brt = utils.get_brazil_now()
        parsed_date_only = dateparser.parse(date_str, languages=['pt'], settings={'PREFER_DATES_FROM': 'future', 'TIMEZONE': BRAZIL_TZ_STR})
        if not parsed_date_only:
            await interaction.followup.send(f"Não consegui entender a data: '{date_str}'.", ephemeral=True); return

        full_datetime_str_for_parse = f"{parsed_date_only.strftime('%d/%m/%Y')} {time_str_input}"
        event_dt_brt = dateparser.parse(full_datetime_str_for_parse, languages=['pt'], settings={'TIMEZONE': BRAZIL_TZ_STR, 'RETURN_AS_TIMEZONE_AWARE': True, 'PREFER_DATES_FROM': 'future'})

        if not event_dt_brt:
            await interaction.followup.send(f"Não entendi data/hora: '{full_datetime_str_for_parse}'.", ephemeral=True); return

        event_dt_brt = event_dt_brt.astimezone(BRAZIL_TZ)
        if event_dt_brt < now_brt:
            if str(now_brt.year) not in date_str and str(now_brt.year + 1) not in date_str and event_dt_brt.year == now_brt.year:
                try: event_dt_brt = event_dt_brt.replace(year=event_dt_brt.year + 1)
                except ValueError: await interaction.followup.send(f"Data/hora '{full_datetime_str_for_parse}' no passado, ajuste de ano falhou.", ephemeral=True); return
            if event_dt_brt < now_brt:
                await interaction.followup.send(f"Data/hora '{full_datetime_str_for_parse}' ({event_dt_brt.strftime('%d/%m/%Y %H:%M')}) no passado.", ephemeral=True); return

        event_data = {
            "title_input": event_name_original_input,
            "description": event_description,
            "event_time_utc": event_dt_brt.astimezone(pytz.utc).isoformat(),
            "event_date_obj_for_role": event_dt_brt.date(),
            "guild_id": interaction.guild_id, "creator_id": interaction.user.id,
            "created_at_utc": datetime.datetime.now(pytz.utc).isoformat()
        }

        detected_title, detected_activity_type, detected_max_attendees = utils.detect_activity_details(event_name_original_input)

        user_confirmed_detection = False
        final_title = event_name_original_input
        final_activity_type = None
        final_max_attendees = None

        if detected_activity_type and detected_max_attendees:
            confirm_view = utils.ConfirmActivityView(interaction, detected_title, detected_activity_type, detected_max_attendees)
            confirm_msg = await interaction.followup.send(confirm_view.confirmation_message_content, view=confirm_view, ephemeral=True)
            confirm_view.message = confirm_msg
            await confirm_view.wait()

            if confirm_view.confirmed is True:
                final_title = detected_title
                final_activity_type = detected_activity_type
                final_max_attendees = detected_max_attendees
                user_confirmed_detection = True
                await interaction.followup.send(f"Ok, usando: **{final_title}** (Tipo: {final_activity_type}, Vagas: {final_max_attendees}p).", ephemeral=True)
            elif confirm_view.confirmed is False:
                await interaction.followup.send("Ok, por favor, selecione o tipo de atividade e defina as vagas.", ephemeral=True)
                final_title = event_name_original_input
            elif confirm_view.confirmed is None:
                await interaction.followup.send("Tempo esgotado para confirmar a atividade. Criação cancelada.", ephemeral=True)
                return

        if not user_confirmed_detection:
            event_data["title"] = final_title
            type_details_view = utils.SelectActivityDetailsView(self.bot, interaction)
            type_select_msg = await interaction.followup.send(
                f"Para o evento '{event_data['title']}', por favor, selecione o tipo:", 
                view=type_details_view, ephemeral=True
            )
            type_details_view.message = type_select_msg
            await type_details_view.wait()

            if type_details_view.selected_activity_type and type_details_view.selected_max_attendees is not None:
                final_activity_type = type_details_view.selected_activity_type
                final_max_attendees = type_details_view.selected_max_attendees
            else:
                return

        event_data["title"] = final_title
        event_data["activity_type"] = final_activity_type
        event_data["max_attendees"] = final_max_attendees

        if not interaction.guild:
            await interaction.followup.send("Erro: Guild não encontrada.", ephemeral=True); return

        channel_options = await utils.get_text_channels_for_select(interaction.guild, self.bot.user) # type: ignore
        if not channel_options:
            await interaction.followup.send("Nenhum canal de texto apropriado encontrado para postar. Use /configurar_canal_eventos.", ephemeral=True); return

        channel_select_view = utils.SelectChannelView(self.bot, interaction, channel_options)
        channel_select_msg = await interaction.followup.send(
            "Em qual canal postar o evento?", view=channel_select_view, ephemeral=True
        )
        channel_select_view.message = channel_select_msg
        await channel_select_view.wait()

        if channel_select_view.selected_channel_id:
            event_data["channel_id"] = channel_select_view.selected_channel_id
        else:
            return

        created_temp_role_id: Optional[int] = None
        if interaction.guild and 'event_date_obj_for_role' in event_data:
            temp_role = await role_utils.create_event_role(interaction.guild, event_data['title'], event_data['event_date_obj_for_role'])
            if temp_role:
                created_temp_role_id = temp_role.id

        event_id = db.db_create_event(
            guild_id=event_data['guild_id'], channel_id=event_data['channel_id'],
            creator_id=event_data['creator_id'], title=event_data['title'],
            description=event_data.get('description'), event_time_utc=event_data['event_time_utc'],
            activity_type=event_data.get('activity_type', 'Outra Atividade'),
            max_attendees=event_data.get('max_attendees', 6), created_at_utc=event_data['created_at_utc'],
            role_mentions=None, restricted_role_ids=None, 
            temp_role_id=created_temp_role_id
        )

        if not event_id:
            await interaction.followup.send("Falha crítica ao salvar evento no DB.", ephemeral=True)
            if created_temp_role_id and interaction.guild:
                await role_utils.delete_event_role(interaction.guild, created_temp_role_id, "Falha ao salvar evento no DB.")
            return

        target_channel = self.bot.get_channel(event_data['channel_id'])
        if not target_channel or not isinstance(target_channel, discord.TextChannel):
            await interaction.followup.send(f"Canal <#{event_data['channel_id']}> não encontrado. Evento salvo, mas não postado.", ephemeral=True)
            return

        event_details_for_embed = db.db_get_event_details(event_id)
        if not event_details_for_embed:
            await interaction.followup.send("Erro ao buscar detalhes do evento recém-criado para postagem.", ephemeral=True)
            return
        rsvps_initial = {'vou': [], 'nao_vou': [], 'talvez': [], 'lista_espera': []}
        embed = await utils.build_event_embed(event_details_for_embed, rsvps_initial, self.bot)

        try:
            view_to_post = PersistentRsvpView(bot_instance=self.bot)
            event_msg = await target_channel.send(embed=embed, view=view_to_post)
            db.db_update_event_message_id(event_id, event_msg.id)
            await interaction.followup.send(f"🎉 Evento '{event_data['title']}' agendado e postado em {target_channel.mention}!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(f"⚠️ Sem permissão para postar em {target_channel.mention}. Evento salvo, mas não postado.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Erro ao postar: {e}", ephemeral=True)
            print(f"ERRO DETALHADO AO POSTAR EVENTO {event_id} VIA /AGENDAR: {e}")
            import traceback
            traceback.print_exc()

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        print(f"Erro no AgendarEventoModal (on_error): {error}")
        import traceback
        traceback.print_exc()
        if interaction.response.is_done():
            try: await interaction.followup.send("Ocorreu um erro crítico no modal. Verifique o console.", ephemeral=True)
            except: pass
        else:
            try: await interaction.response.send_message("Ocorreu um erro crítico. Verifique o console.", ephemeral=True, delete_after=10)
            except: pass


class SchedulingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="agendar", description="Agenda um novo evento usando um formulário.")
    @app_commands.guild_only()
    async def agendar_evento_slash(self, interaction: discord.Interaction):
        # APLICANDO A VERIFICAÇÃO DE PERMISSÃO
        if not await utils.check_event_permission(interaction, 'criar_eventos'):
            await interaction.response.send_message(
                "Você não tem permissão para criar eventos. Peça a um administrador para lhe conceder a permissão `criar_eventos` através do comando `/permissoes`.", 
                ephemeral=True
            )
            return

        modal = AgendarEventoModal(bot=self.bot)
        await interaction.response.send_modal(modal)

async def setup(bot: commands.Bot):
    await bot.add_cog(SchedulingCog(bot))
