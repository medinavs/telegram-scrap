from telethon import TelegramClient, events, functions, types
from telethon.tl.types import InputChannel, Channel, InputPeerChannel
from telethon.errors import ChatAdminRequiredError, ChatForbiddenError
import asyncio
import os
import logging
import json
from dotenv import load_dotenv

os.makedirs("./downloads", exist_ok=True)

# configs
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

API_ID = int(os.getenv('API_ID', 0))
API_HASH = os.getenv('API_HASH', '')
SESSION_NAME = 'user_session'
CANAL_ORIGEM_STR = os.getenv('CANAL_ORIGEM', '')
CANAL_DESTINO_STR = os.getenv('CANAL_DESTINO', '')
TOPICOS_IGNORADOS_STR = os.getenv('TOPICOS_IGNORADOS', '')

# diretorio para armazenar o mapeamento de tópicos
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
    CANAL_DESTINO = int(CANAL_DESTINO_STR.strip('"').strip("'")) if CANAL_DESTINO_STR and CANAL_DESTINO_STR.strip('"').strip("'").startswith('-') else CANAL_DESTINO_STR.strip('"').strip("'")
except ValueError as e:
    logger.error(f"Erro ao converter canal: {e}")
    exit(1)

if not API_ID or not API_HASH or not CANAL_ORIGEM or not CANAL_DESTINO:
    logger.error("Por favor, configure as variáveis de ambiente API_ID, API_HASH, CANAL_ORIGEM e CANAL_DESTINO")
    exit(1)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# mapper of topics on channels
class TopicMapper:
    def __init__(self, origem_id, destino_id):
        self.origem_id = str(origem_id)
        self.destino_id = str(destino_id)
        
        #map of topics: {id_topico_origem: id_topico_destino}
        self.topic_mapping = {}
        
        # name of the file to store the mapping
        self.mapping_file = os.path.join(MAPPINGS_DIR, f"topic_mapping_{self.origem_id}_{self.destino_id}.json")
        
        # load if exists
        self._load_mapping()
    
    def _load_mapping(self):
        """Carrega o mapeamento de tópicos do arquivo"""
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
        """Salva o mapeamento de tópicos em um arquivo"""
        try:
            with open(self.mapping_file, 'w') as f:
                # stringify to serialize
                json_data = {str(k): str(v) for k, v in self.topic_mapping.items()}
                json.dump(json_data, f)
            logger.info(f"Mapeamento de tópicos salvo: {len(self.topic_mapping)} tópicos")
        except Exception as e:
            logger.error(f"Erro ao salvar mapeamento de tópicos: {e}")
    
    def get_target_topic_id(self, origem_topic_id):
        """Obtém o ID do tópico correspondente no grupo de destino"""
        return self.topic_mapping.get(origem_topic_id)
    
    def add_topic_mapping(self, origem_topic_id, destino_topic_id):
        """Adiciona um novo mapeamento de tópicos"""
        self.topic_mapping[origem_topic_id] = destino_topic_id
        self._save_mapping()
        logger.info(f"Novo mapeamento de tópico adicionado: {origem_topic_id} -> {destino_topic_id}")

async def main():
    await client.start()
    logger.info("Cliente Telegram conectado com sucesso!")
    
    # config log
    logger.info(f"CANAL_ORIGEM: {CANAL_ORIGEM}")
    logger.info(f"CANAL_DESTINO: {CANAL_DESTINO}")
    logger.info(f"TÓPICOS IGNORADOS: {TOPICOS_IGNORADOS}")

    # channels entities
    try:
        canal_origem_entity = await client.get_entity(CANAL_ORIGEM)
        canal_destino_entity = await client.get_entity(CANAL_DESTINO)
        
        origem_id = canal_origem_entity.id
        destino_id = canal_destino_entity.id
        
        logger.info(f"Canal de origem: {getattr(canal_origem_entity, 'title', CANAL_ORIGEM)} (ID: {origem_id})")
        logger.info(f"Canal de destino: {getattr(canal_destino_entity, 'title', CANAL_DESTINO)} (ID: {destino_id})")
        
        suporta_forum = False
        try:
            grupo_completo = await client(functions.channels.GetFullChannelRequest(
                channel=canal_destino_entity
            ))
            
            # check if is active
            if hasattr(grupo_completo, 'full_chat') and hasattr(grupo_completo.full_chat, 'forum_topics_active'):
                suporta_forum = grupo_completo.full_chat.forum_topics_active
            else:
                suporta_forum = isinstance(canal_destino_entity, Channel) and canal_destino_entity.megagroup
            
            logger.info(f"Canal de destino suporta fóruns: {suporta_forum}")
            
            if not suporta_forum:
                logger.warning("""
                O canal de destino não parece suportar tópicos/fóruns.
                Certifique-se de que:
                1. O grupo é um supergrupo
                2. Os fóruns estão habilitados nas configurações do grupo
                3. Você tem permissões administrativas no grupo
                
                Continuando sem criar tópicos (todas as mensagens serão enviadas ao grupo principal)
                """)
                
        except Exception as e:
            logger.warning(f"Não foi possível verificar se o canal de destino suporta fóruns: {e}")
            logger.warning("Continuando sem criar tópicos")
            suporta_forum = False
        
        # instance of the topic mapper
        topic_mapper = TopicMapper(origem_id, destino_id)
        
    except Exception as e:
        logger.error(f"Erro ao obter canais: {e}")
        await client.disconnect()
        exit(1)

    async def get_default_topic_id():
        """Tenta obter o ID do tópico 'General' ou outro padrão"""
        try:
            if not suporta_forum:
                return None
                
            forum_topics = await client(functions.channels.GetForumTopicsRequest(
                channel=canal_destino_entity,
                offset_date=0,
                offset_id=0,
                offset_topic=0,
                limit=10,
                q=""
            ))
            
            for topic in forum_topics.topics:
                if topic.title.lower() in ["general", "geral", "chat geral"]:
                    logger.info(f"Encontrado tópico padrão: {topic.title} (ID: {topic.id})")
                    return topic.id
                    
            return None
            
        except Exception as e:
            logger.error(f"Erro ao buscar tópico padrão: {e}")
            return None

    async def get_or_create_topic(topic_title, origem_topic_id):
        """
        Obtém ou cria um tópico no canal de destino com o mesmo título
        do tópico original
        """
        if not suporta_forum:
            return None
            
        destino_topic_id = topic_mapper.get_target_topic_id(origem_topic_id)
        if destino_topic_id:
            return destino_topic_id
        
        try:
            result = await client(functions.channels.CreateForumTopicRequest(
                channel=canal_destino_entity,
                title=topic_title,
                icon_color=0,  # Cor padrão
            ))
            
            new_topic_id = result.topic.id
            
            topic_mapper.add_topic_mapping(origem_topic_id, new_topic_id)
            
            logger.info(f"Novo tópico criado: '{topic_title}' (ID: {new_topic_id})")
            return new_topic_id
            
        except ChatAdminRequiredError:
            logger.error(f"Erro ao criar tópico: Permissões administrativas necessárias no grupo de destino")
            return None
        except Exception as e:
            logger.error(f"Erro ao criar tópico '{topic_title}': {e}")
            
            default_topic = await get_default_topic_id()
            if default_topic:
                topic_mapper.add_topic_mapping(origem_topic_id, default_topic)
                logger.info(f"Usando tópico padrão (ID: {default_topic}) para mensagens do tópico original: {topic_title}")
                return default_topic
                
            return None

    async def get_topic_info(message):
        """
        Extrai informações do tópico da mensagem:
        - ID do tópico
        - Título do tópico (requer consulta adicional)
        """
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
            forum_topics = await client(functions.channels.GetForumTopicsRequest(
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
            
        except Exception as e:
            logger.warning(f"Não foi possível obter título do tópico {topic_id}: {e}")
            return topic_id, f"Tópico {topic_id}"

    # events
    @client.on(events.NewMessage(chats=canal_origem_entity))
    async def on_new_message(event):
        message = event.message
        
        try:
            if hasattr(message, 'chat'):
                chat = message.chat
                chat_id = getattr(chat, 'id', 'desconhecido')
                chat_title = getattr(chat, 'title', 'desconhecido')
                logger.info(f"Origem: Chat ID {chat_id}, Título: {chat_title}")
            elif hasattr(event, 'chat'):
                chat = event.chat
                chat_id = getattr(chat, 'id', 'desconhecido')
                chat_title = getattr(chat, 'title', 'desconhecido')
                logger.info(f"Origem (via event): Chat ID {chat_id}, Título: {chat_title}")

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
            
            destino_topic_id = None
            
            if topic_id and suporta_forum:
                logger.info(f"Mensagem do tópico: {topic_title} (ID: {topic_id})")
                destino_topic_id = await get_or_create_topic(topic_title, topic_id)
            
            # if has media, download and send
            if message.media:
                logger.info(f"Mensagem com mídia detectada de {sender_name}")
                
                path = await message.download_media("./downloads/")
                
                caption = f"{prefix}{message.text}" if message.text else prefix.rstrip(" -")
                
                if destino_topic_id:
                    try:
                        await client.send_file(
                            canal_destino_entity,
                            path,
                            caption=caption,
                            reply_to=destino_topic_id
                        )
                        logger.info(f"Mídia enviada para o tópico {destino_topic_id}")
                    except Exception as e:
                        logger.error(f"Erro ao enviar mídia para tópico {destino_topic_id}: {e}")
                        await client.send_file(
                            canal_destino_entity,
                            path,
                            caption=caption
                        )
                        logger.info("Mídia enviada para o grupo principal (fallback)")
                else:
                    await client.send_file(
                        canal_destino_entity,
                        path,
                        caption=caption
                    )
                    logger.info("Mídia enviada para o grupo principal")
                
                try:
                    os.remove(path)
                except:
                    pass
            else:
                formatted_text = f"{prefix}{message.text}"
                
                if destino_topic_id:
                    try:
                        await client.send_message(
                            canal_destino_entity,
                            formatted_text,
                            reply_to=destino_topic_id
                        )
                        logger.info(f"Mensagem de texto enviada para o tópico {destino_topic_id}")
                    except Exception as e:
                        logger.error(f"Erro ao enviar mensagem para tópico {destino_topic_id}: {e}")
                        await client.send_message(canal_destino_entity, formatted_text)
                        logger.info("Mensagem de texto enviada para o grupo principal (fallback)")
                else:
                    await client.send_message(canal_destino_entity, formatted_text)
                    logger.info("Mensagem de texto enviada para o grupo principal")
                
        except Exception as e:
            logger.error(f"Erro ao encaminhar mensagem: {e}")

    @client.on(events.MessageEdited(chats=canal_origem_entity))
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
            
            destino_topic_id = None
            
            if topic_id and suporta_forum:
                logger.info(f"Mensagem editada do tópico: {topic_title} (ID: {topic_id})")
                destino_topic_id = await get_or_create_topic(topic_title, topic_id)
            
            if message.media:
                logger.info(f"Mensagem editada com mídia detectada de {sender_name}")
                
                path = await message.download_media("./downloads/")
                
                caption = f"[EDITADO] {prefix}{message.text}" if message.text else f"[EDITADO] {prefix}".rstrip(" -")
                
                if destino_topic_id:
                    try:
                        await client.send_file(
                            canal_destino_entity,
                            path,
                            caption=caption,
                            reply_to=destino_topic_id
                        )
                        logger.info(f"Mídia editada enviada para o tópico {destino_topic_id}")
                    except Exception as e:
                        logger.error(f"Erro ao enviar mídia editada para tópico {destino_topic_id}: {e}")
                        await client.send_file(
                            canal_destino_entity,
                            path,
                            caption=caption
                        )
                        logger.info("Mídia editada enviada para o grupo principal (fallback)")
                else:
                    await client.send_file(
                        canal_destino_entity,
                        path,
                        caption=caption
                    )
                    logger.info("Mídia editada enviada para o grupo principal")
                
                try:
                    os.remove(path)
                except:
                    pass
            else:
                formatted_text = f"[EDITADO] {prefix}{message.text}"
                
                if destino_topic_id:
                    try:
                        await client.send_message(
                            canal_destino_entity,
                            formatted_text,
                            reply_to=destino_topic_id
                        )
                        logger.info(f"Mensagem de texto editada enviada para o tópico {destino_topic_id}")
                    except Exception as e:
                        logger.error(f"Erro ao enviar mensagem editada para tópico {destino_topic_id}: {e}")
                        await client.send_message(canal_destino_entity, formatted_text)
                        logger.info("Mensagem de texto editada enviada para o grupo principal (fallback)")
                else:
                    await client.send_message(canal_destino_entity, formatted_text)
                    logger.info("Mensagem de texto editada enviada para o grupo principal")
                
        except Exception as e:
            logger.error(f"Erro ao processar mensagem editada: {e}")

    logger.info(f"Monitorando mensagens do canal {CANAL_ORIGEM}...")
    logger.info("Pressione Ctrl+C para parar")

    try:
        await client.run_until_disconnected()
    except KeyboardInterrupt:
        logger.info("Programa interrompido pelo usuário")
    finally:
        await client.disconnect()
        logger.info("Cliente desconectado")

if __name__ == "__main__":
    asyncio.run(main())