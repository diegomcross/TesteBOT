# cogs/admin_cog.py
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
import database as db
import re

class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # O comando /definir_cargos_gerente foi REMOVIDO daqui.
    # A sua funcionalidade é agora gerida pelo novo comando /permissoes evento.

    @app_commands.command(name="definir_cargos_restritos_padrao", description="Define cargos padrão restritos de interagir com RSVPs.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.describe(
        cargo1="Primeiro cargo restrito padrão (opcional)",
        cargo2="Segundo cargo restrito padrão (opcional)",
        cargo3="Terceiro cargo restrito padrão (opcional)",
        remover_todos="Defina como 'sim' para remover todos os cargos restritos padrão."
    )
    async def definir_cargos_restritos_padrao(self, interaction: discord.Interaction,
                                              cargo1: Optional[discord.Role] = None,
                                              cargo2: Optional[discord.Role] = None,
                                              cargo3: Optional[discord.Role] = None,
                                              remover_todos: Optional[str] = None):
        roles_to_set = []
        if remover_todos and remover_todos.lower() == 'sim':
            roles_to_set = []
        else:
            roles_to_set = [r.id for r in [cargo1, cargo2, cargo3] if r]

        db.db_set_default_restricted_roles(interaction.guild_id, sorted(list(set(roles_to_set))))

        if roles_to_set:
            msg = f"Cargos restritos padrão definidos: {', '.join(f'<@&{rid}>' for rid in roles_to_set)}."
        else:
            msg = "Todos os cargos restritos padrão foram removidos."
        await interaction.response.send_message(msg, ephemeral=True)

    @definir_cargos_restritos_padrao.error
    async def definir_cargos_restritos_padrao_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Você precisa ser administrador para usar este comando.", ephemeral=True)
        else:
            print(f"Erro no comando /definir_cargos_restritos_padrao: {error}")
            await interaction.response.send_message("Ocorreu um erro ao processar o comando.", ephemeral=True)

    @app_commands.command(name="definir_canal_lista", description="Define o canal para o resumo diário de eventos (canal de comandos).")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.describe(canal="O canal de texto para onde o resumo diário será enviado e comandos podem ser usados.")
    async def definir_canal_lista(self, interaction: discord.Interaction, canal: discord.TextChannel):
        db.db_set_digest_channel(interaction.guild_id, canal.id)
        await interaction.response.send_message(f"Canal de resumo diário (e comandos) definido para: {canal.mention}.", ephemeral=True)

    @definir_canal_lista.error
    async def definir_canal_lista_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Você precisa ser administrador para usar este comando.", ephemeral=True)
        else:
            print(f"Erro no comando /definir_canal_lista: {error}")
            await interaction.response.send_message("Ocorreu um erro ao processar o comando.", ephemeral=True)

    @app_commands.command(name="configurar_canal_eventos", description="Configura um canal para posts de eventos e o designa para seleção.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    @app_commands.describe(canal="O canal de texto a ser configurado para posts de eventos.")
    async def configurar_canal_eventos(self, interaction: discord.Interaction, canal: discord.TextChannel):
        if not interaction.guild or not interaction.guild.me:
            await interaction.response.send_message("Erro: O bot não foi encontrado neste servidor.", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if not bot_member.guild_permissions.manage_channels or not bot_member.guild_permissions.manage_permissions:
            await interaction.response.send_message(
                "Erro: Para executar este comando, o **BOT** precisa das permissões de servidor 'Gerir Canais' e 'Gerir Permissões'. Por favor, adicione-as ao cargo do bot.",
                ephemeral=True
            )
            return

        bot_perms = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, embed_links=True,
            attach_files=True, manage_messages=True, read_message_history=True,
            mention_everyone=True, use_external_emojis=True
        )
        everyone_role = interaction.guild.default_role
        everyone_perms = discord.PermissionOverwrite(
            send_messages=False, add_reactions=True,
            read_message_history=True, view_channel=True
        )

        try:
            await canal.set_permissions(bot_member, overwrite=bot_perms, reason="Configuração do bot para canal de eventos")
            await canal.set_permissions(everyone_role, overwrite=everyone_perms, reason="Configuração do canal de eventos para apenas leitura por membros")

            db.db_add_designated_event_channel(interaction.guild_id, canal.id)

            await interaction.response.send_message(
                f"Permissões configuradas em {canal.mention} e o canal foi designado para postagem de eventos.\n"
                f"- O Bot pode postar e gerenciar eventos.\n"
                f"- Membros comuns (`@everyone`) **não podem** enviar mensagens neste canal.",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                f"Não tenho permissão para alterar as configurações do canal {canal.mention}. "
                "Isto geralmente acontece se o cargo do bot estiver abaixo de outros cargos que ele está a tentar gerir. "
                "Verifique a hierarquia de cargos e as permissões do bot.",
                ephemeral=True
            )
        except Exception as e:
            print(f"Erro ao configurar permissões do canal de eventos {canal.id}: {e}")
            await interaction.response.send_message(f"Ocorreu um erro ao configurar {canal.mention}.", ephemeral=True)

    @configurar_canal_eventos.error
    async def configurar_canal_eventos_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Você precisa da permissão 'Gerir Canais' para usar este comando.", ephemeral=True)
        else:
            print(f"Erro /configurar_canal_eventos: {error}")
            await interaction.response.send_message("Erro ao processar comando.", ephemeral=True)

    @app_commands.command(name="remover_canal_evento_cfg", description="Remove um canal da lista de postagem de eventos.")
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.guild_only()
    @app_commands.describe(canal="O canal de texto a ser removido da designação de eventos.")
    async def remover_configuracao_canal_eventos(self, interaction: discord.Interaction, canal: discord.TextChannel):
        if not interaction.guild_id:
            await interaction.response.send_message("Comando apenas para servidores.", ephemeral=True)
            return

        was_designated = db.db_is_designated_event_channel(interaction.guild_id, canal.id)
        if not was_designated:
            await interaction.response.send_message(f"O canal {canal.mention} já não estava configurado como um canal de postagem de eventos.", ephemeral=True)
            return

        try:
            db.db_remove_designated_event_channel(interaction.guild_id, canal.id)
            await interaction.response.send_message(
                f"O canal {canal.mention} foi removido da lista de canais designados para postagem de eventos. "
                "As permissões do canal **não** foram revertidas automaticamente.",
                ephemeral=True
            )
        except Exception as e:
            print(f"Erro ao remover designação do canal de eventos {canal.id}: {e}")
            await interaction.response.send_message(f"Ocorreu um erro ao tentar remover a designação de {canal.mention}.", ephemeral=True)

    @remover_configuracao_canal_eventos.error
    async def remover_configuracao_canal_eventos_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Você precisa da permissão 'Gerenciar Canais' para usar este comando.", ephemeral=True)
        else:
            print(f"Erro no comando /remover_canal_evento_cfg: {error}")
            await interaction.response.send_message("Ocorreu um erro ao processar o comando.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
