# cogs/listeners_cog.py
import discord
from discord import app_commands
from discord.ext import commands
import traceback 

# Imports customizados
import database as db
import utils
import role_utils
from cogs.event_cog import PersistentRsvpView # Para recriar a view ao editar o embed

class ListenersCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """
        Este evento é acionado quando um membro sai ou é removido do servidor.
        Ele limpa todos os RSVPs ativos do membro.
        """
        print(f"INFO_LISTENERS: Membro {member.display_name} (ID: {member.id}) saiu/foi removido da guild {member.guild.id}. Verificando RSVPs ativos...")

        # 1. Obter todos os eventos ativos nos quais o membro estava inscrito nesta guilda
        active_event_ids = db.db_get_user_active_rsvps_in_guild(member.id, member.guild.id)
        
        if not active_event_ids:
            print(f"INFO_LISTENERS: Nenhum RSVP ativo encontrado para o membro que saiu {member.id}.")
            return

        print(f"INFO_LISTENERS: Membro {member.id} tem RSVPs em {len(active_event_ids)} evento(s) ativo(s). Removendo...")

        for event_id in active_event_ids:
            # Obter detalhes do evento para atualizar o embed mais tarde
            event_details = db.db_get_event_details(event_id)
            if not event_details:
                continue

            # Remover o RSVP do membro do banco de dados
            db.db_remove_rsvp(event_id, member.id)
            print(f"DEBUG_LISTENERS: RSVP do membro {member.id} removido do evento {event_id}.")
            
            # Verificar se é necessário promover alguém da lista de espera
            rsvps_after_removal = db.db_get_rsvps_for_event(event_id)
            max_attendees = event_details['max_attendees']
            
            if len(rsvps_after_removal.get('vou', [])) < max_attendees and rsvps_after_removal.get('lista_espera'):
                promoted_user_id = rsvps_after_removal['lista_espera'][0]
                db.db_add_or_update_rsvp(event_id, promoted_user_id, 'vou')
                print(f"DEBUG_LISTENERS: Usuário {promoted_user_id} promovido para 'Vou' no evento {event_id} após a saída de {member.id}.")

                # Adicionar o membro promovido ao cargo temporário, se houver
                promoted_member = member.guild.get_member(promoted_user_id)
                temp_role_id = event_details['temp_role_id']
                if promoted_member and temp_role_id:
                    temp_role = member.guild.get_role(temp_role_id)
                    if temp_role:
                        await role_utils.manage_member_event_role(promoted_member, temp_role, "add", event_id)

            # Atualizar a mensagem do evento para refletir a mudança
            if event_details['channel_id'] and event_details['message_id']:
                target_channel = self.bot.get_channel(event_details['channel_id'])
                if target_channel and isinstance(target_channel, discord.TextChannel):
                    try:
                        msg_to_edit = await target_channel.fetch_message(event_details['message_id'])
                        
                        # Re-buscar dados atualizados para construir o embed
                        updated_event_details = db.db_get_event_details(event_id)
                        updated_rsvps = db.db_get_rsvps_for_event(event_id)

                        if updated_event_details:
                            new_embed = await utils.build_event_embed(updated_event_details, updated_rsvps, self.bot)
                            new_view = PersistentRsvpView(bot_instance=self.bot)
                            await msg_to_edit.edit(embed=new_embed, view=new_view)
                            print(f"DEBUG_LISTENERS: Embed do evento {event_id} atualizado devido à saída do membro {member.id}.")
                    except (discord.NotFound, discord.Forbidden) as e:
                        print(f"WARN_LISTENERS: Não foi possível atualizar o embed do evento {event_id} após a saída do membro: {e}")
                    except Exception as e:
                        print(f"ERRO_LISTENERS: Erro inesperado ao atualizar embed do evento {event_id}: {e}")
            
    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Trata erros para comandos de prefixo tradicionais."""
        if isinstance(error, commands.CommandNotFound):
            return 
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("Você não tem permissão para usar este comando (prefixo).", delete_after=10)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Falta um argumento necessário para este comando: {error.param.name}.", delete_after=10)
        else:
            print(f"Erro em comando de prefixo não tratado: {ctx.command} - {error}")
            await ctx.send("Ocorreu um erro ao processar o comando (prefixo).", delete_after=10)

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Trata erros para comandos de barra (app_commands)."""
        command_name = interaction.command.name if interaction.command else "N/A"
        print(f"Erro em AppCommand: Comando '{command_name}' invocado por '{interaction.user}' (ID: {interaction.user.id})")
        print(f"Tipo do Erro: {type(error).__name__}, Erro: {error}")

        if isinstance(error, app_commands.CommandInvokeError):
            print("--- Erro Original (CommandInvokeError) ---")
            traceback.print_exception(type(error.original), error.original, error.original.__traceback__)
            print("-----------------------------------------")
            original_error = error.original
            user_message = f"Ocorreu um erro interno ao executar o comando: {type(original_error).__name__}. Se o problema persistir, por favor, contate um administrador."
        elif isinstance(error, app_commands.CheckFailure) or isinstance(error, app_commands.MissingPermissions):
            user_message = "Você não tem permissão para usar este comando."
        elif isinstance(error, app_commands.CommandNotFound):
            user_message = "Comando não encontrado. Isto é inesperado para comandos de barra."
        elif isinstance(error, app_commands.TransformerError):
            user_message = f"Um argumento inválido foi fornecido: {error.value}. Por favor, verifique o tipo e valor do argumento."
        elif isinstance(error, app_commands.CommandOnCooldown):
            user_message = f"Este comando está em cooldown. Por favor, tente novamente em {error.retry_after:.2f} segundos."
        else:
            user_message = "Ocorreu um erro desconhecido ao processar este comando. Tente novamente mais tarde."
            print("--- Erro AppCommand Não Tratado Especificamente ---")
            traceback.print_exc()
            print("------------------------------------------------")


        try:
            if interaction.response.is_done():
                await interaction.followup.send(user_message, ephemeral=True)
            else:
                await interaction.response.send_message(user_message, ephemeral=True)
        except discord.NotFound:
            print("DEBUG: Interação não encontrada ao tentar enviar mensagem de erro (on_app_command_error).")
        except Exception as e_resp_err:
            print(f"DEBUG: Erro adicional ao tentar enviar mensagem de erro para interação: {e_resp_err}")


async def setup(bot: commands.Bot):
    await bot.add_cog(ListenersCog(bot))
