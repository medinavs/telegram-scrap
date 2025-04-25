from telethon import TelegramClient
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv('API_ID', 0))
API_HASH = os.getenv('API_HASH', '')
SESSION_NAME = 'user_session'

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

async def list_all_dialogs():
    await client.start()
    
    print("\n=== TODOS OS DIÁLOGOS DISPONÍVEIS ===")
    print("ID | TIPO | NOME")
    print("-" * 50)
    
    async for dialog in client.iter_dialogs():
        entity_type = type(dialog.entity).__name__
        print(f"{dialog.id} | {entity_type} | {dialog.name}")
    
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(list_all_dialogs())