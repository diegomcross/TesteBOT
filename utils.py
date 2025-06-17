# utils.py
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import datetime
import pytz
from typing import Optional, List, Tuple, Dict, Set
import sqlite3
from difflib import SequenceMatcher

from constants import (
    BRAZIL_TZ, BRAZIL_TZ_STR, DIAS_SEMANA_PT_FULL, DIAS_SEMANA_PT_SHORT, MESES_PT,
    ALL_ACTIVITIES_PT, RAID_INFO_PT, MASMORRA_INFO_PT, PVP_ACTIVITY_INFO_PT,
    SIMILARITY_THRESHOLD
)
import database as db

# --- Novas Funções de Verificação de Permissão ---

async def check_event_permission(interaction: discord.Interaction, permission: str) -> bool:
    """
    Verifica se um utilizador tem uma permissão específica para eventos.
    Administradores do servidor sempre têm permissão.
    Retorna True se tiver permissão, False caso contrário.
    """
    # Garante que estamos num servidor e que o utilizador é um membro
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False

    # Administradores têm acesso a tudo
    if interaction.user.guild_permissions.administrator:
        return True

    # Obtém os IDs dos cargos do utilizador
    user_roles_ids: Set[int] = {role.id for role in interaction.user.roles}

    # Verifica a permissão na base de dados
    has_perm = db.db_check_user_permission(interaction.guild_id, user_roles_ids, permission)

    return has_perm

async def is_user_event_manager(interaction: discord.Interaction, event_creator_id: int, permission_to_check: str) -> bool:
    """
    Verifica se um utilizador pode gerir um evento específico (editar, apagar, etc.).
    Um utilizador pode gerir se:
    1. Ele é o criador do evento.
    2. Ele tem a permissão específica (ex: 'editar_qualquer_evento') OU é um administrador do servidor.
    """
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False

    member: discord.Member = interaction.user

    # O criador do evento sempre pode gerir o seu próprio evento
    if member.id == event_creator_id:
        return True

    # Se não for o criador, verifica se tem a permissão para gerir eventos de outros
    return await check_event_permission(interaction, permission_to_check)


# --- Views ---
class ConfirmAttendanceView(discord.ui.View):
    def __init__(self, original_interaction_user_id: int, event_id: int, bot_instance: commands.Bot):
        super().__init__(timeout=3600) 
        self.bot = bot_instance
        self.user_id = original_interaction_user_id
        self.event_id = event_id
        self.confirmed_attendance: Optional[bool] = None
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Este lembrete não é para você.", ephemeral=True)
            return False
        return True

    async def disable_all_items(self, interaction: Optional[discord.Interaction] = None, new_content: Optional[str] = None):
        for item in self.children:
            if hasattr(item, 'disabled'): item.disabled = True
        if self.message:
            try:
                content_to_set = new_content if new_content else self.message.content
                await self.message.edit(content=content_to_set, view=self)
            except discord.HTTPException as e: print(f"WARN_UTILS: Falha ao editar msg ConfirmAttendanceView (ID: {self.message.id}): {e}")
            except AttributeError: print(f"WARN_UTILS: self.message não definido para ConfirmAttendanceView.")
        self.stop()

    @discord.ui.button(label="Sim, vou comparecer!", style=discord.ButtonStyle.success, custom_id="confirm_attendance_yes")
    async def confirm_yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed_attendance = True
        await interaction.response.send_message("Obrigado por confirmar sua presença! ✅", ephemeral=True)
        await self.disable_all_items(new_content=f"Lembrete respondido: Presença confirmada para o evento ID {self.event_id}.")

    @discord.ui.button(label="Não poderei comparecer", style=discord.ButtonStyle.danger, custom_id="confirm_attendance_no")
    async def confirm_no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed_attendance = False
        await interaction.response.send_message("Entendido. Seu RSVP será removido do evento. ❌", ephemeral=True)
        await self.disable_all_items(new_content=f"Lembrete respondido: RSVP removido para o evento ID {self.event_id}.")
        self.stop()

    async def on_timeout(self):
        self.confirmed_attendance = None
        print(f"INFO_UTILS: ConfirmAttendanceView para evento {self.event_id}, usuário {self.user_id} timed out.")
        await self.disable_all_items(new_content=f"Lembrete para evento ID {self.event_id} expirou sem resposta.")
        self.stop()

class ConfirmActivityView(discord.ui.View):
    def __init__(self, original_interaction: discord.Interaction, detected_title: str, detected_type: Optional[str], detected_spots: Optional[int]):
        super().__init__(timeout=180.0)
        self.original_interaction = original_interaction 
        self.confirmed: Optional[bool] = None 
        self.message: Optional[discord.Message] = None
        self.detected_title = detected_title
        self.detected_type = detected_type
        self.detected_spots = detected_spots
        self.confirmation_message_content = f"Entendi como: **{detected_title}**"
        if detected_type and detected_spots:
            self.confirmation_message_content += f" (Tipo: {detected_type}, Vagas: {detected_spots}p)."
        else: self.confirmation_message_content += "."
        self.confirmation_message_content += "\nIsso está correto?"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.original_interaction.user.id:
            await interaction.response.send_message("Você não pode interagir com esta seleção.", ephemeral=True)
            return False
        return True

    async def disable_all_items(self, interaction: Optional[discord.Interaction] = None):
        for item in self.children:
            if hasattr(item, 'disabled'): item.disabled = True
        if interaction and not interaction.response.is_done():
            try: await interaction.response.edit_message(view=self)
            except discord.HTTPException: pass 
        elif self.message:
            try: await self.message.edit(view=self)
            except discord.HTTPException: pass

    @discord.ui.button(label="Sim, está correto", style=discord.ButtonStyle.success, custom_id="confirm_activity_yes")
    async def confirm_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True; await self.disable_all_items(interaction); self.stop()

    @discord.ui.button(label="Não, digitar nome/tipo", style=discord.ButtonStyle.danger, custom_id="confirm_activity_no")
    async def confirm_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False; await self.disable_all_items(interaction); self.stop()

    async def on_timeout(self):
        self.confirmed = None; await self.disable_all_items()
        if self.message: 
            try: await self.message.edit(content=self.confirmation_message_content + "\n*Tempo esgotado para confirmação.*", view=self)
            except discord.HTTPException: pass
        self.stop()


class SelectActivityDetailsView(discord.ui.View):
    def __init__(self, bot: commands.Bot, original_interaction: discord.Interaction):
        super().__init__(timeout=180.0)
        self.bot = bot; self.original_interaction = original_interaction
        self.selected_activity_type: Optional[str] = None
        self.selected_max_attendees: Optional[int] = None
        self.message: Optional[discord.Message] = None
        self.activity_options = {
            "act_type_raid": {"label": "Incursão (6p)", "value": ("Incursão", 6), "style": discord.ButtonStyle.primary},
            "act_type_dungeon": {"label": "Masmorra (3p)", "value": ("Masmorra", 3), "style": discord.ButtonStyle.primary},
            "act_type_pvp_osiris": {"label": "PvP - Osíris (3p)", "value": ("PvP - Desafios de Osíris", 3), "style": discord.ButtonStyle.red},
            "act_type_pvp_other": {"label": "Outro PvP", "value": ("PvP", None), "style": discord.ButtonStyle.secondary},
            "act_type_other": {"label": "Outra Atividade", "value": ("Outra Atividade", None), "style": discord.ButtonStyle.secondary}
        }
        for custom_id, details in self.activity_options.items():
            button = discord.ui.Button(label=details["label"], custom_id=custom_id, style=details["style"])
            button.callback = self.button_callback
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.original_interaction.user.id:
            await interaction.response.send_message("Você não pode interagir.", ephemeral=True); return False
        return True

    async def disable_all_items(self, interaction_for_edit: Optional[discord.Interaction] = None):
        for item in self.children:
            if hasattr(item, 'disabled'): item.disabled = True
        if interaction_for_edit and not interaction_for_edit.response.is_done():
             try: await interaction_for_edit.response.edit_message(view=self)
             except discord.HTTPException: pass
        elif self.message:
            try: await self.message.edit(view=self)
            except discord.HTTPException: pass

    async def button_callback(self, interaction: discord.Interaction):
        custom_id = interaction.data["custom_id"] # type: ignore
        selected_option = self.activity_options.get(custom_id)
        if not selected_option:
            await interaction.response.send_message("Opção inválida.", ephemeral=True); self.stop(); return
        self.selected_activity_type, self.selected_max_attendees = selected_option["value"]

        msg_content = f"Tipo selecionado: {self.selected_activity_type}."
        if self.message:
            try: await self.message.edit(content=msg_content, view=None)
            except discord.HTTPException: await interaction.response.edit_message(content=msg_content, view=None)
        else: await interaction.response.edit_message(content=msg_content, view=None)

        if self.selected_max_attendees is None:
            await self.original_interaction.followup.send("Qual o nº máximo de participantes? (1-100)", ephemeral=True)
            try:
                msg_resp = await self.bot.wait_for("message", timeout=120.0,
                    check=lambda m: m.author.id == self.original_interaction.user.id and \
                                    m.channel.id == self.original_interaction.channel_id and m.content.isdigit())
                num_spots = int(msg_resp.content)
                self.selected_max_attendees = 6 if not (1 <= num_spots <= 100) else num_spots
                if self.selected_max_attendees == 6 and num_spots != 6 : await self.original_interaction.followup.send("Nº inválido. Usando 6.", ephemeral=True)
                try: await msg_resp.delete()
                except: pass
            except asyncio.TimeoutError:
                await self.original_interaction.followup.send("Tempo esgotado. Usando 6 vagas.", ephemeral=True)
                self.selected_max_attendees = 6
        self.stop()

    async def on_timeout(self):
        await self.disable_all_items()
        if self.message:
            try: await self.message.edit(content="Tempo esgotado para selecionar tipo.", view=self)
            except discord.HTTPException: pass
        await self.original_interaction.followup.send("Tempo esgotado para tipo. Criação cancelada.", ephemeral=True)
        self.stop()


class SelectChannelView(discord.ui.View):
    def __init__(self, bot: commands.Bot, original_interaction: discord.Interaction, text_channels_options: list[discord.SelectOption]):
        super().__init__(timeout=180.0)
        self.bot = bot; self.original_interaction = original_interaction
        self.selected_channel_id: Optional[int] = None
        self.message: Optional[discord.Message] = None
        if not text_channels_options:
            self.add_item(discord.ui.Button(label="Nenhum canal configurável encontrado", disabled=True, style=discord.ButtonStyle.danger)); return
        self.channel_select = discord.ui.Select(placeholder="Selecione o canal para postar...", options=text_channels_options, custom_id="utils_select_channel_dropdown")
        self.channel_select.callback = self.on_channel_select_callback; self.add_item(self.channel_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.original_interaction.user.id:
            await interaction.response.send_message("Você não pode interagir.", ephemeral=True); return False
        return True

    async def on_channel_select_callback(self, interaction: discord.Interaction):
        self.selected_channel_id = int(self.channel_select.values[0])
        self.channel_select.disabled = True
        await interaction.response.edit_message(content=f"Canal de postagem: <#{self.selected_channel_id}>. Processando...", view=self)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            if hasattr(item, 'disabled'): item.disabled = True
        if self.message:
            try: await self.message.edit(content="Tempo esgotado para selecionar canal. Criação cancelada.", view=self)
            except discord.HTTPException: pass
        await self.original_interaction.followup.send("Tempo esgotado para canal. Criação cancelada.", ephemeral=True)
        self.stop()

# --- Funções Utilitárias Existentes ---
def get_brazil_now() -> datetime.datetime:
    return datetime.datetime.now(BRAZIL_TZ)

def get_next_weekday_date(start_datetime_obj: datetime.datetime, target_weekday: int) -> datetime.date:
    days_ahead = target_weekday - start_datetime_obj.weekday()
    if days_ahead <= 0: days_ahead += 7
    return (start_datetime_obj + datetime.timedelta(days=days_ahead)).date()

def format_datetime_for_embed(dt_utc: datetime.datetime | str) -> tuple[str, str]:
    if isinstance(dt_utc, str):
        try: dt_utc = datetime.datetime.fromisoformat(dt_utc.replace('Z', '+00:00'))
        except ValueError: return "Data inválida", "Erro de formato"
    if dt_utc.tzinfo is None: dt_utc = pytz.utc.localize(dt_utc)
    elif dt_utc.tzinfo != pytz.utc: dt_utc = dt_utc.astimezone(pytz.utc)
    unix_ts = int(dt_utc.timestamp())
    return f"<t:{unix_ts}:F>", f"<t:{unix_ts}:R>"

async def ask_question_with_format(user: discord.User, bot: commands.Bot, prompt: str, example: str | None = None, timeout: int = 300, nl: bool = True) -> str | None:
    dm = await user.create_dm()
    msg = prompt + (f"\n{example}" if example and nl else (f" - {example}" if example else ""))
    try:
        await dm.send(msg)
        resp = await bot.wait_for("message", timeout=timeout, check=lambda m: m.author.id == user.id and isinstance(m.channel, discord.DMChannel))
        return resp.content.strip()
    except (discord.Forbidden, asyncio.TimeoutError) as e:
        if isinstance(e, discord.Forbidden): print(f"DM falhou para {user.name}: {e}")
        return None

async def get_user_display_name_static(user_id: int, bot: commands.Bot, guild: Optional[discord.Guild]) -> str:
    member = guild.get_member(user_id) if guild else None
    name = member.nick if member and member.nick else ""
    if not name:
        try:
            user_obj = bot.get_user(user_id) or await bot.fetch_user(user_id)
            name = user_obj.global_name if user_obj and user_obj.global_name else (user_obj.name if user_obj else f"Usuário ({user_id})")
        except (discord.NotFound, discord.HTTPException):
            name = f"Usuário ({user_id})"
    return name or f"ID:{user_id}"

def format_event_line_for_list(row: sqlite3.Row, vou_count: int, guild_id: int) -> str:
    dt_utc = datetime.datetime.fromisoformat(row['event_time_utc'].replace('Z', '+00:00'))
    dt_brt = dt_utc.astimezone(BRAZIL_TZ)
    date_str = f"{DIAS_SEMANA_PT_SHORT[dt_brt.weekday()]}. {dt_brt.strftime('%d/%m')}"
    vagas_disp = row['max_attendees'] - vou_count
    vagas_str = f"{vagas_disp} vagas"
    if vagas_disp <= 0:
        espera_count = len(db.db_get_rsvps_for_event(row['event_id']).get('lista_espera', []))
        vagas_str = f"Lotado (Espera: {espera_count})" if espera_count > 0 else "Lotado"
    elif vagas_disp == 1: vagas_str = "1 vaga"
    link = f"https://discord.com/channels/{guild_id}/{row['channel_id']}/{row['message_id']}" if all([row['channel_id'], row['message_id'], guild_id]) else ""
    fmt_line = f"{row['title']} - {date_str} às {dt_brt.strftime('%H:%M')} - {vagas_str}"
    return f"[{fmt_line}]({link})" if link else fmt_line

async def generate_event_list_message_content(guild_id: int, days: int, bot: commands.Bot) -> str:
    now_brt = get_brazil_now()
    start_utc = now_brt.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc)
    end_utc = (now_brt + datetime.timedelta(days=days)).replace(hour=23, minute=59, second=59, microsecond=999999).astimezone(pytz.utc)
    events = db.db_get_events_for_digest_list(guild_id, start_utc, end_utc)
    if not events: return f"Nenhum evento agendado para os próximos {days} dias."
    lines = [format_event_line_for_list(er, len(db.db_get_rsvps_for_event(er['event_id']).get('vou', [])), guild_id) for er in events]
    return "\n".join(lines)

async def get_text_channels_for_select(guild: discord.Guild, bot_user: discord.ClientUser) -> list[discord.SelectOption]:
    options: List[discord.SelectOption] = []
    if not guild: return options
    designated_ids = db.db_get_designated_event_channels(guild.id)
    if not designated_ids: return options
    bot_member = guild.get_member(bot_user.id)
    if not bot_member: return options
    for cid in designated_ids:
        ch = guild.get_channel(cid)
        if ch and isinstance(ch, discord.TextChannel):
            perms = ch.permissions_for(bot_member)
            if perms.send_messages and perms.embed_links:
                if len(options) < 25: options.append(discord.SelectOption(label=f"#{ch.name}", value=str(ch.id), description=f"Postar em: {ch.name}"))
                else: break
    return options

def detect_activity_details(name_input: str) -> tuple[str, str | None, int | None]:
    name_lower = name_input.lower().strip()
    best_match, best_type, best_spots, highest_sim = name_input.strip(), None, None, 0.0
    for official, keywords in ALL_ACTIVITIES_PT.items():
        sim_off = SequenceMatcher(None, name_lower, official.lower()).ratio()
        if sim_off > highest_sim: highest_sim, best_match = sim_off, official
        for kw in keywords:
            sim_kw = SequenceMatcher(None, name_lower, kw.lower()).ratio()
            if sim_kw > highest_sim: highest_sim, best_match = sim_kw, official
        if highest_sim == 1.0 and best_match == official: break
    if highest_sim >= SIMILARITY_THRESHOLD:
        if best_match in RAID_INFO_PT: best_type, best_spots = "Incursão", 6
        elif best_match in MASMORRA_INFO_PT: best_type, best_spots = "Masmorra", 3
        elif best_match in PVP_ACTIVITY_INFO_PT: best_type, best_spots = "PvP - Desafios de Osíris", 3
        return best_match, best_type, best_spots
    return name_input.strip(), None, None

def detect_and_format_event_subtype(title: str, description: Optional[str]) -> str:
    if not description:
        return title

    subtype_map = {
        'mestre': ' (Mestre)',
        'escola': ' (Escola)',
        'farm': ' (Farm)',
        'triunfo': ' (Triunfo)',
        'catalisador': ' (Catalisador)'
    }

    desc_lower = description.lower()

    for keyword, tag in subtype_map.items():
        if keyword in desc_lower:
            if tag.lower() not in title.lower():
                return f"{title}{tag}"

    return title

async def build_event_embed(event_details: sqlite3.Row, rsvps_data: Dict[str, List[int]], bot_instance: commands.Bot) -> discord.Embed:
    event_id, guild_id = event_details['event_id'], event_details['guild_id']
    guild = bot_instance.get_guild(guild_id)
    color = discord.Color.blue()
    if event_details['activity_type'] == "Incursão": color = discord.Color.purple()
    elif event_details['activity_type'] == "Masmorra": color = discord.Color.orange()
    elif str(event_details['activity_type']).startswith("PvP"): color = discord.Color.red()
    desc = f"**{event_details['description']}**" if event_details['description'] else "*Nenhuma descrição fornecida.*"
    embed = discord.Embed(title=event_details['title'], description=desc, color=color)
    dt_utc = datetime.datetime.fromisoformat(event_details['event_time_utc'].replace('Z', '+00:00'))
    fmt_date, rel_time = format_datetime_for_embed(dt_utc)
    embed.add_field(name="🗓️ Data e Hora", value=f"{fmt_date} ({rel_time})", inline=False)
    embed.add_field(name="🎮 Tipo", value=event_details['activity_type'], inline=True)
    creator_name = await get_user_display_name_static(event_details['creator_id'], bot_instance, guild)
    try: creator_mention = (await bot_instance.fetch_user(event_details['creator_id'])).mention
    except: creator_mention = creator_name
    embed.add_field(name="👑 Organizador", value=creator_mention, inline=True)
    max_a = event_details['max_attendees']
    vou_ids = rsvps_data.get('vou', [])
    vou_names = [await get_user_display_name_static(uid, bot_instance, guild) for uid in vou_ids]
    vou_lines = [f"{i+1}. {vou_names[i]}" if i < len(vou_names) else f"{i+1}. _________" for i in range(max_a)]
    vou_val = "\n".join(vou_lines) if max_a > 0 else "Ninguém."
    if not vou_lines and max_a > 0: vou_val = "Ninguém."
    embed.add_field(name=f"✅ Confirmados ({len(vou_names)}/{max_a})", value=vou_val if vou_val.strip() else "Ninguém.", inline=False)
    le_ids = rsvps_data.get('lista_espera', [])
    le_val = "\n".join([f"{i+1}. {await get_user_display_name_static(uid, bot_instance, guild)}" for i, uid in enumerate(le_ids)]) if le_ids else "-"
    embed.add_field(name=f"⏳ Lista de Espera ({len(le_ids)})", value=le_val, inline=False)
    nv_ids = rsvps_data.get('nao_vou', [])
    nv_val = "\n".join([await get_user_display_name_static(uid, bot_instance, guild) for uid in nv_ids]) if nv_ids else "-"
    embed.add_field(name=f"❌ Não vou ({len(nv_ids)})", value=nv_val, inline=True)
    tv_ids = rsvps_data.get('talvez', [])
    tv_val = "\n".join([await get_user_display_name_static(uid, bot_instance, guild) for uid in tv_ids]) if tv_ids else "-"
    embed.add_field(name=f"🔷 Talvez ({len(tv_ids)})", value=tv_val, inline=True)
    r_roles_str = event_details['restricted_role_ids']
    if r_roles_str and guild:
        r_names = [role.name if (role := guild.get_role(int(rid.strip()))) else f"Cargo ID {rid}(?)" for rid in r_roles_str.split(',') if rid.strip().isdigit()]
        if r_names: embed.add_field(name="🚫 Restrições (Evento)", value="- " + "\n- ".join(r_names), inline=False)
    embed.add_field(name="ℹ️ Como Participar", value="Use os botões para indicar presença!", inline=False)
    embed.set_footer(text=f"ID do Evento: {event_id}")
    return embed
