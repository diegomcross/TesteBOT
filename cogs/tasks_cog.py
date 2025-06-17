# cogs/tasks_cog.py
import discord
from discord.ext import commands, tasks
import asyncio 
import datetime
import pytz
import database as db
import utils 
import role_utils 
from constants import BRAZIL_TZ, DIGEST_TIMES_BRT # Importar a nova lista de horários
from utils import ConfirmAttendanceView 
from cogs.event_cog import PersistentRsvpView 

class TasksCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # A lógica do self.digest_time_brt não é mais necessária aqui

        self.delete_canceled_events_messages_task.start()
        self.event_reminder_task.start() 
        self.confirmation_reminder_task.start() 
        self.daily_event_digest_task.start()
        self.cleanup_completed_events_task.start()

    def cog_unload(self):
        self.delete_canceled_events_messages_task.cancel()
        self.event_reminder_task.cancel()
        self.confirmation_reminder_task.cancel()
        self.daily_event_digest_task.cancel()
        self.cleanup_completed_events_task.cancel()

    @tasks.loop(minutes=5.0)
    async def delete_canceled_events_messages_task(self):
        # print("DEBUG_TASKS: Tarefa 'delete_canceled_events_messages_task' rodando...")
        events_to_process = db.db_get_events_to_delete_message()
        if not events_to_process: return

        for event_row in events_to_process:
            try:
                channel = self.bot.get_channel(event_row['channel_id']) or await self.bot.fetch_channel(event_row['channel_id'])
                if not (channel and isinstance(channel, discord.TextChannel)):
                    db.db_clear_message_id_and_update_status_after_delete(event_row['event_id'], event_row['status']); continue
                if event_row['message_id']:
                    msg_to_del = await channel.fetch_message(event_row['message_id']); await msg_to_del.delete()
                db.db_clear_message_id_and_update_status_after_delete(event_row['event_id'], event_row['status'])
            except discord.NotFound:
                print(f"DEBUG_TASKS: Mensagem {event_row['message_id']} para evento {event_row['event_id']} não encontrada para deleção (já deletada?).")
                db.db_clear_message_id_and_update_status_after_delete(event_row['event_id'], event_row['status'])
            except Exception as e: print(f"DEBUG_TASKS: Erro ao deletar msg do evento {event_row['event_id']}: {e}")

    @delete_canceled_events_messages_task.before_loop
    async def before_delete_canceled_task(self):
        await self.bot.wait_until_ready(); print("Tarefa de deleção de mensagens agendadas pronta.")

    @tasks.loop(minutes=1.0)
    async def event_reminder_task(self): # Lembrete de ~15 minutos antes
        upcoming_events = db.db_get_upcoming_events_for_reminder()
        if not upcoming_events: return

        for event_row in upcoming_events:
            event_id, event_title = event_row['event_id'], event_row['title']
            temp_role_id = event_row['temp_role_id']
            guild = self.bot.get_guild(event_row['guild_id'])
            mention_target = ""

            if temp_role_id and guild:
                temp_role = guild.get_role(temp_role_id)
                if temp_role: mention_target = temp_role.mention

            if not mention_target and not db.db_get_rsvps_for_event(event_id).get('vou'):
                db.db_mark_reminder_sent(event_id, reminder_type="standard"); continue

            link_to_event = f"https://discord.com/channels/{event_row['guild_id']}/{event_row['channel_id']}/{event_row['message_id']}" if all([event_row['guild_id'], event_row['channel_id'], event_row['message_id']]) else "Link indisponível"
            message_content_base = f"🔔 **Lembrete!** O evento **'{event_title}'** começa em aproximadamente 15 minutos!\nLink: {link_to_event}"

            if mention_target:
                event_channel = self.bot.get_channel(event_row['channel_id'])
                if event_channel and isinstance(event_channel, discord.TextChannel):
                    try: await event_channel.send(f"{mention_target} {message_content_base}")
                    except Exception as e: print(f"ERRO_TASKS: Falha ao enviar lembrete para canal {event_row['channel_id']} evento {event_id}: {e}")
                else: print(f"WARN_TASKS: Canal do evento {event_row['channel_id']} não encontrado para lembrete {event_id}.")
            else: 
                rsvps = db.db_get_rsvps_for_event(event_id)
                attendees_ids = rsvps.get('vou', [])
                for user_id in attendees_ids:
                    try:
                        user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                        if user: await user.send(message_content_base)
                    except Exception as e: print(f"DEBUG_TASKS: Erro ao enviar DM de lembrete para {user_id}: {e}")
                    await asyncio.sleep(10) # Pausa de 10 segundos entre cada DM

            db.db_mark_reminder_sent(event_id, reminder_type="standard")

    @event_reminder_task.before_loop
    async def before_event_reminder_task(self):
        await self.bot.wait_until_ready(); print("Tarefa de lembrete de eventos (~15min) pronta.")

    @tasks.loop(minutes=1.0)
    async def confirmation_reminder_task(self):
        # print("DEBUG_TASKS: Verificando eventos para lembrete de confirmação de 1 hora...")
        events_for_confirmation = db.db_get_events_for_confirmation_reminder()
        if not events_for_confirmation: return

        print(f"DEBUG_TASKS: {len(events_for_confirmation)} evento(s) encontrado(s) para lembrete de confirmação de 1h.")
        for event_row in events_for_confirmation:
            event_id, event_title, guild_id, creator_id = event_row['event_id'], event_row['title'], event_row['guild_id'], event_row['creator_id']
            guild = self.bot.get_guild(guild_id)
            if not guild:
                print(f"WARN_TASKS: Guilda {guild_id} não encontrada para evento {event_id}. Pulando lembrete."); db.db_mark_reminder_sent(event_id, reminder_type="confirmation"); continue

            rsvps = db.db_get_rsvps_for_event(event_id)
            attendees_vou = rsvps.get('vou', [])
            if not attendees_vou:
                print(f"INFO_TASKS: Evento {event_id} ('{event_title}') sem 'Vou'. Pulando lembrete."); db.db_mark_reminder_sent(event_id, reminder_type="confirmation"); continue

            print(f"DEBUG_TASKS: Enviando lembretes de confirmação para {len(attendees_vou)} do evento {event_id} ('{event_title}').")
            at_least_one_dm_sent = False
            for user_id in attendees_vou:
                if user_id == creator_id:
                    print(f"INFO_TASKS: Pulando lembrete de confirmação para o organizador {user_id} do evento {event_id}.")
                    continue 

                member = guild.get_member(user_id)
                if not member: print(f"WARN_TASKS: Membro {user_id} não encontrado na guilda {guild_id} para lembrete evento {event_id}."); continue
                try:
                    dm_channel = await member.create_dm()
                    confirmation_view = ConfirmAttendanceView(user_id, event_id, self.bot)
                    reminder_msg_content = f"⏳ Lembrete: Evento **'{event_title}'** em ~1 hora. Ainda pretende comparecer?"
                    sent_msg = await dm_channel.send(reminder_msg_content, view=confirmation_view)
                    confirmation_view.message = sent_msg 
                    at_least_one_dm_sent = True
                    await confirmation_view.wait()

                    if confirmation_view.confirmed_attendance is False:
                        print(f"INFO_TASKS: Usuário {user_id} ({member.display_name}) removeu RSVP para evento {event_id} via lembrete.")
                        db.db_add_or_update_rsvp(event_id, user_id, "nao_vou")
                        temp_role_id = event_row['temp_role_id']
                        if temp_role_id and guild:
                            temp_role = guild.get_role(temp_role_id)
                            if temp_role: await role_utils.manage_member_event_role(member, temp_role, "remove", event_id)

                        target_channel_id = event_row['channel_id']
                        message_id_to_update = event_row['message_id']
                        event_channel_obj = self.bot.get_channel(target_channel_id)

                        if event_channel_obj and isinstance(event_channel_obj, discord.TextChannel) and message_id_to_update:
                            try:
                                msg_to_edit = await event_channel_obj.fetch_message(message_id_to_update)
                                updated_event_details_fetch = db.db_get_event_details(event_id) 
                                updated_rsvps_fetch = db.db_get_rsvps_for_event(event_id)
                                if updated_event_details_fetch:
                                    new_embed = await utils.build_event_embed(updated_event_details_fetch, updated_rsvps_fetch, self.bot)
                                    new_view_instance = PersistentRsvpView(bot_instance=self.bot) 
                                    await msg_to_edit.edit(embed=new_embed, view=new_view_instance)
                                    print(f"DEBUG_TASKS: Embed do evento {event_id} atualizado após remoção de RSVP via lembrete.")
                                else: print(f"WARN_TASKS: Não buscou detalhes atualizados do evento {event_id} para embed.")
                            except discord.NotFound: print(f"WARN_TASKS: Msg original do evento {event_id} (ID: {message_id_to_update}) no canal {target_channel_id} não encontrada para atualizar embed.")
                            except discord.Forbidden: print(f"WARN_TASKS: Sem permissão para editar msg do evento {event_id} no canal {target_channel_id}.")
                            except Exception as e_embed_upd: print(f"ERRO_TASKS: Erro ao atualizar embed do evento {event_id} via lembrete: {e_embed_upd}")
                        else: 
                            print(f"WARN_TASKS: Canal do evento {target_channel_id} não encontrado/inválido ou message_id ausente para evento {event_id} ao tentar atualizar embed.")
                    elif confirmation_view.confirmed_attendance is True:
                        print(f"INFO_TASKS: Usuário {user_id} ({member.display_name}) confirmou presença para evento {event_id} via lembrete.")
                except discord.Forbidden: print(f"WARN_TASKS: Não enviou DM de lembrete de confirmação para {user_id} ({member.display_name}) (evento {event_id}).")
                except Exception as e: print(f"ERRO_TASKS: Erro ao enviar/processar lembrete de confirmação para {user_id} ({member.display_name}) (evento {event_id}): {e}")

                await asyncio.sleep(10)

            if at_least_one_dm_sent:
                db.db_mark_reminder_sent(event_id, reminder_type="confirmation")
            else:
                print(f"INFO_TASKS: Nenhuma DM de confirmação foi efetivamente enviada para o evento {event_id}, mas marcando como 'enviado' para evitar reenvios.")
                db.db_mark_reminder_sent(event_id, reminder_type="confirmation")

    @confirmation_reminder_task.before_loop
    async def before_confirmation_reminder_task(self):
        await self.bot.wait_until_ready(); print("Tarefa de lembrete de confirmação de presença (~1h) pronta.")

    # --- TAREFA DO RESUMO DIÁRIO ATUALIZADA ---
    @tasks.loop(time=DIGEST_TIMES_BRT) # Agora usa a lista de horários
    async def daily_event_digest_task(self):
        now_brt_display = utils.get_brazil_now().strftime('%H:%M:%S %Z')
        print(f"DEBUG: Tarefa 'daily_event_digest_task' rodando às {now_brt_display}...")
        for guild in self.bot.guilds:
            digest_channel_id = db.db_get_digest_channel(guild.id)
            if digest_channel_id:
                channel = self.bot.get_channel(digest_channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    print(f"DEBUG: Gerando digest de eventos para o servidor '{guild.name}' no canal '{channel.name}'")
                    try:
                        content = await utils.generate_event_list_message_content(guild.id, 3, self.bot)
                        header = f"**Eventos Agendados (Próximos 3 Dias):**\n"
                        full_message = header + content; max_chars = 1980
                        if len(full_message) > max_chars:
                            current_part = header; first_part = True
                            for line in content.splitlines():
                                if len(current_part) + len(line) + 1 > max_chars:
                                    await channel.send(current_part); current_part = "" if first_part else "(Continuação)\n"; first_part = False
                                current_part += line + "\n"
                            if current_part.strip(): await channel.send(current_part)
                        else: await channel.send(full_message)
                        print(f"DEBUG: Digest enviado para '{guild.name}'.")
                    except Exception as e: print(f"DEBUG: Erro ao enviar digest para o servidor {guild.id} ({guild.name}): {e}")
                else: print(f"DEBUG: Canal de digest ({digest_channel_id}) não encontrado ou inválido no servidor '{guild.name}'.")

    @daily_event_digest_task.before_loop
    async def before_daily_digest_task(self):
        await self.bot.wait_until_ready()
        digest_times_str = ", ".join([t.strftime('%H:%M') for t in DIGEST_TIMES_BRT])
        print(f"Tarefa de Digest Diário pronta (agendada para {digest_times_str} BRT).")

    @tasks.loop(hours=1.0)
    async def cleanup_completed_events_task(self):
        # print("DEBUG: Tarefa 'cleanup_completed_events_task' rodando...")
        events_to_cleanup = db.db_get_events_for_cleanup()
        if not events_to_cleanup: return

        for event_row in events_to_cleanup:
            event_id, event_title, channel_id, message_id, guild_id, temp_role_id = event_row['event_id'], event_row['title'], event_row['channel_id'], event_row['message_id'], event_row['guild_id'], event_row['temp_role_id']
            print(f"DEBUG: Evento {event_id} ('{event_title}') encontrado para marcar como concluído.")
            if channel_id and message_id:
                try:
                    channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                    if channel and isinstance(channel, discord.TextChannel):
                        msg = await channel.fetch_message(message_id)
                        completed_embed = discord.Embed(title=f"[CONCLUÍDO] {event_title}", description="Este evento já foi finalizado.", color=discord.Color.light_grey())
                        dt_utc_obj_completed = datetime.datetime.fromisoformat(event_row['event_time_utc'].replace('Z', '+00:00'))
                        completed_embed.add_field(name="🗓️ Data Original do Evento", value=f"<t:{int(dt_utc_obj_completed.timestamp())}:F>", inline=False)
                        await msg.edit(content=f"**EVENTO CONCLUÍDO**", embed=completed_embed, view=None)
                        print(f"DEBUG: Mensagem do evento {event_id} ('{event_title}') editada para o estado [CONCLUÍDO].")
                except discord.NotFound: print(f"DEBUG: Mensagem do evento {event_id} ('{event_title}') não encontrada.")
                except discord.Forbidden: print(f"DEBUG: Sem permissão para editar a mensagem do evento {event_id} ('{event_title}').")
                except Exception as e: print(f"DEBUG: Erro ao editar a mensagem do evento {event_id} ('{event_title}') para concluído: {e}")

            role_deleted_msg_part = ""
            if temp_role_id and guild_id:
                guild = self.bot.get_guild(guild_id)
                if guild:
                    role_deleted = await role_utils.delete_event_role(guild, temp_role_id, f"Evento '{event_title}' (ID: {event_id}) concluído.")
                    if role_deleted: role_deleted_msg_part = " Cargo temporário deletado."
                    else: role_deleted_msg_part = " Falha ao deletar cargo temporário (ver logs)."
                else: print(f"WARN_TASKS: Guilda {guild_id} não encontrada para deletar cargo do evento {event_id}."); role_deleted_msg_part = " Guilda não encontrada para deletar cargo."

            delete_at_utc = (datetime.datetime.now(pytz.utc) + datetime.timedelta(hours=24)).isoformat()
            db.db_update_event_status(event_id, 'concluido', delete_after_utc=delete_at_utc)
            db.db_update_event_details(event_id=event_id, temp_role_id=None) 
            print(f"DEBUG_TASKS: Evento {event_id} ('{event_title}') marcado como 'concluido'. Deleção msg: {delete_at_utc}.{role_deleted_msg_part}")

    @cleanup_completed_events_task.before_loop
    async def before_cleanup_completed_events_task(self):
        await self.bot.wait_until_ready(); print("Tarefa de Cleanup de Eventos Concluídos pronta.")

async def setup(bot: commands.Bot):
    await bot.add_cog(TasksCog(bot))
