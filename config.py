# config.py
import os
from dotenv import load_dotenv # Import for .env file handling (optional for Replit secrets)

# Load .env file if it exists (useful for local development, Replit handles secrets differently)
load_dotenv()

TOKEN = os.environ.get("DISCORD_BOT_TOKEN") # Reads from Replit's "Secrets" or your .env file
GUILD_ID_STR = os.environ.get("DISCORD_GUILD_ID") # Also read GUILD_ID from environment if needed

GUILD_ID = None
if GUILD_ID_STR and GUILD_ID_STR.isdigit():
    GUILD_ID = int(GUILD_ID_STR)
elif GUILD_ID_STR:
    print(f"AVISO: GUILD_ID ('{GUILD_ID_STR}') no ambiente não é um ID numérico válido.")

# You can add a check here to ensure TOKEN is loaded
if not TOKEN:
    print("ERRO CRÍTICO EM CONFIG.PY: DISCORD_BOT_TOKEN não encontrado nos segredos/variáveis de ambiente.")
    # You might want to raise an error here or let main.py handle the None value