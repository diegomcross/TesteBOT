# role_utils.py
import discord
import datetime
from typing import Optional

async def create_event_role(guild: discord.Guild, event_title: str, event_date_obj: datetime.date) -> Optional[discord.Role]:
    """
    Cria um cargo temporário para um evento específico.

    Args:
        guild: O servidor (guild) onde o cargo será criado.
        event_title: O título do evento, usado para nomear o cargo.
        event_date_obj: A data do evento, usada para nomear o cargo.

    Returns:
        O objeto discord.Role criado, ou None se a criação falhar.
    """
    date_str_for_role = event_date_obj.strftime("%d/%m")
    # Nome do cargo: "Evento: {Título (máx ~78 chars)} - {DD/MM}"
    # Limite do Discord para nome de cargo é 100 caracteres.
    # "Evento: " = 8 chars, " - DD/MM" = 8 chars. Total: 16 chars.
    # Deixa 100 - 16 = 84 caracteres para o título. Truncar com alguma margem.
    max_title_len_for_role = 80 
    truncated_title = event_title[:max_title_len_for_role]
    role_name = f"Evento: {truncated_title} - {date_str_for_role}"

    try:
        # Cria o cargo com permissões mínimas, apenas para ser mencionável.
        # A cor pode ser aleatória ou uma cor padrão do bot.
        event_role = await guild.create_role(
            name=role_name,
            permissions=discord.Permissions.none(), # Sem permissões especiais por padrão
            mentionable=True, # Importante para que @cargo funcione
            reason=f"Cargo temporário para o evento '{event_title}' agendado para {date_str_for_role}"
        )
        print(f"DEBUG_ROLE_UTILS: Cargo temporário '{event_role.name}' (ID: {event_role.id}) criado na guild {guild.id}.")
        return event_role
    except discord.Forbidden:
        print(f"WARN_ROLE_UTILS: Sem permissão para criar cargos na guild {guild.id} para o evento '{event_title}'.")
    except discord.HTTPException as e:
        print(f"WARN_ROLE_UTILS: Erro HTTP ao criar cargo para o evento '{event_title}' na guild {guild.id}: {e}")
    except Exception as e:
        print(f"ERRO_ROLE_UTILS: Erro inesperado ao criar cargo para o evento '{event_title}': {e}")
    return None

async def delete_event_role(guild: discord.Guild, role_id: int, reason: str = "Evento concluído ou cancelado.") -> bool:
    """
    Deleta um cargo de evento específico.

    Args:
        guild: O servidor (guild) de onde o cargo será deletado.
        role_id: O ID do cargo a ser deletado.
        reason: A razão para a deleção do cargo.

    Returns:
        True se o cargo foi deletado com sucesso, False caso contrário.
    """
    if not guild:
        print(f"WARN_ROLE_UTILS: Tentativa de deletar cargo {role_id} mas a guild não foi fornecida ou é inválida.")
        return False

    role_to_delete = guild.get_role(role_id)
    if role_to_delete:
        try:
            await role_to_delete.delete(reason=reason)
            print(f"DEBUG_ROLE_UTILS: Cargo temporário ID {role_id} ('{role_to_delete.name}') deletado da guild {guild.id}.")
            return True
        except discord.Forbidden:
            print(f"WARN_ROLE_UTILS: Sem permissão para deletar o cargo ID {role_id} da guild {guild.id}.")
        except discord.HTTPException as e:
            print(f"WARN_ROLE_UTILS: Erro HTTP ao deletar o cargo ID {role_id} da guild {guild.id}: {e}")
        except Exception as e:
            print(f"ERRO_ROLE_UTILS: Erro inesperado ao deletar cargo ID {role_id}: {e}")
    else:
        print(f"INFO_ROLE_UTILS: Cargo temporário ID {role_id} não encontrado na guild {guild.id} para deleção (pode já ter sido deletado).")
        return True # Considera sucesso se o cargo não existe, pois o objetivo é que ele não exista mais.
    return False

async def manage_member_event_role(member: discord.Member, role: Optional[discord.Role], action: str, event_id_for_log: int) -> bool:
    """
    Adiciona ou remove um membro de um cargo de evento.

    Args:
        member: O objeto discord.Member.
        role: O objeto discord.Role. Se None, a função não fará nada e retornará False.
        action: "add" para adicionar, "remove" para remover.
        event_id_for_log: O ID do evento, para logging.

    Returns:
        True se a ação foi bem-sucedida, False caso contrário.
    """
    if not role:
        print(f"DEBUG_ROLE_UTILS: Tentativa de gerenciar cargo para usuário {member.id} no evento {event_id_for_log}, mas o cargo é None.")
        return False

    if not member:
        print(f"DEBUG_ROLE_UTILS: Tentativa de gerenciar cargo {role.id} para usuário (ID não disponível) no evento {event_id_for_log}, mas o membro é None.")
        return False

    try:
        if action == "add":
            if role not in member.roles: # Evita erro se já tiver o cargo
                await member.add_roles(role, reason=f"Participando do evento {event_id_for_log}")
                print(f"DEBUG_ROLE_UTILS: Usuário {member.id} ({member.display_name}) adicionado ao cargo '{role.name}' (ID: {role.id}) para evento {event_id_for_log}.")
            else:
                print(f"DEBUG_ROLE_UTILS: Usuário {member.id} já possui o cargo '{role.name}' para evento {event_id_for_log}.")
            return True
        elif action == "remove":
            if role in member.roles: # Evita erro se não tiver o cargo
                await member.remove_roles(role, reason=f"Não participa mais ativamente do evento {event_id_for_log}")
                print(f"DEBUG_ROLE_UTILS: Usuário {member.id} ({member.display_name}) removido do cargo '{role.name}' (ID: {role.id}) para evento {event_id_for_log}.")
            else:
                print(f"DEBUG_ROLE_UTILS: Usuário {member.id} não possuía o cargo '{role.name}' para evento {event_id_for_log} para ser removido.")
            return True
        else:
            print(f"WARN_ROLE_UTILS: Ação desconhecida '{action}' para gerenciamento de cargo do evento {event_id_for_log}.")
            return False
    except discord.Forbidden:
        print(f"WARN_ROLE_UTILS: Sem permissão para '{action}' cargo '{role.name}' para/de {member.display_name} (ID: {member.id}) no evento {event_id_for_log}.")
    except discord.HTTPException as e:
        print(f"WARN_ROLE_UTILS: Erro HTTP ao '{action}' cargo '{role.name}' para/de {member.display_name} (ID: {member.id}) no evento {event_id_for_log}: {e}")
    except Exception as e:
        print(f"ERRO_ROLE_UTILS: Erro inesperado ao '{action}' cargo para {member.display_name} (ID: {member.id}): {e}")
    return False
