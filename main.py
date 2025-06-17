# main.py
import discord
from discord.ext import commands, tasks
import asyncio
import os # For loading cogs
import traceback # For error printing

# Custom module imports
import config # For TOKEN and GUILD_ID
import database as db # For init_db
from constants import DB_NAME # For printing
# Import PersistentRsvpView if its definition is here or in another accessible module
# If it's defined inside event_cog.py, we don't import it here directly for bot.add_view
# Instead, the cog itself should handle adding its views if necessary, or we find another way.
# For this structure, PersistentRsvpView is in event_cog.py.
# The recommended way for persistent views is to add them once.
# We will add it here AFTER event_cog is loaded, assuming its definition is accessible.
# A cleaner way would be for the cog to register its own persistent views.
# For now, let's assume event_cog.py makes PersistentRsvpView available globally or via an import.
# To make this work correctly, PersistentRsvpView definition should be outside any class in event_cog.py
# or imported directly.
# Let's adjust: we will import PersistentRsvpView from the event_cog module.
# This means PersistentRsvpView class should be defined at the top level of event_cog.py
from cogs.event_cog import PersistentRsvpView # Make sure this class is top-level in event_cog.py

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True  # For prefix commands, if any, and potentially message logging
intents.guilds = True          # Needed for guild-related events and properties
intents.members = True         # REQUIRED for accurately fetching member details (nicks, roles) for embeds

bot = commands.Bot(command_prefix="!", intents=intents) # Still define a prefix for on_command_error

# --- Cog Loading Function ---
async def load_cogs():
    print("DEBUG: Iniciando carregamento de cogs...")
    loaded_cogs_count = 0
    for filename in os.listdir('./cogs'): # Ensure this path is correct
        if filename.endswith('.py') and not filename.startswith('__'):
            try:
                await bot.load_extension(f'cogs.{filename[:-3]}')
                print(f"  -> Cog '{filename[:-3]}' carregado com sucesso.")
                loaded_cogs_count +=1
            except commands.ExtensionAlreadyLoaded:
                print(f"  -- Cog '{filename[:-3]}' já estava carregado.")
            except Exception as e:
                print(f"  XX Falha ao carregar o cog {filename[:-3]}: {type(e).__name__} - {e}")
                traceback.print_exc()
    print(f"DEBUG: Carregamento de cogs concluído. {loaded_cogs_count} cogs novos carregados.")


@bot.event
async def on_ready():
    print("-" * 30)
    print("DEBUG: Evento on_ready INICIADO")

    # 1. Initialize Database
    try:
        db.init_db() # Initialize database schema if not exists
        print("DEBUG: Banco de dados inicializado/verificado.")
    except Exception as e_db_init:
        print(f"ERRO CRÍTICO ao inicializar banco de dados: {e_db_init}")
        traceback.print_exc()
        return # Stop if DB fails

    # 2. Load Cogs
    await load_cogs()

    # 3. Add Persistent Views
    # Ensure PersistentRsvpView is defined in a way that it can be imported here.
    # Typically, class definitions are at the module's top level.
    try:
        # Check if a view with this custom_id prefix pattern is already added
        # This is a simplistic check; real persistent views are usually identified by their structure/items.
        # Since we pass the bot instance, it should handle its children correctly.
        # A better check would be specific to how discord.py manages persistent views.
        # For now, we assume we add it once.
        # If the view can be uniquely identified (e.g., by a unique property or checking bot.persistent_views),
        # you could add a check. For now, we'll add it.
        # If PersistentRsvpView is defined in event_cog, it's loaded with the cog.
        # We add it to the bot instance here.
        bot.add_view(PersistentRsvpView(bot_instance=bot))
        print("DEBUG: PersistentRsvpView adicionada ao bot.")
    except Exception as e_add_view:
        print(f"ERRO ao adicionar PersistentRsvpView: {e_add_view}")
        traceback.print_exc()


    # 4. Synchronize Slash Commands
    guild_obj = None
    sync_scope_msg = "globalmente"
    if hasattr(config, 'GUILD_ID') and config.GUILD_ID:
        try:
            guild_obj = discord.Object(id=int(config.GUILD_ID)) # type: ignore
            sync_scope_msg = f"para o servidor ID {config.GUILD_ID}"
        except ValueError:
            print(f"AVISO: GUILD_ID ('{config.GUILD_ID}') em config.py não é um ID numérico válido. Sincronizando globalmente.")
            guild_obj = None # Fallback to global sync
            sync_scope_msg = "globalmente (GUILD_ID inválido)"

    print(f"DEBUG: Aguardando bot estar totalmente pronto para sincronizar comandos {sync_scope_msg}...")
    await bot.wait_until_ready() # Ensure internal cache is ready

    try:
        synced_commands = await bot.tree.sync(guild=guild_obj)
        if synced_commands:
            print(f"Sincronizados {len(synced_commands)} comandos ({sync_scope_msg}). Nomes: {[s.name for s in synced_commands]}")
        else:
            print(f"AVISO: Nenhum comando foi sincronizado ({sync_scope_msg}). Verifique as definições dos comandos nos cogs.")
    except discord.HTTPException as e_sync:
        print(f"ERRO de HTTP ao sincronizar comandos ({sync_scope_msg}): {e_sync}")
        if "scope" in str(e_sync).lower():
             print("  -> Dica: Se estiver mudando de guild sync para global (ou vice-versa), pode levar um tempo para atualizar.")
    except Exception as e_sync_generic:
        print(f"ERRO GENÉRICO ao sincronizar comandos ({sync_scope_msg}): {e_sync_generic}")
        traceback.print_exc()

    # 5. Final Bot Ready Message
    if bot.user:
        print(f'Bot {bot.user.name} (ID: {bot.user.id}) conectado e pronto!')
        print(f'Usando banco de dados: {DB_NAME}')
    else:
        print("ERRO CRÍTICO: bot.user não está definido em on_ready. O bot pode não ter conectado corretamente.")

    print("DEBUG: Evento on_ready CONCLUÍDO")
    print("-" * 30)


@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return # Ignore messages from the bot itself

    # If you still want to process prefix commands (e.g., for admin purposes or older commands)
    await bot.process_commands(message)


# --- Main Execution ---
async def main_async():
    if not hasattr(config, 'TOKEN') or not config.TOKEN or config.TOKEN == "YOUR_DISCORD_BOT_TOKEN":
        print("ERRO CRÍTICO: O token do bot não foi configurado em config.py ou é o valor padrão.")
        print("Por favor, obtenha um token de https://discord.com/developers/applications e adicione-o ao arquivo config.py.")
        return

    async with bot:
        try:
            await bot.start(config.TOKEN)
        except discord.LoginFailure:
            print("Falha no login: Token inválido. Verifique o token em config.py.")
        except discord.PrivilegedIntentsRequired as e_intents:
            print(f"Falha no login: Intents privilegiadas faltando: {e_intents}")
            print("  -> Certifique-se de que as intents 'Server Members Intent' e 'Message Content Intent' estão habilitadas no portal de desenvolvedores do Discord para o seu bot.")
        except Exception as e_main_start:
            print(f"Erro inesperado durante a inicialização ou execução do bot: {e_main_start}")
            traceback.print_exc()
        finally:
            print("Bot está encerrando...")
            # Cogs should handle the cancellation of their own tasks in cog_unload
            # If any tasks are still managed directly in main.py, cancel them here.
            print("Processo de encerramento finalizado.")


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nBot desligado manualmente (KeyboardInterrupt).")
    except Exception as e_global_run:
        # This catches errors if asyncio.run itself fails or other top-level exceptions
        print(f"Erro global não capturado durante a execução do main_async: {e_global_run}")
        traceback.print_exc()