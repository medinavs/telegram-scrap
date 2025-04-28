from telethon import TelegramClient, events, functions, types
from telethon.tl.types import InputChannel, Channel, InputPeerChannel
from telethon.errors import ChatAdminRequiredError, ChatForbiddenError
import asyncio
import os
import logging
import json
from dotenv import load_dotenv
import discord
from discord.ext import commands

os.makedirs("./downloads", exist_ok=True)

# configs
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# telegram Config
API_ID = int(os.getenv('API_ID', 0))
API_HASH = os.getenv('API_HASH', '')
SESSION_NAME = 'user_session'
CANAL_ORIGEM_STR = os.getenv('CANAL_ORIGEM', '')
TOPICOS_IGNORADOS_STR = os.getenv('TOPICOS_IGNORADOS', '')

# discord Config
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', '')
DISCORD_GUILD_ID = int(os.getenv('DISCORD_GUILD_ID', 0))
DISCORD_CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', 0)) # channel id to send messages

# dirs
MAPPINGS_DIR = "./mappings"
os.makedirs(MAPPINGS_DIR, exist_ok=True)

TOPICOS_IGNORADOS = []
if TOPICOS_IGNORADOS_STR:
    try:
        # check if is csv
        if "," in TOPICOS_IGNORADOS_STR:
            for id_str in TOPICOS_IGNORADOS_STR.split(","):
                if id_str.strip().strip('"').strip("'"):
                    TOPICOS_IGNORADOS.append(int(id_str.strip().strip('"').strip("'")))
        else:
            # try with unique value
            if TOPICOS_IGNORADOS_STR.strip('"').strip("'"):
                TOPICOS_IGNORADOS.append(int(TOPICOS_IGNORADOS_STR.strip('"').strip("'")))
    except Exception as e:
        logger.error(f"Erro ao processar TOPICOS_IGNORADOS: {e}")
        TOPICOS_IGNORADOS = []

try:
    CANAL_ORIGEM = int(CANAL_ORIGEM_STR.strip('"').strip("'")) if CANAL_ORIGEM_STR and CANAL_ORIGEM_STR.strip('"').strip("'").startswith('-') else CANAL_ORIGEM_STR.strip('"').strip("'")
except ValueError as e:
    logger.error(f"Erro ao converter canal: {e}")
    exit(1)

if not API_ID or not API_HASH or not CANAL_ORIGEM or not DISCORD_TOKEN or not DISCORD_CHANNEL_ID:
    logger.error("Por favor, configure as variáveis de ambiente API_ID, API_HASH, CANAL_ORIGEM, DISCORD_TOKEN e DISCORD_CHANNEL_ID")
    exit(1)

telegram_client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# config discord with intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
discord_client = commands.Bot(command_prefix="!", intents=intents)

# mapper of telegram topics to discord channels
class TopicMapper:
    def __init__(self, origem_id):
        self.origem_id = str(origem_id)
        
        # map of topics: {id_topico_origem: id_canal_discord}
        self.topic_mapping = {}
        
        # name of the file to store the mapping
        self.mapping_file = os.path.join(MAPPINGS_DIR, f"topic_mapping_{self.origem_id}_discord.json")
        
        # load if exists
        self._load_mapping()
    
    def _load_mapping(self):
        if os.path.exists(self.mapping_file):
            try:
                with open(self.mapping_file, 'r') as f:
                    data = json.load(f)
                    # string to int conversion
                    self.topic_mapping = {int(k): int(v) for k, v in data.items()}
                logger.info(f"Mapeamento de tópicos carregado: {len(self.topic_mapping)} tópicos")
            except Exception as e:
                logger.error(f"Erro ao carregar mapeamento de tópicos: {e}")
                self.topic_mapping = {}
    
    def _save_mapping(self):
        try:
            with open(self.mapping_file, 'w') as f:
                # stringify to serialize
                json_data = {str(k): str(v) for k, v in self.topic_mapping.items()}
                json.dump(json_data, f)
            logger.info(f"Mapeamento de tópicos salvo: {len(self.topic_mapping)} tópicos")
        except Exception as e:
            logger.error(f"Erro ao salvar mapeamento de tópicos: {e}")
    
    def get_discord_channel_id(self, origem_topic_id):
        return self.topic_mapping.get(origem_topic_id)
    
    def add_topic_mapping(self, origem_topic_id, discord_channel_id):
        self.topic_mapping[origem_topic_id] = discord_channel_id
        self._save_mapping()
        logger.info(f"Novo mapeamento de tópico adicionado: {origem_topic_id} -> {discord_channel_id}")

async def main():
    # init telegram client
    await telegram_client.start()
    logger.info("Cliente Telegram conectado com sucesso!")
    
    # init client discord
    discord_client.remove_command('help')
    
    @discord_client.event
    async def on_ready():
        logger.info(f'Discord Bot conectado como {discord_client.user}')
        logger.info(f'ID do Bot: {discord_client.user.id}')
        
        # check channels and permissions
        guild = discord_client.get_guild(DISCORD_GUILD_ID)
        if not guild:
            logger.error(f"Não foi possível encontrar o servidor Discord com ID {DISCORD_GUILD_ID}")
            return
            
        channel = guild.get_channel(DISCORD_CHANNEL_ID)
        if not channel:
            logger.error(f"Não foi possível encontrar o canal Discord com ID {DISCORD_CHANNEL_ID}")
            return
            
        logger.info(f"Servidor Discord: {guild.name} (ID: {guild.id})")
        logger.info(f"Canal Discord principal: {channel.name} (ID: {channel.id})")
        
        # start telegram handlers
        await setup_telegram_handlers()
    
    # start discord client as background task
    asyncio.create_task(discord_client.start(DISCORD_TOKEN))
    
    # config log
    logger.info(f"CANAL_ORIGEM: {CANAL_ORIGEM}")
    logger.info(f"TÓPICOS IGNORADOS: {TOPICOS_IGNORADOS}")

    # origen channel entity
    try:
        canal_origem_entity = await telegram_client.get_entity(CANAL_ORIGEM)
        origem_id = canal_origem_entity.id
        
        logger.info(f"Canal de origem: {getattr(canal_origem_entity, 'title', CANAL_ORIGEM)} (ID: {origem_id})")
        
        # instance of the topic mapper
        topic_mapper = TopicMapper(origem_id)
        
    except Exception as e:
        logger.error(f"Erro ao obter canal origem: {e}")
        await telegram_client.disconnect()
        exit(1)

    async def get_or_create_discord_channel(topic_title, telegram_topic_id):
        """
        Obtém ou cria um canal no Discord com o mesmo título do tópico do Telegram
        """
        discord_channel_id = topic_mapper.get_discord_channel_id(telegram_topic_id)
        if discord_channel_id:
            # check if exists
            channel = discord_client.get_channel(discord_channel_id)
            if channel:
                return channel
        
        try:
            guild = discord_client.get_guild(DISCORD_GUILD_ID)
            if not guild:
                logger.error("Servidor Discord não encontrado")
                return None
            
            # create a new channel with the same name as the topic
            safe_name = ''.join(c for c in topic_title.lower() if c.isalnum() or c in '-_').replace(' ', '-')
            if not safe_name:
                safe_name = f"topic-{telegram_topic_id}"
                
            # check if channel already exists
            existing_channel = discord.utils.get(guild.text_channels, name=safe_name)
            if existing_channel:
                topic_mapper.add_topic_mapping(telegram_topic_id, existing_channel.id)
                return existing_channel
            
            # create a new channel
            new_channel = await guild.create_text_channel(
                name=safe_name,
                topic=f"Tópico importado do Telegram: {topic_title}"
            )
            
            topic_mapper.add_topic_mapping(telegram_topic_id, new_channel.id)
            logger.info(f"Novo canal Discord criado: '{new_channel.name}' (ID: {new_channel.id})")
            return new_channel
            
        except discord.errors.Forbidden:
            logger.error("Erro ao criar canal: Permissões insuficientes no Discord")
            return None
        except Exception as e:
            logger.error(f"Erro ao criar canal Discord para tópico '{topic_title}': {e}")
            return None

    async def get_topic_info(message):
        topic_id = None
        
        if hasattr(message, 'reply_to') and message.reply_to:
            if hasattr(message.reply_to, 'reply_to_top_id') and message.reply_to.reply_to_top_id:
                topic_id = message.reply_to.reply_to_top_id
            elif hasattr(message.reply_to, 'forum_topic') and message.reply_to.forum_topic:
                if not isinstance(message.reply_to.forum_topic, bool) and hasattr(message.reply_to.forum_topic, 'id'):
                    topic_id = message.reply_to.forum_topic.id
        
        if not topic_id and hasattr(message, 'forum_topic') and message.forum_topic:
            if not isinstance(message.forum_topic, bool) and hasattr(message.forum_topic, 'id'):
                topic_id = message.forum_topic.id
        
        if not topic_id:
            return None, None
        
        try:
            # try to obtain the topics from the channel
            forum_topics = await telegram_client.get_messages(
                canal_origem_entity,
                ids=types.InputMessageID(topic_id)
            )
            
            if forum_topics:
                return topic_id, getattr(forum_topics[0], 'topic', {}).get('title', f"Tópico {topic_id}")
            else:
                return topic_id, f"Tópico {topic_id}"
            
        except Exception as e:
            logger.warning(f"Não foi possível obter título do tópico {topic_id}: {e}")
            try:
                # second method to obtain the topic title
                forum_topics = await telegram_client(functions.channels.GetForumTopicsRequest(
                    channel=canal_origem_entity,
                    offset_date=0,
                    offset_id=0,
                    offset_topic=0,
                    limit=100,
                    q=""
                ))
                
                for topic in forum_topics.topics:
                    if topic.id == topic_id:
                        return topic_id, topic.title
                
                return topic_id, f"Tópico {topic_id}"
            except Exception as e2:
                logger.warning(f"Segunda tentativa falhou: {e2}")
                return topic_id, f"Tópico {topic_id}"

    async def setup_telegram_handlers():
        # telegram handlers
        @telegram_client.on(events.NewMessage(chats=canal_origem_entity))
        async def on_new_message(event):
            message = event.message
            
            try:
                topic_id = None
                if hasattr(message, 'reply_to') and message.reply_to:
                    if hasattr(message.reply_to, 'reply_to_top_id') and message.reply_to.reply_to_top_id:
                        topic_id = message.reply_to.reply_to_top_id
                        if topic_id in TOPICOS_IGNORADOS:
                            logger.info(f"Mensagem do tópico ignorado: {topic_id}")
                            return
                
                sender = await event.get_sender()
                sender_name = getattr(sender, 'first_name', '') or getattr(sender, 'title', '')
                if hasattr(sender, 'last_name') and sender.last_name:
                    sender_name += f" {sender.last_name}"
                
                if not sender_name:
                    sender_name = getattr(sender, 'username', '') or f"ID:{sender.id}"
                
                prefix = f"{sender_name} - "
                
                topic_id, topic_title = await get_topic_info(message)
                
                discord_channel = None
                
                if topic_id:
                    logger.info(f"Mensagem do tópico: {topic_title} (ID: {topic_id})")
                    discord_channel = await get_or_create_discord_channel(topic_title, topic_id)
                
                # if no topic or no channel created, use the default channel
                if not discord_channel:
                    discord_channel = discord_client.get_channel(DISCORD_CHANNEL_ID)
                
                # if has media, download and send
                if message.media:
                    logger.info(f"Mensagem com mídia detectada de {sender_name}")
                    
                    path = await message.download_media("./downloads/")
                    
                    caption = f"{prefix}{message.text}" if message.text else prefix.rstrip(" -")
                    
                    # send to discord
                    try:
                        # create discord file
                        discord_file = discord.File(path)
                        
                        # send message with file
                        await discord_channel.send(content=caption, file=discord_file)
                        logger.info(f"Mídia enviada para o canal Discord: {discord_channel.name}")
                        
                    except discord.errors.HTTPException as e:
                        # if file is too large
                        if e.status == 413: 
                            await discord_channel.send(
                                f"{caption}\n\n**[ARQUIVO MUITO GRANDE PARA SER ENVIADO]**\n"
                            )
                            logger.warning(f"Arquivo muito grande para enviar ao Discord: {path}")
                        else:
                            logger.error(f"Erro HTTP ao enviar mídia: {e}")
                            await discord_channel.send(f"{caption}\n\n**[ERRO AO ENVIAR MÍDIA]**")
                    except Exception as e:
                        logger.error(f"Erro ao enviar mídia para Discord: {e}")
                        await discord_channel.send(f"{caption}\n\n**[ERRO AO ENVIAR MÍDIA]**")
                    
                    # clean up the downloaded file
                    try:
                        os.remove(path)
                    except:
                        pass
                else:
                    formatted_text = f"{prefix}{message.text}"
                    
                    # send to discord
                    try:
                        # break the text into chunks if too long
                        if len(formatted_text) > 2000:
                            chunks = [formatted_text[i:i+1999] for i in range(0, len(formatted_text), 1999)]
                            for i, chunk in enumerate(chunks):
                                if i == 0:
                                    await discord_channel.send(chunk)
                                else:
                                    await discord_channel.send(f"(Continuação) {chunk}")
                        else:
                            await discord_channel.send(formatted_text)
                        
                        logger.info(f"Mensagem de texto enviada para o canal Discord: {discord_channel.name}")
                    except Exception as e:
                        logger.error(f"Erro ao enviar texto para Discord: {e}")
                    
            except Exception as e:
                logger.error(f"Erro ao processar mensagem: {e}")

        @telegram_client.on(events.MessageEdited(chats=canal_origem_entity))
        async def on_edit(event):
            message = event.message
            
            try:
                topic_id = None
                if hasattr(message, 'reply_to') and message.reply_to:
                    if hasattr(message.reply_to, 'reply_to_top_id') and message.reply_to.reply_to_top_id:
                        topic_id = message.reply_to.reply_to_top_id
                        if topic_id in TOPICOS_IGNORADOS:
                            logger.info(f"Mensagem do tópico ignorado: {topic_id}")
                            return
                
                sender = await event.get_sender()
                sender_name = getattr(sender, 'first_name', '') or getattr(sender, 'title', '')
                if hasattr(sender, 'last_name') and sender.last_name:
                    sender_name += f" {sender.last_name}"
                
                if not sender_name:
                    sender_name = getattr(sender, 'username', '') or f"ID:{sender.id}"
                
                prefix = f"{sender_name} - "
                
                topic_id, topic_title = await get_topic_info(message)
                
                discord_channel = None
                
                if topic_id:
                    logger.info(f"Mensagem editada do tópico: {topic_title} (ID: {topic_id})")
                    discord_channel = await get_or_create_discord_channel(topic_title, topic_id)
                
                # if no topic or no channel created, use the default channel
                if not discord_channel:
                    discord_channel = discord_client.get_channel(DISCORD_CHANNEL_ID)
                
                if message.media:
                    logger.info(f"Mensagem editada com mídia detectada de {sender_name}")
                    
                    path = await message.download_media("./downloads/")
                    
                    caption = f"[EDITADO] {prefix}{message.text}" if message.text else f"[EDITADO] {prefix}".rstrip(" -")
                    
                    # send to discord
                    try:
                        discord_file = discord.File(path)
                        await discord_channel.send(content=caption, file=discord_file)
                        logger.info(f"Mídia editada enviada para o canal Discord: {discord_channel.name}")
                    except discord.errors.HTTPException as e:
                        if e.status == 413:
                            await discord_channel.send(
                                f"{caption}\n\n**[ARQUIVO MUITO GRANDE PARA SER ENVIADO]**\n"
                            )
                        else:
                            logger.error(f"Erro HTTP ao enviar mídia editada: {e}")
                            await discord_channel.send(f"{caption}\n\n**[ERRO AO ENVIAR MÍDIA]**")
                    except Exception as e:
                        logger.error(f"Erro ao enviar mídia editada para Discord: {e}")
                        await discord_channel.send(f"{caption}\n\n**[ERRO AO ENVIAR MÍDIA EDITADA]**")
                    
                    try:
                        os.remove(path)
                    except:
                        pass
                else:
                    formatted_text = f"[EDITADO] {prefix}{message.text}"
                    
                    try:
                        if len(formatted_text) > 2000:
                            chunks = [formatted_text[i:i+1999] for i in range(0, len(formatted_text), 1999)]
                            for i, chunk in enumerate(chunks):
                                if i == 0:
                                    await discord_channel.send(chunk)
                                else:
                                    await discord_channel.send(f"(Continuação) {chunk}")
                        else:
                            await discord_channel.send(formatted_text)
                        
                        logger.info(f"Mensagem de texto editada enviada para o canal Discord: {discord_channel.name}")
                    except Exception as e:
                        logger.error(f"Erro ao enviar texto editado para Discord: {e}")
                    
            except Exception as e:
                logger.error(f"Erro ao processar mensagem editada: {e}")

        logger.info(f"Monitorando mensagens do canal Telegram {CANAL_ORIGEM}...")
        logger.info("Pressione Ctrl+C para parar")

    try:
        await telegram_client.run_until_disconnected()
    except KeyboardInterrupt:
        logger.info("Programa interrompido pelo usuário")
    finally:
        await telegram_client.disconnect()
        await discord_client.close()
        logger.info("Clientes desconectados")

if __name__ == "__main__":
    asyncio.run(main())