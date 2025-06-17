# cogs/permissions_cog.py
import discord
from discord import app_commands
from discord.ext import commands
from typing import Literal, Dict, List

import database as db

# Definir as permissões disponíveis para que sejam consistentes em todo o cog
AVAILABLE_PERMISSIONS = Literal[
    'criar_eventos', 
    'editar_qualquer_evento', 
    'apagar_qualquer_evento', 
    'gerir_rsvp_qualquer_evento'
]

PERMISSION_DESCRIPTIONS = {
    'criar_eventos': 'Permite usar /criar_evento e /agendar.',
    'editar_qualquer_evento': 'Permite editar eventos de outros membros.',
    'apagar_qualquer_evento': 'Permite apagar eventos de outros membros.',
    'gerir_rsvp_qualquer_evento': 'Permite usar /gerenciar_rsvp para qualquer evento.'
}

class PermissionsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Criar um grupo de comandos para /permissoes
    permissions_group = app_commands.Group(
        name="permissoes", 
        description="Gere as permissões do bot para cargos específicos.",
        default_permissions=discord.Permissions(administrator=True), # Apenas administradores por padrão
        guild_only=True
    )

    # Criar um sub-grupo para /permissoes evento
    event_permissions_group = app_commands.Group(
        parent=permissions_group,
        name="evento",
        description="Gere as permissões relacionadas à criação e gestão de eventos."
    )

    @event_permissions_group.command(name="adicionar", description="Adiciona uma permissão de evento a um cargo.")
    @app_commands.describe(
        cargo="O cargo que receberá a permissão.",
        permissao="A permissão a ser concedida."
    )
    async def add_permission(self, interaction: discord.Interaction, cargo: discord.Role, permissao: AVAILABLE_PERMISSIONS):
        try:
            db.db_add_event_permission(interaction.guild_id, cargo.id, permissao)
            await interaction.response.send_message(
                f"✅ Permissão `{permissao}` adicionada com sucesso ao cargo **{cargo.name}**.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Ocorreu um erro ao tentar adicionar a permissão: {e}",
                ephemeral=True
            )
            print(f"Erro ao adicionar permissão: {e}")

    @event_permissions_group.command(name="remover", description="Remove uma permissão de evento de um cargo.")
    @app_commands.describe(
        cargo="O cargo do qual a permissão será removida.",
        permissao="A permissão a ser revogada."
    )
    async def remove_permission(self, interaction: discord.Interaction, cargo: discord.Role, permissao: AVAILABLE_PERMISSIONS):
        try:
            db.db_remove_event_permission(interaction.guild_id, cargo.id, permissao)
            await interaction.response.send_message(
                f"🗑️ Permissão `{permissao}` removida com sucesso do cargo **{cargo.name}**.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Ocorreu um erro ao tentar remover a permissão: {e}",
                ephemeral=True
            )
            print(f"Erro ao remover permissão: {e}")

    @event_permissions_group.command(name="ver", description="Mostra todas as permissões de evento configuradas para os cargos.")
    async def view_permissions(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("Comando apenas para servidores.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        all_perms = db.db_get_all_event_permissions(interaction.guild_id)

        if not all_perms:
            await interaction.followup.send("Nenhuma permissão de evento personalizada foi configurada neste servidor.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📋 Permissões de Evento Configuradas",
            description="Lista de cargos e as permissões de gestão de eventos que eles possuem.",
            color=discord.Color.blue()
        )

        for role_id, perms_list in all_perms.items():
            role = interaction.guild.get_role(role_id)
            role_name = role.name if role else f"Cargo Apagado (ID: {role_id})"

            # Formatar a lista de permissões para exibição
            perm_descriptions = [f"- `{p}`: {PERMISSION_DESCRIPTIONS.get(p, 'Descrição não disponível.')}" for p in perms_list]
            value_text = "\n".join(perm_descriptions)

            embed.add_field(name=f"👑 Cargo: @{role_name}", value=value_text, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PermissionsCog(bot))
