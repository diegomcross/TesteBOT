# database.py
import sqlite3
import datetime
import pytz
import json
from constants import DB_NAME
from typing import List, Dict, Set

def init_db():
    print("DEBUG: init_db - Iniciando")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # --- Tabela server_configs ---
    cursor.execute("PRAGMA table_info(server_configs)")
    server_configs_columns = [column[1] for column in cursor.fetchall()]

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS server_configs (
            guild_id INTEGER PRIMARY KEY,
            digest_channel_id INTEGER,
            default_restricted_role_ids TEXT,
            onboarding_role_id INTEGER
        )
    ''')
    if 'onboarding_role_id' not in server_configs_columns:
        try:
            cursor.execute("ALTER TABLE server_configs ADD COLUMN onboarding_role_id INTEGER")
            print("DEBUG: Coluna onboarding_role_id adicionada à tabela server_configs.")
        except sqlite3.OperationalError: pass

    # --- Tabela event_permissions ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS event_permissions (
            guild_id INTEGER NOT NULL,
            role_id INTEGER NOT NULL,
            permission TEXT NOT NULL,
            PRIMARY KEY (guild_id, role_id, permission)
        )
    ''')

    # --- Tabela user_onboarding ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_onboarding (
            user_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            completed_at_utc TEXT NOT NULL,
            answers_json TEXT,
            PRIMARY KEY (user_id, guild_id)
        )
    ''')

    # --- Tabela events ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT, 
            guild_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL, 
            creator_id INTEGER NOT NULL,
            title TEXT NOT NULL, 
            description TEXT, 
            event_time_utc TEXT NOT NULL, 
            activity_type TEXT NOT NULL, 
            max_attendees INTEGER NOT NULL,
            created_at_utc TEXT NOT NULL,
            message_id INTEGER UNIQUE,
            role_mentions TEXT, 
            restricted_role_ids TEXT, 
            status TEXT DEFAULT 'ativo', 
            delete_message_after_utc TEXT, 
            reminder_sent INTEGER DEFAULT 0, 
            temp_role_id INTEGER,
            confirmation_reminder_sent INTEGER DEFAULT 0,
            is_recurring_template INTEGER DEFAULT 0, 
            recurrence_type TEXT,
            recurrence_interval INTEGER DEFAULT 1, 
            recurrence_days_of_week TEXT,
            recurrence_day_of_month INTEGER, 
            recurrence_week_of_month INTEGER,
            recurrence_weekday_of_month INTEGER, 
            recurrence_end_date_utc TEXT,
            recurrence_count_total INTEGER, 
            recurrence_count_generated INTEGER DEFAULT 0,
            parent_template_id INTEGER REFERENCES events(event_id) ON DELETE SET NULL
        )
    ''')

    # --- Outras Tabelas ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rsvps (
            rsvp_id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            status TEXT NOT NULL, rsvp_timestamp TEXT NOT NULL, UNIQUE(event_id, user_id), 
            FOREIGN KEY (event_id) REFERENCES events (event_id) ON DELETE CASCADE
        )''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS designated_event_channels (
            guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, PRIMARY KEY (guild_id, channel_id)
        )''')
    conn.commit()
    if conn: conn.close()
    print("DEBUG: init_db - Concluído, schema verificado/atualizado.")


# --- Funções de Permissões de Evento ---
def db_add_event_permission(guild_id: int, role_id: int, permission: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO event_permissions (guild_id, role_id, permission) VALUES (?, ?, ?)", (guild_id, role_id, permission))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Erro DB ao adicionar permissão de evento: {e}")
    finally:
        if conn: conn.close()

def db_remove_event_permission(guild_id: int, role_id: int, permission: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM event_permissions WHERE guild_id = ? AND role_id = ? AND permission = ?", (guild_id, role_id, permission))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Erro DB ao remover permissão de evento: {e}")
    finally:
        if conn: conn.close()

def db_get_roles_with_permission(guild_id: int, permission: str) -> List[int]:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT role_id FROM event_permissions WHERE guild_id = ? AND permission = ?", (guild_id, permission))
        return [row[0] for row in cursor.fetchall()]
    except sqlite3.Error as e:
        print(f"Erro DB ao buscar cargos com permissão '{permission}': {e}")
        return []
    finally:
        if conn: conn.close()

def db_get_all_event_permissions(guild_id: int) -> Dict[int, List[str]]:
    permissions_by_role: Dict[int, List[str]] = {}
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT role_id, permission FROM event_permissions WHERE guild_id = ?", (guild_id,))
        for role_id, permission in cursor.fetchall():
            if role_id not in permissions_by_role:
                permissions_by_role[role_id] = []
            permissions_by_role[role_id].append(permission)
    except sqlite3.Error as e:
        print(f"Erro DB ao buscar todas as permissões de evento: {e}")
    finally:
        if conn: conn.close()
    return permissions_by_role

def db_check_user_permission(guild_id: int, user_roles_ids: Set[int], permission: str) -> bool:
    """Verifica se algum dos cargos do usuário possui a permissão especificada."""
    roles_with_perm = db_get_roles_with_permission(guild_id, permission)
    if not roles_with_perm:
        return False
    return not user_roles_ids.isdisjoint(roles_with_perm)


# --- Funções de Onboarding ---
def db_set_onboarding_role(guild_id: int, role_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO server_configs (guild_id, onboarding_role_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET onboarding_role_id = excluded.onboarding_role_id", (guild_id, role_id))
        conn.commit()
    except sqlite3.Error as e: print(f"Erro no DB ao definir cargo de onboarding: {e}")
    finally:
        if conn: conn.close()

def db_get_onboarding_role(guild_id: int) -> int | None:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT onboarding_role_id FROM server_configs WHERE guild_id = ?", (guild_id,))
        row = cursor.fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.Error as e:
        print(f"Erro no DB ao buscar cargo de onboarding: {e}")
        return None
    finally:
        if conn: conn.close()

def db_add_user_onboarding(user_id: int, guild_id: int, answers: dict):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        answers_json = json.dumps(answers)
        completed_at = datetime.datetime.now(pytz.utc).isoformat()
        cursor.execute('''
            INSERT INTO user_onboarding (user_id, guild_id, completed_at_utc, answers_json) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET
            completed_at_utc = excluded.completed_at_utc,
            answers_json = excluded.answers_json
        ''', (user_id, guild_id, completed_at, answers_json))
        conn.commit()
    except sqlite3.Error as e:
        print(f"Erro no DB ao adicionar registro de onboarding do usuário: {e}")
    finally:
        if conn: conn.close()

def db_has_user_completed_onboarding(user_id: int, guild_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT 1 FROM user_onboarding WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
        return cursor.fetchone() is not None
    except sqlite3.Error as e:
        print(f"Erro no DB ao verificar onboarding do usuário: {e}")
        return False
    finally:
        if conn: conn.close()


# --- Funções para Designated Event Channels ---
def db_add_designated_event_channel(guild_id: int, channel_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO designated_event_channels (guild_id, channel_id) VALUES (?, ?)", (guild_id, channel_id))
        conn.commit()
    except sqlite3.Error as e: print(f"Erro DB ao adicionar canal designado: {e}")
    finally:
        if conn: conn.close()

def db_remove_designated_event_channel(guild_id: int, channel_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM designated_event_channels WHERE guild_id = ? AND channel_id = ?", (guild_id, channel_id))
        conn.commit()
    except sqlite3.Error as e: print(f"Erro DB ao remover canal designado: {e}")
    finally:
        if conn: conn.close()

def db_get_designated_event_channels(guild_id: int) -> list[int]:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT channel_id FROM designated_event_channels WHERE guild_id = ?", (guild_id,))
        return [row[0] for row in cursor.fetchall()]
    except sqlite3.Error as e: print(f"Erro DB ao buscar canais designados: {e}"); return []
    finally:
        if conn: conn.close()

# --- Funções de RSVP ---
def db_add_or_update_rsvp(event_id: int, user_id: int, status: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    timestamp_utc = datetime.datetime.now(pytz.utc).isoformat()
    try:
        cursor.execute('''
            INSERT INTO rsvps (event_id, user_id, status, rsvp_timestamp) VALUES (?, ?, ?, ?)
            ON CONFLICT(event_id, user_id) DO UPDATE SET status = excluded.status, rsvp_timestamp = excluded.rsvp_timestamp
        ''', (event_id, user_id, status, timestamp_utc))
        conn.commit()
    except sqlite3.Error as e: print(f"Erro DB ao adicionar/atualizar RSVP: {e}")
    finally:
        if conn: conn.close()

def db_remove_rsvp(event_id: int, user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM rsvps WHERE event_id = ? AND user_id = ?", (event_id, user_id))
        conn.commit()
    except sqlite3.Error as e: print(f"Erro DB ao remover RSVP: {e}")
    finally:
        if conn: conn.close()

def db_get_rsvps_for_event(event_id: int) -> dict:
    rsvps = {'vou': [], 'nao_vou': [], 'talvez': [], 'lista_espera': []}
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id, status FROM rsvps WHERE event_id = ? ORDER BY rsvp_timestamp ASC", (event_id,))
        for row in cursor.fetchall():
            if row['status'] in rsvps: rsvps[row['status']].append(row['user_id'])
    except sqlite3.Error as e: print(f"Erro DB ao buscar RSVPs: {e}")
    finally:
        if conn: conn.close()
    return rsvps

def db_get_user_active_rsvps_in_guild(user_id: int, guild_id: int) -> list[int]:
    """Busca todos os IDs de eventos ativos para os quais um usuário tem um RSVP em um servidor específico."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT event_id FROM rsvps 
            WHERE user_id = ? AND event_id IN 
            (SELECT event_id FROM events WHERE guild_id = ? AND status = 'ativo')
        ''', (user_id, guild_id))
        return [row[0] for row in cursor.fetchall()]
    except sqlite3.Error as e:
        print(f"Erro DB ao buscar RSVPs ativos do usuário na guild: {e}")
        return []
    finally:
        if conn: conn.close()


# --- Funções de Eventos ---
def db_get_event_details(event_id: int) -> sqlite3.Row | None:
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
        return cursor.fetchone()
    except sqlite3.Error as e: print(f"Erro DB ao buscar detalhes do evento {event_id}: {e}"); return None
    finally:
        if conn: conn.close()

def db_update_event_status(event_id: int, status: str, delete_after_utc: str | None = None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        if delete_after_utc:
            cursor.execute("UPDATE events SET status = ?, delete_message_after_utc = ? WHERE event_id = ?", (status, delete_after_utc, event_id))
        else:
            cursor.execute("UPDATE events SET status = ?, delete_message_after_utc = NULL WHERE event_id = ?", (status, event_id))
        conn.commit()
    except sqlite3.Error as e: print(f"Erro DB ao atualizar status do evento {event_id}: {e}")
    finally:
        if conn: conn.close()

def db_update_event_details(event_id: int, **kwargs):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    updates = [f"{key} = ?" for key in kwargs]
    params = list(kwargs.values())

    if not updates:
        print(f"DEBUG: Nenhum campo fornecido para atualizar evento {event_id}."); conn.close(); return

    params.append(event_id)
    query = f"UPDATE events SET {', '.join(updates)} WHERE event_id = ?"

    try:
        cursor.execute(query, tuple(params))
        conn.commit()
    except sqlite3.Error as e: print(f"Erro no DB ao atualizar detalhes do evento {event_id}: {e}")
    finally:
        if conn: conn.close()

def db_get_events_for_cleanup() -> list[sqlite3.Row]:
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    two_hours_ago = datetime.datetime.now(pytz.utc) - datetime.timedelta(hours=2)
    try:
        cursor.execute("SELECT * FROM events WHERE status = 'ativo' AND (is_recurring_template = 0 OR is_recurring_template IS NULL) AND event_time_utc < ?", (two_hours_ago.isoformat(),))
        return cursor.fetchall()
    except sqlite3.Error as e: print(f"Erro DB ao buscar eventos para cleanup: {e}"); return []
    finally:
        if conn: conn.close()

def db_get_events_to_delete_message() -> list[sqlite3.Row]:
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    now_utc = datetime.datetime.now(pytz.utc).isoformat()
    try:
        cursor.execute("SELECT event_id, guild_id, channel_id, message_id, status FROM events WHERE (status = 'cancelado' OR status = 'concluido') AND delete_message_after_utc IS NOT NULL AND delete_message_after_utc <= ?", (now_utc,))
        return cursor.fetchall()
    except sqlite3.Error as e: print(f"Erro DB ao buscar eventos para deletar msg: {e}"); return []
    finally:
        if conn: conn.close()

def db_clear_message_id_and_update_status_after_delete(event_id: int, original_status: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    new_status = f"msg_{original_status}_deletada"
    try:
        cursor.execute("UPDATE events SET message_id = NULL, status = ?, delete_message_after_utc = NULL WHERE event_id = ?", (new_status, event_id))
        conn.commit()
    except sqlite3.Error as e: print(f"Erro DB ao limpar message_id e status do evento {event_id}: {e}")
    finally:
        if conn: conn.close()

def db_get_upcoming_events_for_reminder() -> list[sqlite3.Row]: # Lembrete de ~15 min
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    now_utc = datetime.datetime.now(pytz.utc)
    start_window = (now_utc + datetime.timedelta(minutes=14)).isoformat()
    end_window = (now_utc + datetime.timedelta(minutes=16)).isoformat()
    try:
        cursor.execute("SELECT * FROM events WHERE status = 'ativo' AND (is_recurring_template = 0 OR is_recurring_template IS NULL) AND reminder_sent = 0 AND event_time_utc > ? AND event_time_utc <= ?", (start_window, end_window ))
        return cursor.fetchall()
    except sqlite3.Error as e: print(f"Erro DB ao buscar eventos para lembrete: {e}"); return []
    finally:
        if conn: conn.close()

def db_mark_reminder_sent(event_id: int, reminder_type: str = "standard"):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    column_to_update = "reminder_sent"
    if reminder_type == "confirmation":
        column_to_update = "confirmation_reminder_sent"
    try:
        cursor.execute(f"UPDATE events SET {column_to_update} = 1 WHERE event_id = ?", (event_id,))
        conn.commit()
    except sqlite3.Error as e: print(f"Erro DB ao marcar {reminder_type} lembrete como enviado para evento {event_id}: {e}")
    finally:
        if conn: conn.close()

def db_get_events_for_confirmation_reminder() -> list[sqlite3.Row]: # Lembrete de ~1 hora
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    now_utc = datetime.datetime.now(pytz.utc)
    start_window = (now_utc + datetime.timedelta(minutes=59)).isoformat()
    end_window = (now_utc + datetime.timedelta(minutes=61)).isoformat()
    try:
        cursor.execute("SELECT * FROM events WHERE status = 'ativo' AND (is_recurring_template = 0 OR is_recurring_template IS NULL) AND confirmation_reminder_sent = 0 AND event_time_utc > ? AND event_time_utc <= ?", (start_window, end_window ))
        return cursor.fetchall()
    except sqlite3.Error as e: print(f"Erro DB ao buscar eventos para lembrete de confirmação: {e}"); return []
    finally:
        if conn: conn.close()

def db_create_event(**kwargs) -> int | None:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    event_id = None
    columns = [
        "guild_id", "channel_id", "creator_id", "title", "description", "event_time_utc", 
        "activity_type", "max_attendees", "created_at_utc", "role_mentions", "restricted_role_ids", 
        "temp_role_id"
    ]
    values = tuple(kwargs.get(col) for col in columns)
    columns_str = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))
    try:
        cursor.execute(f"INSERT INTO events ({columns_str}) VALUES ({placeholders})", values)
        event_id = cursor.lastrowid
        conn.commit()
    except sqlite3.Error as e: print(f"Erro DB ao criar evento: {e}")
    finally:
        if conn: conn.close()
    return event_id

def db_update_event_message_id(event_id: int, message_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE events SET message_id = ? WHERE event_id = ?", (message_id, event_id))
        conn.commit()
    except sqlite3.Error as e: print(f"Erro DB ao atualizar message_id do evento {event_id}: {e}")
    finally:
        if conn: conn.close()

def db_get_event_temp_role_id(event_id: int) -> int | None:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT temp_role_id FROM events WHERE event_id = ?", (event_id,))
        row = cursor.fetchone()
        return row[0] if row and row[0] is not None else None
    except sqlite3.Error as e: print(f"Erro DB ao buscar temp_role_id para evento {event_id}: {e}"); return None
    finally:
        if conn: conn.close()

def db_set_default_restricted_roles(guild_id: int, role_ids: list[int]):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    role_ids_str = ",".join(map(str, role_ids)) if role_ids else None
    try:
        cursor.execute("INSERT INTO server_configs (guild_id, default_restricted_role_ids) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET default_restricted_role_ids = excluded.default_restricted_role_ids", (guild_id, role_ids_str))
        conn.commit()
    except sqlite3.Error as e: print(f"Erro DB ao definir cargos restritos padrão: {e}")
    finally:
        if conn: conn.close()

def db_get_default_restricted_roles(guild_id: int) -> list[int]:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT default_restricted_role_ids FROM server_configs WHERE guild_id = ?", (guild_id,))
        row = cursor.fetchone()
        if row and row[0]: return [int(rid) for rid in row[0].split(',') if rid.strip().isdigit()]
    except sqlite3.Error as e: print(f"Erro DB ao buscar cargos restritos padrão: {e}")
    finally:
        if conn: conn.close()
    return []

def db_set_digest_channel(guild_id: int, channel_id: int | None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO server_configs (guild_id, digest_channel_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET digest_channel_id = excluded.digest_channel_id", (guild_id, channel_id))
        conn.commit()
    except sqlite3.Error as e: print(f"Erro DB ao definir canal de digest: {e}")
    finally:
        if conn: conn.close()

def db_get_digest_channel(guild_id: int) -> int | None:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT digest_channel_id FROM server_configs WHERE guild_id = ?", (guild_id,))
        row = cursor.fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.Error as e: print(f"Erro DB ao buscar canal de digest: {e}"); return None
    finally:
        if conn: conn.close()

def db_get_events_for_digest_list(guild_id: int, start_utc: datetime.datetime, end_utc: datetime.datetime) -> list[sqlite3.Row]:
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM events WHERE guild_id = ? AND status = 'ativo' AND event_time_utc BETWEEN ? AND ? ORDER BY event_time_utc ASC", (guild_id, start_utc.isoformat(), end_utc.isoformat()))
        return cursor.fetchall()
    except sqlite3.Error as e: print(f"Erro DB ao buscar eventos para digest: {e}"); return []
    finally:
        if conn: conn.close()
