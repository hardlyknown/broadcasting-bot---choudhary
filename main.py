import asyncio
import os
import json
import random
import re
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.functions.messages import SendReactionRequest, ImportChatInviteRequest
from telethon.tl.functions.contacts import AddContactRequest
from telethon.tl.types import ReactionEmoji, Channel, Chat, User
from telethon.errors import FloodWaitError, InviteHashExpiredError, InviteHashInvalidError
from telethon.tl.functions.channels import JoinChannelRequest
import logging
import sys
import io
import nest_asyncio

# Windows specific fixes
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except AttributeError:
        pass  # IDLE ya koi aur IDE use ho raha hai, skip
    
nest_asyncio.apply()

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'userbot_manager.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============= CONFIGURATION =============
BOT_TOKEN = "8712979025:AAEZXRb-WdMxJ54mAtBXiRAAemKwIwNLFMk"
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"
ADMIN_IDS = [6061069578, 8574146669, 5393060599, 8104158848]

# Folders
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSIONS_DIR = os.path.join(BASE_DIR, "uploaded_sessions")
PHOTOS_DIR = os.path.join(BASE_DIR, "uploaded_photos")
DATA_FILE = os.path.join(BASE_DIR, "userbot_data234.json")

# Default settings
DEFAULT_BROADCAST_INTERVAL = 25
DEFAULT_DELAY_BETWEEN_MSGS = 1
# =========================================

class UserBotManager:
    def __init__(self):
        self.global_settings = {
            'default_interval': DEFAULT_BROADCAST_INTERVAL,
            'max_bots': 10,
            'auto_restart': False
        }
        
        self.bots = {}
        self.bot_tasks = {}
        self.ensure_directories()
        self.current_menu = {}
        self.settings = self.load_settings()
        
    def ensure_directories(self):
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        os.makedirs(PHOTOS_DIR, exist_ok=True)
        
    def load_settings(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'global_settings' not in data:
                        data['global_settings'] = self.global_settings
                    return data
            except:
                return {'global_settings': self.global_settings}
        return {'global_settings': self.global_settings}
    
    def save_settings(self):
        # self.settings mein 'global_settings' key bhi hoti hai (load se)
        # isliye pehle bot-only data nikaalo, phir global_settings upar rakho
        bot_data = {k: v for k, v in self.settings.items() if k != 'global_settings'}
        data = {
            'global_settings': self.global_settings,
            **bot_data
        }
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def get_bot_settings(self, session_name):
        if session_name not in self.settings:
            self.settings[session_name] = {
                'broadcast_message': '',
                'welcome_message': '',
                'new_name': '',
                'profile_photo': '',
                'broadcast_interval': self.global_settings['default_interval'],
                'auto_welcome': False,
                'auto_spam': False,
                'auto_vc_join': False,
                'auto_react': False,
                'auto_gc_reply': False,
                'gc_reply_message': 'Maine tumhe contacts mein add kar liya hai, ab tum mujhe DM kar sakte ho! 😊',
                'last_broadcast': None,
                'total_broadcasts': 0,
                'groups': [],
                'channels': [],
                'total_members': 0,
                'status': 'stopped',
                'joined_groups_count': 0
            }
        return self.settings[session_name]
    
    async def add_bot(self, session_file):
        session_name = os.path.basename(session_file).replace('.session', '')
        
        try:
            client = TelegramClient(session_file, API_ID, API_HASH)
            await client.start()
            me = await client.get_me()
            
            bot = UserBot(session_name, client, me, self)
            self.bots[session_name] = bot
            
            settings = self.get_bot_settings(session_name)
            bot.settings = settings
            
            logger.info(f"✅ Bot added: {session_name} - {me.first_name}")
            return bot
            
        except Exception as e:
            logger.error(f"❌ Failed to add bot {session_name}: {str(e)}")
            return None
    
    async def remove_bot(self, session_name):
        if session_name in self.bots:
            if session_name in self.bot_tasks:
                self.bot_tasks[session_name].cancel()
                try:
                    await self.bot_tasks[session_name]
                except:
                    pass
            
            await self.bots[session_name].client.disconnect()
            del self.bots[session_name]
            
            if session_name in self.bot_tasks:
                del self.bot_tasks[session_name]
            
            if session_name in self.settings:
                self.settings[session_name]['status'] = 'stopped'
                self.save_settings()
            
            logger.info(f"🔴 Bot removed: {session_name}")
            return True
        return False
    
    async def start_bot_services(self, session_name):
        if session_name in self.bot_tasks:
            self.bot_tasks[session_name].cancel()
            try:
                await self.bot_tasks[session_name]
            except:
                pass
        
        if session_name in self.bots:
            bot = self.bots[session_name]
            bot.running = True
            bot.welcomed_users = set()
            bot.gc_replied_users = set()
            bot.reacted_messages = set()
            task = asyncio.create_task(bot.run_services())
            self.bot_tasks[session_name] = task
            
            self.settings[session_name]['status'] = 'running'
            self.save_settings()
            logger.info(f"▶️ Bot {session_name} started")
    
    async def stop_bot_services(self, session_name):
        if session_name in self.bot_tasks:
            self.bot_tasks[session_name].cancel()
            try:
                await self.bot_tasks[session_name]
            except:
                pass
            del self.bot_tasks[session_name]
        
        if session_name in self.bots:
            self.bots[session_name].running = False
        
        if session_name in self.settings:
            self.settings[session_name]['status'] = 'stopped'
            self.save_settings()
        logger.info(f"⏹️ Bot {session_name} stopped")
    
    def get_all_sessions(self):
        return [f.replace('.session', '') for f in os.listdir(SESSIONS_DIR) if f.endswith('.session')]

class UserBot:
    def __init__(self, name, client, me, manager):
        self.name = name
        self.client = client
        self.me = me
        self.manager = manager
        self.settings = {}
        self.running = False
        self.groups_cache = []
        self.channels_cache = []
        self.users_cache = []
        self.dialogs_cache_time = None
        self.welcome_handler = None
        self.welcomed_users = set()
        self.gc_replied_users = set()
        self.reacted_messages = set()
        self.current_vc_chat = None
        
        # Add these for group joining tracking
        self.joining_in_progress = False
        self.total_links_to_join = 0
        self.joined_success = 0
        self.joined_failed = 0
        
        # Duplicate handler registration rokne ke liye flags
        self._welcome_handler_registered = False
        self._gc_reply_handler_registered = False
        self._vc_monitor_task = None
        
    async def run_services(self):
        logger.info(f"🚀 Starting services for {self.name}")
        self.running = True
        
        if self.settings.get('auto_welcome', False):
            await self.register_welcome_handler()
        
        if self.settings.get('auto_gc_reply', False):
            await self.register_gc_reply_handler()
        
        if self.settings.get('auto_vc_join', False):
            if self._vc_monitor_task is None or self._vc_monitor_task.done():
                self._vc_monitor_task = asyncio.create_task(self.voice_chat_monitor())
        
        broadcast_count = 0
        react_count = 0
        
        while self.running:
            try:
                broadcast_count += 1
                react_count += 1
                
                # Auto Spam
                if self.settings.get('auto_spam', False):
                    logger.info(f"📢 {self.name} - Broadcast #{broadcast_count}")
                    await self.broadcast_to_groups()
                
                # Auto React — har 60 cycle pe (react_count % 1 was always True, fixed)
                if self.settings.get('auto_react', False):
                    if react_count % 60 == 0:
                        asyncio.create_task(self.auto_react())
                
                # Interval: har second re-read karo taaki setting change hote hi effect ho
                interval = self.settings.get('broadcast_interval', DEFAULT_BROADCAST_INTERVAL)
                elapsed = 0
                while self.running and elapsed < interval:
                    await asyncio.sleep(1)
                    elapsed += 1
                    interval = self.settings.get('broadcast_interval', DEFAULT_BROADCAST_INTERVAL)
                    
            except FloodWaitError as e:
                logger.warning(f"⏳ {self.name} - Flood wait: {e.seconds}s")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                logger.error(f"❌ {self.name} - Error: {str(e)}")
                await asyncio.sleep(5)
        
        logger.info(f"⏹️ {self.name} - Services stopped")
    
    # ============= FIXED: JOIN GROUPS FROM LINKS =============
    def extract_invite_hash(self, link):
        """Extract invite hash from various Telegram link formats"""
        link = link.strip()
        
        # Remove query parameters if any
        if '?' in link:
            link = link.split('?')[0]
        
        logger.info(f"Processing link: {link}")
        
        # Handle channel links (c/ format)
        if '/c/' in link:
            channel_id = link.split('/c/')[-1].split('/')[0].split('?')[0]
            if channel_id.isdigit():
                logger.info(f"✅ Extracted channel ID: {channel_id}")
                return f"c_{channel_id}"
        
        # Check for private invite links first (these need ImportChatInviteRequest)
        private_patterns = [
            (r'(?:https?://)?(?:www\.)?t\.me/joinchat/([a-zA-Z0-9_-]+)', 1),
            (r'(?:https?://)?(?:www\.)?telegram\.me/joinchat/([a-zA-Z0-9_-]+)', 1),
            (r'(?:https?://)?(?:www\.)?telegram\.dog/joinchat/([a-zA-Z0-9_-]+)', 1),
            (r'(?:https?://)?(?:www\.)?t\.me/\+([a-zA-Z0-9_-]+)', 1),
            (r'(?:https?://)?(?:www\.)?telegram\.me/\+([a-zA-Z0-9_-]+)', 1),
            (r'joinchat/([a-zA-Z0-9_-]+)', 1),
            (r'^\+([a-zA-Z0-9_-]+)$', 1),
        ]
        
        for pattern, group_num in private_patterns:
            match = re.search(pattern, link)
            if match:
                hash_value = match.group(group_num)
                if hash_value and len(hash_value) > 3:
                    logger.info(f"✅ Extracted private hash: {hash_value}")
                    return f"private_{hash_value}"
        
        # Now handle public group links (usernames)
        public_patterns = [
            (r'(?:https?://)?(?:www\.)?t\.me/([a-zA-Z0-9_]+)', 1),
            (r'(?:https?://)?(?:www\.)?telegram\.me/([a-zA-Z0-9_]+)', 1),
            (r'^@?([a-zA-Z0-9_]+)$', 1),
        ]
        
        for pattern, group_num in public_patterns:
            match = re.search(pattern, link)
            if match:
                username = match.group(group_num)
                # Filter out common false positives
                if username.lower() not in ['share', 'joinchat', 'telegram', 'http', 'https', 'www']:
                    if len(username) >= 3:
                        logger.info(f"✅ Extracted public username: {username}")
                        return f"public_{username}"
        
        # If nothing worked, try to get last part
        if '/' in link:
            last_part = link.split('/')[-1].split('?')[0]
            if last_part and len(last_part) > 2:
                if last_part[0] == '+':
                    logger.info(f"✅ Extracted as private: {last_part}")
                    return f"private_{last_part[1:]}"
                else:
                    logger.info(f"✅ Extracted as public: {last_part}")
                    return f"public_{last_part}"
        
        logger.warning(f"❌ Could not extract hash from: {link}")
        return None

    async def join_groups_from_links(self, links_text):
        """Join multiple groups from provided links with progress tracking"""
        
        # Extract all links from text
        lines = links_text.strip().split('\n')
        links = []
        
        for line in lines:
            line = line.strip()
            if line:
                invite_data = self.extract_invite_hash(line)
                if invite_data:
                    # Parse the extracted data
                    if invite_data.startswith('private_'):
                        links.append({
                            'original': line,
                            'hash': invite_data[8:],
                            'type': 'private'
                        })
                    elif invite_data.startswith('public_'):
                        links.append({
                            'original': line,
                            'username': invite_data[7:],
                            'type': 'public'
                        })
                    elif invite_data.startswith('c_'):
                        links.append({
                            'original': line,
                            'channel_id': int(invite_data[2:]),
                            'type': 'channel'
                        })
        
        if not links:
            return False, 0, 0, "No valid Telegram invite links found!"
        
        self.joining_in_progress = True
        self.total_links_to_join = len(links)
        self.joined_success = 0
        self.joined_failed = 0
        
        logger.info(f"🔗 {self.name} - Starting to join {len(links)} groups")
        
        for i, link_data in enumerate(links, 1):
            if not self.joining_in_progress:
                break
            
            try:
                logger.info(f"Attempting to join {i}/{len(links)}: {link_data.get('username') or link_data.get('hash')}")
                
                if link_data['type'] == 'public':
                    # Join public group by username
                    try:
                        entity = await self.client.get_entity(link_data['username'])
                        if isinstance(entity, (Channel, Chat)):
                            await self.client(JoinChannelRequest(entity))
                            self.joined_success += 1
                            logger.info(f"✅ {self.name} - Joined public group: {link_data['original']}")
                        else:
                            logger.warning(f"❌ {self.name} - Not a group: {link_data['original']}")
                            self.joined_failed += 1
                    except Exception as e:
                        error_msg = str(e)
                        if "USER_ALREADY_PARTICIPANT" in error_msg:
                            logger.info(f"⚠️ {self.name} - Already in group: {link_data['original']}")
                            self.joined_success += 1
                        elif "Username not found" in error_msg:
                            logger.warning(f"❌ {self.name} - Group not found: {link_data['original']}")
                            self.joined_failed += 1
                        else:
                            logger.error(f"❌ {self.name} - Failed to join public: {error_msg}")
                            self.joined_failed += 1
                            
                elif link_data['type'] == 'private':
                    # Join private group by invite hash
                    try:
                        updates = await self.client(ImportChatInviteRequest(link_data['hash']))
                        self.joined_success += 1
                        logger.info(f"✅ {self.name} - Joined private group: {link_data['original']}")
                    except Exception as e:
                        error_msg = str(e)
                        if "USER_ALREADY_PARTICIPANT" in error_msg:
                            logger.info(f"⚠️ {self.name} - Already in group: {link_data['original']}")
                            self.joined_success += 1
                        elif "INVITE_HASH_EXPIRED" in error_msg:
                            logger.warning(f"❌ {self.name} - Invite expired: {link_data['original']}")
                            self.joined_failed += 1
                        else:
                            logger.error(f"❌ {self.name} - Failed to join private: {error_msg}")
                            self.joined_failed += 1
                            
                elif link_data['type'] == 'channel':
                    # Join channel by ID
                    try:
                        entity = await self.client.get_entity(link_data['channel_id'])
                        await self.client(JoinChannelRequest(entity))
                        self.joined_success += 1
                        logger.info(f"✅ {self.name} - Joined channel: {link_data['original']}")
                    except Exception as e:
                        logger.error(f"❌ {self.name} - Failed to join channel: {str(e)}")
                        self.joined_failed += 1
                
            except FloodWaitError as e:
                logger.warning(f"⏳ {self.name} - Flood wait: {e.seconds}s")
                self.joined_failed += 1
                await asyncio.sleep(min(e.seconds, 30))
            except Exception as e:
                logger.error(f"❌ {self.name} - Unexpected error: {str(e)}")
                self.joined_failed += 1
            
            # Delay between joins
            if i < len(links):
                await asyncio.sleep(2)
        
        self.joining_in_progress = False
        
        # Update joined groups count
        self.settings['joined_groups_count'] = self.settings.get('joined_groups_count', 0) + self.joined_success
        self.manager.save_settings()
        
        # Refresh dialogs after joining
        await self.get_all_dialogs(force_refresh=True)
        
        result_msg = f"✅ Joined: {self.joined_success} | ❌ Failed: {self.joined_failed} | Total: {len(links)}"
        return True, self.joined_success, self.joined_failed, result_msg
    
    async def get_join_progress(self):
        """Get current join progress"""
        if self.joining_in_progress:
            return {
                'in_progress': True,
                'total': self.total_links_to_join,
                'success': self.joined_success,
                'failed': self.joined_failed,
                'remaining': self.total_links_to_join - (self.joined_success + self.joined_failed)
            }
        return {'in_progress': False}
    
    async def stop_joining(self):
        """Stop ongoing join process"""
        self.joining_in_progress = False
        return True
    
    async def register_welcome_handler(self):
        # Guard: agar handler pehle se registered hai to dobara mat karo
        if self._welcome_handler_registered:
            logger.info(f"⚠️ {self.name} - Welcome handler already registered, skipping")
            return
        self._welcome_handler_registered = True
        
        @self.client.on(events.NewMessage(incoming=True))
        async def welcome_handler(event):
            try:
                if not self.running or not self.settings.get('auto_welcome', False):
                    return
                
                if not event.is_private or event.out:
                    return
                
                welcome_msg = self.settings.get('welcome_message', '')
                if not welcome_msg:
                    return
                
                sender = await event.get_sender()
                if getattr(sender, 'bot', False):
                    return
                
                user_id = sender.id
                
                if user_id in self.welcomed_users:
                    return
                
                logger.info(f"👋 {self.name} - First message from {user_id}")
                
                await asyncio.sleep(2)
                await event.reply(welcome_msg)
                
                self.welcomed_users.add(user_id)
                logger.info(f"✅ {self.name} - Welcome sent to {user_id}")
                
            except FloodWaitError as e:
                logger.warning(f"⏳ {self.name} - Welcome flood wait: {e.seconds}s")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                logger.error(f"❌ {self.name} - Welcome error: {str(e)}")
        
        self.welcome_handler = welcome_handler
        logger.info(f"✅ {self.name} - Welcome handler registered")
    
    async def register_gc_reply_handler(self):
        # Guard: agar handler pehle se registered hai to dobara mat karo
        if self._gc_reply_handler_registered:
            logger.info(f"⚠️ {self.name} - GC reply handler already registered, skipping")
            return
        self._gc_reply_handler_registered = True
        
        @self.client.on(events.NewMessage(incoming=True))
        async def gc_reply_handler(event):
            try:
                if not self.running or not self.settings.get('auto_gc_reply', False):
                    return
                
                # Only group chats, not private, not outgoing
                if event.is_private or event.out:
                    return
                
                # FIX: Sirf tabhi reply karo jab koi HAMARI message ka reply de
                if not event.is_reply:
                    return
                
                # Check karo ki replied message hamare bot ne bheji thi
                replied_msg = await event.get_reply_message()
                if not replied_msg or replied_msg.sender_id != self.me.id:
                    return
                
                sender = await event.get_sender()
                if not sender or getattr(sender, 'bot', False):
                    return
                
                user_id = sender.id
                
                # gc_replied_users: ek user ko sirf ek baar reply karo
                if user_id in self.gc_replied_users:
                    return
                
                gc_msg = self.settings.get('gc_reply_message', '')
                if not gc_msg:
                    return
                
                # Reply in GC
                await asyncio.sleep(3)
                await event.reply(gc_msg)
                self.gc_replied_users.add(user_id)
                logger.info(f"💬 {self.name} - GC replied to {user_id} (replied to our message)")
                
                # Add to contacts
                try:
                    await self.client(AddContactRequest(
                        id=sender,
                        first_name=getattr(sender, 'first_name', '') or 'User',
                        last_name=getattr(sender, 'last_name', '') or '',
                        phone='',
                        add_phone_privacy_exception=False
                    ))
                    logger.info(f"✅ {self.name} - Added {user_id} to contacts")
                except Exception as ce:
                    logger.warning(f"⚠️ {self.name} - Could not add contact {user_id}: {str(ce)}")
                
            except FloodWaitError as e:
                logger.warning(f"⏳ {self.name} - GC reply flood wait: {e.seconds}s")
                await asyncio.sleep(e.seconds)
            except Exception as e:
                logger.error(f"❌ {self.name} - GC reply error: {str(e)}")
        
        self.gc_reply_handler = gc_reply_handler
        logger.info(f"✅ {self.name} - GC reply handler registered")
    
    async def voice_chat_monitor(self):
        """Monitor and join voice chats"""
        while self.running and self.settings.get('auto_vc_join', False):
            try:
                groups, channels = await self.get_all_dialogs()
                
                for group in groups:
                    if not self.running:
                        break
                    
                    try:
                        # Check if VC is active
                        full_chat = await self.client.get_entity(group['id'])
                        
                        # Try to join VC if available
                        if hasattr(full_chat, 'call') and full_chat.call:
                            if self.current_vc_chat != group['id']:
                                logger.info(f"🎤 {self.name} - Joining VC in {group['title']}")
                                # Join voice chat (simplified)
                                self.current_vc_chat = group['id']
                                
                                # Stay in VC for random time (5-15 min)
                                await asyncio.sleep(random.randint(300, 900))
                                
                    except Exception as e:
                        logger.debug(f"VC join error in {group.get('title', 'Unknown')}: {str(e)}")
                
                # Check every 2 minutes
                await asyncio.sleep(120)
                
            except Exception as e:
                logger.error(f"VC Monitor error: {str(e)}")
                await asyncio.sleep(60)
    
    async def auto_react(self):
        """Auto react to random messages"""
        try:
            groups, channels = await self.get_all_dialogs()
            
            # Get recent messages from random group
            if groups:
                group = random.choice(groups)
                
                async for message in self.client.iter_messages(group['id'], limit=20):
                    if message.id in self.reacted_messages:
                        continue
                    
                    if message.out:
                        continue
                    
                    if message.text and len(message.text) > 0:
                        # React with heart
                        try:
                            await self.client(SendReactionRequest(
                                peer=group['id'],
                                msg_id=message.id,
                                reaction=[ReactionEmoji(emoticon="❤️")]
                            ))
                            
                            self.reacted_messages.add(message.id)
                            logger.info(f"❤️ {self.name} - Reacted to message in {group['title']}")
                            
                            # Keep set size manageable
                            if len(self.reacted_messages) > 1000:
                                self.reacted_messages = set(list(self.reacted_messages)[-500:])
                            
                            break
                        except:
                            pass
                        
        except Exception as e:
            logger.error(f"Auto react error: {str(e)}")
    
    async def get_all_dialogs(self, force_refresh=False):
        if self.dialogs_cache_time and not force_refresh:
            if datetime.now() - self.dialogs_cache_time < timedelta(minutes=5):
                return self.groups_cache, self.channels_cache
        
        groups = []
        channels = []
        users = []
        
        try:
            async for dialog in self.client.iter_dialogs():
                entity = dialog.entity
                
                if isinstance(entity, Channel):
                    if getattr(entity, 'megagroup', False):
                        groups.append({
                            'id': entity.id,
                            'title': entity.title,
                            'username': entity.username,
                            'type': 'group'
                        })
                    else:
                        channels.append({
                            'id': entity.id,
                            'title': entity.title,
                            'username': entity.username,
                            'type': 'channel'
                        })
                
                elif isinstance(entity, Chat):
                    groups.append({
                        'id': entity.id,
                        'title': entity.title,
                        'username': None,
                        'type': 'group'
                    })
                
                elif isinstance(entity, User) and not getattr(entity, 'bot', False) and not getattr(entity, 'is_self', False):
                    users.append({
                        'id': entity.id,
                        'first_name': getattr(entity, 'first_name', 'Unknown'),
                        'username': getattr(entity, 'username', None)
                    })
            
            self.groups_cache = groups
            self.channels_cache = channels
            self.users_cache = users
            self.dialogs_cache_time = datetime.now()
            
            self.settings['groups'] = groups
            self.settings['channels'] = channels
            self.settings['total_members'] = len(users)
            self.manager.save_settings()
            
            logger.info(f"📊 {self.name} - Found {len(groups)} groups, {len(channels)} channels, {len(users)} users")
            
        except Exception as e:
            logger.error(f"❌ {self.name} - Error getting dialogs: {str(e)}")
        
        return groups, channels
    
    async def broadcast_to_groups(self):
        message = self.settings.get('broadcast_message', '')
        
        if not message:
            logger.warning(f"⚠️ {self.name} - No broadcast message")
            return
        
        groups, _ = await self.get_all_dialogs()
        if not groups:
            logger.warning(f"⚠️ {self.name} - No groups to broadcast")
            return
        
        logger.info(f"📢 {self.name} - Broadcasting to {len(groups)} groups")
        success = 0
        failed = 0
        
        for i, group in enumerate(groups, 1):
            if not self.running:
                break
            
            try:
                await self.client.send_message(group['id'], message)
                success += 1
                logger.info(f"✅ {self.name} - Sent to {i}/{len(groups)}: {group['title']}")
                
                if i < len(groups):
                    await asyncio.sleep(DEFAULT_DELAY_BETWEEN_MSGS)
                    
            except FloodWaitError as e:
                logger.warning(f"⏳ {self.name} - Flood wait: {e.seconds}s")
                await asyncio.sleep(e.seconds)
                failed += 1
            except Exception as e:
                logger.error(f"❌ {self.name} - Failed to {group['title']}: {str(e)}")
                failed += 1
        
        self.settings['last_broadcast'] = datetime.now().isoformat()
        self.settings['total_broadcasts'] = self.settings.get('total_broadcasts', 0) + 1
        self.manager.save_settings()
        
        logger.info(f"📊 {self.name} - Broadcast complete: {success} success, {failed} failed")
        return success, failed
    
    async def post_to_channel(self, channel_id, message, file=None):
        try:
            if file:
                await self.client.send_file(channel_id, file, caption=message)
            else:
                await self.client.send_message(channel_id, message)
            return True, "Posted successfully!"
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    async def change_name(self, new_name):
        try:
            parts = new_name.strip().split(' ', 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ''
            
            await self.client(UpdateProfileRequest(
                first_name=first_name,
                last_name=last_name
            ))
            
            self.settings['new_name'] = new_name
            self.manager.save_settings()
            return True, "Name changed successfully!"
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    async def change_profile_photo(self, photo_path):
        try:
            file = await self.client.upload_file(photo_path)
            await self.client(UploadProfilePhotoRequest(file=file))
            
            self.settings['profile_photo'] = photo_path
            self.manager.save_settings()
            
            logger.info(f"✅ {self.name} - Profile photo changed")
            return True, "Profile photo changed successfully!"
            
        except FloodWaitError as e:
            return False, f"Flood wait: {e.seconds} seconds"
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    async def remove_profile_photo(self):
        try:
            photos = await self.client.get_profile_photos('me')
            if photos:
                await self.client(DeletePhotosRequest(id=[photos[0]]))
                
            self.settings['profile_photo'] = ''
            self.manager.save_settings()
            
            return True, "Profile photo removed successfully!"
        except Exception as e:
            return False, f"Error: {str(e)}"

# ============= TELEGRAM BOT =============
bot = TelegramClient(os.path.join(BASE_DIR, 'manager_bot'), API_ID, API_HASH)
manager = UserBotManager()

def is_admin(user_id):
    return user_id in ADMIN_IDS

# ============= SMART JOIN HELPERS =============
def _is_invalid_link_error(e):
    err = str(e).lower()
    err_type = type(e).__name__
    invalid_types = {
        "UsernameInvalidError", "UsernameNotOccupiedError",
        "InviteHashInvalidError", "InviteHashExpiredError",
        "ChannelInvalidError", "PeerIdInvalidError",
    }
    if err_type in invalid_types:
        return True
    invalid_phrases = ["username invalid", "invite hash invalid", "invite hash expired",
                       "no user", "channel invalid", "username not occupied"]
    return any(p in err for p in invalid_phrases)


async def _try_join_link(client, session_name, link, notify_event=None):
    """
    Single link join attempt.
    Returns: 'ok', 'invalid', 'retry', 'flood'
    """
    link = link.strip()
    if not link:
        return "invalid"
    try:
        if 't.me/+' in link or 'joinchat' in link:
            hash_part = link.split('+')[-1] if '+' in link else link.split('joinchat/')[-1]
            hash_part = hash_part.strip('/')
            await client(ImportChatInviteRequest(hash_part))
        else:
            username = link.replace('https://t.me/', '').replace('http://t.me/', '')
            username = username.replace('t.me/', '').replace('@', '').strip('/')
            entity = await client.get_entity(username)
            await client(JoinChannelRequest(entity))
        return "ok"
    except FloodWaitError as e:
        wait_time = e.seconds + 30
        if notify_event:
            try:
                await bot.send_message(notify_event, f"⏳ {session_name}: FloodWait {wait_time}s, waiting...")
            except:
                pass
        await asyncio.sleep(wait_time)
        return "flood"
    except (InviteHashExpiredError, InviteHashInvalidError):
        return "invalid"
    except Exception as e:
        if _is_invalid_link_error(e):
            return "invalid"
        return "retry"


async def smart_join_task(links_text, admin_chat_id, join_mode="random"):
    """
    join_mode='random': links distribute across all active bots. Fail -> retry with another bot.
    join_mode='all':    har active bot sabhi links join karta hai.
    """
    active_bots = list(manager.bots.values())
    if not active_bots:
        await bot.send_message(admin_chat_id, "❌ No active bots! Pehle koi bot activate karo.")
        return

    lines = [l.strip() for l in links_text.strip().split('\n') if l.strip()]
    if not lines:
        await bot.send_message(admin_chat_id, "❌ No valid links found!")
        return

    await bot.send_message(
        admin_chat_id,
        f"🔗 **Smart Join Started**\n\nMode: {'Join All' if join_mode == 'all' else 'Random Distribution'}\n"
        f"Links: {len(lines)} | Bots: {len(active_bots)}"
    )

    total_ok = 0
    total_fail = 0

    if join_mode == "all":
        for bot_instance in active_bots:
            client = bot_instance.client
            sname = bot_instance.name
            for link in lines:
                result = await _try_join_link(client, sname, link, admin_chat_id)
                if result == "ok":
                    await bot.send_message(admin_chat_id, f"✅ {sname} joined {link}")
                    total_ok += 1
                    await asyncio.sleep(3)
                elif result == "flood":
                    result2 = await _try_join_link(client, sname, link, admin_chat_id)
                    if result2 == "ok":
                        await bot.send_message(admin_chat_id, f"✅ {sname} joined {link} (after flood wait)")
                        total_ok += 1
                    else:
                        await bot.send_message(admin_chat_id, f"❌ {sname} failed {link}")
                        total_fail += 1
                    await asyncio.sleep(3)
                elif result == "invalid":
                    await bot.send_message(admin_chat_id, f"⚠️ Invalid/expired link, skipping all: {link}")
                    total_fail += 1
                    break  # skip this link for remaining bots too
                else:
                    await bot.send_message(admin_chat_id, f"❌ {sname} failed {link}")
                    total_fail += 1
                    await asyncio.sleep(2)

    else:  # random distribution
        per_bot = max(1, len(lines) // len(active_bots))
        remainder = len(lines) % len(active_bots)
        start = 0
        assignments = {}
        for i, bot_instance in enumerate(active_bots):
            count = per_bot + (1 if i < remainder else 0)
            assignments[bot_instance.name] = (bot_instance, lines[start:start + count])
            start += count

        for sname, (bot_instance, assigned_links) in assignments.items():
            client = bot_instance.client
            for link in assigned_links:
                result = await _try_join_link(client, sname, link, admin_chat_id)

                if result == "ok":
                    await bot.send_message(admin_chat_id, f"✅ {sname} joined {link}")
                    total_ok += 1
                    await asyncio.sleep(3)

                elif result == "flood":
                    result2 = await _try_join_link(client, sname, link, admin_chat_id)
                    if result2 == "ok":
                        await bot.send_message(admin_chat_id, f"✅ {sname} joined {link} (post-flood)")
                        total_ok += 1
                    else:
                        await bot.send_message(admin_chat_id, f"❌ {sname} failed {link} after flood")
                        total_fail += 1
                    await asyncio.sleep(3)

                elif result == "invalid":
                    await bot.send_message(admin_chat_id, f"⚠️ Invalid/expired, skipped: {link}")
                    total_fail += 1

                else:  # retry with other bots
                    await bot.send_message(admin_chat_id, f"⚠️ {sname} failed {link}, trying others...")
                    other_bots = [b for n, (b, _) in assignments.items() if n != sname]
                    joined = False
                    for other in other_bots:
                        r2 = await _try_join_link(other.client, other.name, link, admin_chat_id)
                        if r2 == "ok":
                            await bot.send_message(admin_chat_id, f"✅ {other.name} joined {link} (retry)")
                            total_ok += 1
                            joined = True
                            await asyncio.sleep(3)
                            break
                        elif r2 == "invalid":
                            await bot.send_message(admin_chat_id, f"⚠️ Invalid link, skipped: {link}")
                            total_fail += 1
                            joined = True
                            break
                    if not joined:
                        await bot.send_message(admin_chat_id, f"❌ All bots failed for {link}")
                        total_fail += 1
                    await asyncio.sleep(2)

    await bot.send_message(
        admin_chat_id,
        f"✅ **Smart Join Complete!**\n\n✅ Joined: {total_ok}\n❌ Failed: {total_fail}"
    )


# ============= MAIN MENU =============
async def main_menu(event, edit=False):
    text = """
🤖 **UserBot Manager - v5.3**

🔹 **Upload Session** - Add new userbot
🔹 **My Bots** - Manage existing bots
🔹 **Settings** - Configure global settings

Select an option below:
"""
    buttons = [
        [Button.inline("📤 Upload Session", b"upload")],
        [Button.inline("🤖 My Bots", b"my_bots")],
        [Button.inline("🔗 Smart Join", b"smart_join")],
        [Button.inline("⚙️ Settings", b"settings")],
        [Button.inline("📊 Status", b"status")]
    ]
    
    if edit:
        await event.edit(text, buttons=buttons)
    else:
        await event.reply(text, buttons=buttons)

# ============= SETTINGS MENU =============
async def settings_menu(event):
    text = f"""
⚙️ **Global Settings**

• Default Interval: `{manager.global_settings['default_interval']}s`
• Max Bots: `{manager.global_settings['max_bots']}`
• Auto Restart: `{'✅' if manager.global_settings['auto_restart'] else '❌'}`

Select an option:
"""
    buttons = [
        [Button.inline("⏱️ Set Default Interval", b"set_default_interval")],
        [Button.inline("📊 Set Max Bots", b"set_max_bots")],
        [Button.inline("🔄 Toggle Auto Restart", b"toggle_auto_restart")],
        [Button.inline("🔙 Back to Menu", b"back_to_menu")]
    ]
    
    await event.edit(text, buttons=buttons)

# ============= START COMMAND =============
@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    if not is_admin(event.sender_id):
        await event.reply("❌ Unauthorized!")
        return
    await main_menu(event)

# ============= UPLOAD SESSION =============
@bot.on(events.CallbackQuery(data=b'upload'))
async def upload_callback(event):
    if not is_admin(event.sender_id):
        await event.answer("❌ Unauthorized!")
        return
    
    await event.edit(
        "📤 **Upload Session File**\n\n"
        "Please send the `.session` file now.",
        buttons=[Button.inline("🔙 Back to Menu", b"back_to_menu")]
    )
    manager.current_menu[event.sender_id] = 'waiting_session'

# ============= SMART JOIN =============
@bot.on(events.CallbackQuery(data=b'smart_join'))
async def smart_join_callback(event):
    if not is_admin(event.sender_id):
        await event.answer("❌ Unauthorized!")
        return
    
    active_count = len(manager.bots)
    await event.edit(
        f"🔗 **Smart Join**\n\n"
        f"Active bots: {active_count}\n\n"
        f"**Random Distribution** — links sare bots mein baant deta hai. Fail hone pe doosra bot retry karta hai.\n\n"
        f"**Join All** — har bot sabhi links join karta hai.",
        buttons=[
            [Button.inline("🎲 Random Distribution", b"smartjoin_random")],
            [Button.inline("📢 Join All (har bot sab links)", b"smartjoin_all")],
            [Button.inline("🔙 Back", b"back_to_menu")]
        ]
    )

@bot.on(events.CallbackQuery(data=b'smartjoin_random'))
async def smartjoin_random_callback(event):
    if not is_admin(event.sender_id):
        return
    await event.edit(
        "📝 **Smart Join — Random Distribution**\n\nLinks bhejo (ek per line):\n\n"
        "Supports:\n`t.me/+inviteHash`\n`t.me/username`\n`@username`",
        buttons=[Button.inline("🔙 Cancel", b"smart_join")]
    )
    manager.current_menu[event.sender_id] = 'waiting_smartjoin_random'

@bot.on(events.CallbackQuery(data=b'smartjoin_all'))
async def smartjoin_all_callback(event):
    if not is_admin(event.sender_id):
        return
    await event.edit(
        "📝 **Smart Join — Join All**\n\nLinks bhejo (ek per line):\n\n"
        "Supports:\n`t.me/+inviteHash`\n`t.me/username`\n`@username`",
        buttons=[Button.inline("🔙 Cancel", b"smart_join")]
    )
    manager.current_menu[event.sender_id] = 'waiting_smartjoin_all'

# ============= MAIN CALLBACK HANDLER =============
@bot.on(events.CallbackQuery)
async def callback_handler(event):
    try:
        if not is_admin(event.sender_id):
            await event.answer("❌ Unauthorized!")
            return

        data = event.data

        if data == b'back_to_menu':
            await main_menu(event, edit=True)
            return

        if data == b'status':
            await show_status(event)
            return

        if data == b'my_bots':
            await my_bots(event)
            return

        if data == b'settings':
            await settings_menu(event)
            return

        if data == b'set_default_interval':
            await event.edit(
                "⏱️ **Set Default Interval**\n\nSend interval in seconds (min 5):",
                buttons=[Button.inline("🔙 Cancel", b"settings")]
            )
            manager.current_menu[event.sender_id] = 'waiting_default_interval'
            return

        if data == b'set_max_bots':
            await event.edit(
                "📊 **Set Max Bots**\n\nSend maximum number of bots:",
                buttons=[Button.inline("🔙 Cancel", b"settings")]
            )
            manager.current_menu[event.sender_id] = 'waiting_max_bots'
            return

        if data == b'toggle_auto_restart':
            manager.global_settings['auto_restart'] = not manager.global_settings['auto_restart']
            manager.save_settings()
            await event.answer(f"✅ Auto Restart: {'ON' if manager.global_settings['auto_restart'] else 'OFF'}")
            await settings_menu(event)
            return

        data_str = data.decode('utf-8')

        if data_str.startswith('bot_'):
            session_name = data_str.replace('bot_', '')
            await bot_details(event, session_name)
            return

        if data_str.startswith('activate_'):
            session_name = data_str.replace('activate_', '')
            await activate_bot(event, session_name)
            return

        if data_str.startswith('start_'):
            session_name = data_str.replace('start_', '')
            await start_bot(event, session_name)
            return

        if data_str.startswith('stop_'):
            session_name = data_str.replace('stop_', '')
            await stop_bot(event, session_name)
            return

        if data_str.startswith('togglespam_'):
            session_name = data_str.replace('togglespam_', '')
            await toggle_spam(event, session_name)
            return

        if data_str.startswith('togglewelcome_'):
            session_name = data_str.replace('togglewelcome_', '')
            await toggle_welcome(event, session_name)
            return

        if data_str.startswith('togglevc_'):
            session_name = data_str.replace('togglevc_', '')
            await toggle_vc(event, session_name)
            return

        if data_str.startswith('togglereact_'):
            session_name = data_str.replace('togglereact_', '')
            await toggle_react(event, session_name)
            return

        if data_str.startswith('togglegcreply_'):
            session_name = data_str.replace('togglegcreply_', '')
            await toggle_gc_reply(event, session_name)
            return

        if data_str.startswith('setgcreply_'):
            session_name = data_str.replace('setgcreply_', '')
            await setgcreply_prompt(event, session_name)
            return

        # Add to Groups button handler
        if data_str.startswith('addtogroups_'):
            session_name = data_str.replace('addtogroups_', '')
            await add_to_groups_prompt(event, session_name)
            return

        # Check join progress
        if data_str.startswith('progress_'):
            session_name = data_str.replace('progress_', '')
            await check_join_progress(event, session_name)
            return

        # Stop joining process
        if data_str.startswith('stopjoin_'):
            session_name = data_str.replace('stopjoin_', '')
            await stop_joining(event, session_name)
            return

        if data_str.startswith('setmsg_'):
            session_name = data_str.replace('setmsg_', '')
            await setmsg_prompt(event, session_name)
            return

        if data_str.startswith('setwelcome_'):
            session_name = data_str.replace('setwelcome_', '')
            await setwelcome_prompt(event, session_name)
            return

        if data_str.startswith('setname_'):
            session_name = data_str.replace('setname_', '')
            await setname_prompt(event, session_name)
            return

        if data_str.startswith('setphoto_'):
            session_name = data_str.replace('setphoto_', '')
            await setphoto_prompt(event, session_name)
            return

        if data_str.startswith('removephoto_'):
            session_name = data_str.replace('removephoto_', '')
            await remove_photo(event, session_name)
            return

        if data_str.startswith('setinterval_'):
            session_name = data_str.replace('setinterval_', '')
            await setinterval_prompt(event, session_name)
            return

        if data_str.startswith('channels_'):
            session_name = data_str.replace('channels_', '')
            await list_channels(event, session_name)
            return

        if data_str.startswith('post_'):
            parts = data_str.split('_')
            if len(parts) >= 3:
                session_name = parts[1]
                channel_id = int(parts[2])
                await post_to_channel_prompt(event, session_name, channel_id)
            return

        if data_str.startswith('refresh_'):
            session_name = data_str.replace('refresh_', '')
            await refresh_stats(event, session_name)
            return

        if data_str.startswith('delete_'):
            session_name = data_str.replace('delete_', '')
            await delete_bot(event, session_name)
            return

        if data_str.startswith('confirm_delete_'):
            session_name = data_str.replace('confirm_delete_', '')
            await confirm_delete(event, session_name)
            return

    # ============= ADD TO GROUPS FUNCTIONS =============
    except Exception as e:
        err = str(e)
        if 'MessageNotModified' in err or 'not modified' in err.lower():
            pass
        elif 'readonly database' in err.lower():
            import logging as _l; _l.getLogger(__name__).warning(f'⚠️ SQLite readonly — {err}')
        else:
            import logging as _l; _l.getLogger(__name__).error(f'❌ callback_handler: {err}')

async def add_to_groups_prompt(event, session_name):
    """Prompt user to send group links"""
    await event.edit(
        f"🔗 **Add {session_name} to Groups**\n\n"
        f"Send the group invite links (one per line):\n\n"
        f"Example:\n"
        f"https://t.me/joinchat/AAAAAE123456\n"
        f"https://t.me/group123\n"
        f"t.me/group456\n"
        f"t.me/+AbCdEfGhIjK\n\n"
        f"Bot will show progress after you send.",
        buttons=[
            [Button.inline("🔙 Cancel", f"bot_{session_name}".encode())]
        ]
    )
    manager.current_menu[event.sender_id] = f'waiting_grouplinks_{session_name}'

async def check_join_progress(event, session_name):
    """Check current join progress"""
    if session_name in manager.bots:
        bot = manager.bots[session_name]
        progress = await bot.get_join_progress()
        
        if progress['in_progress']:
            percentage = ((progress['success'] + progress['failed']) / progress['total'] * 100)
            text = f"""
📊 **Join Progress - {session_name}**

• Total Links: {progress['total']}
• ✅ Success: {progress['success']}
• ❌ Failed: {progress['failed']}
• ⏳ Remaining: {progress['remaining']}

Progress: {percentage:.1f}%
"""
            buttons = [
                [Button.inline("🔄 Refresh", f"progress_{session_name}".encode())],
                [Button.inline("⏹️ Stop Joining", f"stopjoin_{session_name}".encode())],
                [Button.inline("🔙 Back", f"bot_{session_name}".encode())]
            ]
        else:
            text = "📭 No joining process in progress."
            buttons = [[Button.inline("🔙 Back to Bot", f"bot_{session_name}".encode())]]
        
        await event.edit(text, buttons=buttons)

async def stop_joining(event, session_name):
    """Stop ongoing join process"""
    if session_name in manager.bots:
        bot = manager.bots[session_name]
        await bot.stop_joining()
        await event.answer("⏹️ Joining stopped!")
        await bot_details(event, session_name)

# ============= TOGGLE FUNCTIONS =============
async def toggle_vc(event, session_name):
    if session_name in manager.bots:
        bot = manager.bots[session_name]
        bot.settings['auto_vc_join'] = not bot.settings.get('auto_vc_join', False)
        
        # Agar ON kiya aur bot chal raha hai to monitor abhi start karo
        if bot.settings['auto_vc_join'] and bot.running:
            if bot._vc_monitor_task is None or bot._vc_monitor_task.done():
                bot._vc_monitor_task = asyncio.create_task(bot.voice_chat_monitor())
        
        manager.save_settings()
        await event.answer(f"🎤 VC Auto Join: {'ON' if bot.settings['auto_vc_join'] else 'OFF'}")
        await bot_details(event, session_name)

async def toggle_react(event, session_name):
    if session_name in manager.bots:
        bot = manager.bots[session_name]
        bot.settings['auto_react'] = not bot.settings.get('auto_react', False)
        manager.save_settings()
        await event.answer(f"❤️ Auto React: {'ON' if bot.settings['auto_react'] else 'OFF'}")
        await bot_details(event, session_name)

async def toggle_gc_reply(event, session_name):
    if session_name in manager.bots:
        bot = manager.bots[session_name]
        bot.settings['auto_gc_reply'] = not bot.settings.get('auto_gc_reply', False)
        
        if bot.settings['auto_gc_reply']:
            await bot.register_gc_reply_handler()
        else:
            bot.gc_replied_users.clear()
        
        manager.save_settings()
        await event.answer(f"💬 GC Reply: {'ON' if bot.settings['auto_gc_reply'] else 'OFF'}")
        await bot_details(event, session_name)

async def setgcreply_prompt(event, session_name):
    await event.edit(
        f"💬 **Set GC Reply Message**\n\n"
        f"Yeh message GC mein reply karne ke liye use hoga.\n"
        f"User ko contact mein bhi add kar liya jayega automatically.\n\n"
        f"Send the message:",
        buttons=[Button.inline("🔙 Cancel", f"bot_{session_name}".encode())]
    )
    manager.current_menu[event.sender_id] = f'waiting_gcreply_{session_name}'

async def list_channels(event, session_name):
    if session_name not in manager.bots:
        await event.edit("❌ Bot not active!", buttons=[Button.inline("🔙 Back", b"my_bots")])
        return
    
    bot = manager.bots[session_name]
    await bot.get_all_dialogs(force_refresh=True)
    channels = bot.settings.get('channels', [])
    
    if not channels:
        await event.edit(f"📭 No channels found for {session_name}",
                        buttons=[Button.inline("🔙 Back", f"bot_{session_name}".encode())])
        return
    
    text = f"📢 **Channels of {session_name}**\n\nSelect channel to post:\n"
    buttons = []
    
    for channel in channels[:10]:
        buttons.append([Button.inline(
            f"📺 {channel['title'][:30]}",
            f"post_{session_name}_{channel['id']}".encode()
        )])
    
    buttons.append([Button.inline("🔙 Back to Bot", f"bot_{session_name}".encode())])
    await event.edit(text, buttons=buttons)

async def post_to_channel_prompt(event, session_name, channel_id):
    await event.edit(
        f"📝 **Send Post**\n\nSend the message (with optional photo):",
        buttons=[Button.inline("🔙 Cancel", f"channels_{session_name}".encode())]
    )
    manager.current_menu[event.sender_id] = f'waiting_post_{session_name}_{channel_id}'

# ============= HANDLE INPUTS =============
@bot.on(events.NewMessage)
async def handle_input(event):
    if not is_admin(event.sender_id):
        return
    
    if event.sender_id not in manager.current_menu:
        return
    
    state = manager.current_menu[event.sender_id]
    
    if state == 'waiting_session':
        if event.document:
            file_path = await event.download_media(file=SESSIONS_DIR)
            
            if file_path and file_path.endswith('.session'):
                await event.reply("⏳ **Adding session...**")
                bot_instance = await manager.add_bot(file_path)
                
                if bot_instance:
                    await event.reply(
                        f"✅ **Session Added!**\n\n"
                        f"**Name:** {bot_instance.me.first_name}\n"
                        f"**Username:** @{bot_instance.me.username}",
                        buttons=[[Button.inline("🔙 Back to Menu", b"back_to_menu")]]
                    )
                else:
                    await event.reply("❌ Failed to add session!", 
                                    buttons=[[Button.inline("🔙 Back to Menu", b"back_to_menu")]])
                    if os.path.exists(file_path):
                        os.remove(file_path)
            else:
                await event.reply("❌ Please send a valid `.session` file!",
                                buttons=[[Button.inline("🔙 Back to Menu", b"back_to_menu")]])
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
        else:
            await event.reply("❌ Please send a `.session` file!",
                            buttons=[[Button.inline("🔙 Back to Menu", b"back_to_menu")]])
        
        manager.current_menu.pop(event.sender_id, None)
        return
    
    # Handle smart join inputs
    if state in ('waiting_smartjoin_random', 'waiting_smartjoin_all'):
        if not event.text:
            await event.reply("❌ Text mein links bhejo!")
            manager.current_menu.pop(event.sender_id, None)
            return
        
        join_mode = 'random' if state == 'waiting_smartjoin_random' else 'all'
        links_text = event.text
        valid_count = len([l for l in links_text.strip().split('\n') if l.strip()])
        
        await event.reply(
            f"⏳ **Smart Join starting...**\n\nMode: {'Random Distribution' if join_mode == 'random' else 'Join All'}\nLinks: {valid_count}",
            buttons=[[Button.inline("🔙 Back to Menu", b"back_to_menu")]]
        )
        
        asyncio.create_task(smart_join_task(links_text, event.chat_id, join_mode))
        manager.current_menu.pop(event.sender_id, None)
        return
    
    # Handle group links input
    if state.startswith('waiting_grouplinks_'):
        session_name = state.replace('waiting_grouplinks_', '')
        
        if session_name in manager.bots:
            bot = manager.bots[session_name]
            links_text = event.text
            
            # Count total links properly
            links_list = links_text.strip().split('\n')
            valid_links = [l for l in links_list if l.strip()]
            total_links = len(valid_links)
            
            # Send initial progress message
            progress_msg = await event.reply(
                f"🔗 **Starting to join groups for {session_name}...**\n\n"
                f"Processing {total_links} links...\n"
                f"This may take a few moments."
            )
            
            # Start joining process
            success, joined, failed, message = await bot.join_groups_from_links(links_text)
            
            # Update progress message
            if success:
                await progress_msg.edit(
                    f"✅ **Join Process Complete!**\n\n"
                    f"📊 **Results:**\n"
                    f"• Total: {joined + failed}\n"
                    f"• ✅ Joined: {joined}\n"
                    f"• ❌ Failed: {failed}\n\n"
                    f"{message}\n\n"
                    f"Groups joined: {bot.settings.get('joined_groups_count', 0)} total",
                    buttons=[Button.inline("🔙 Back to Bot", f"bot_{session_name}".encode())]
                )
            else:
                await progress_msg.edit(
                    f"❌ {message}",
                    buttons=[Button.inline("🔙 Back to Bot", f"bot_{session_name}".encode())]
                )
        
        manager.current_menu.pop(event.sender_id, None)
        return
    
    if state.startswith('waiting_photo_'):
        session_name = state.replace('waiting_photo_', '')
        
        if event.photo or event.document:
            photo_path = await event.download_media(file=PHOTOS_DIR)
            
            if photo_path:
                await event.reply("⏳ **Changing profile photo...**")
                
                if session_name in manager.bots:
                    success, message = await manager.bots[session_name].change_profile_photo(photo_path)
                    
                    await event.reply(
                        f"{'✅' if success else '❌'} **{message}**",
                        buttons=[Button.inline("🔙 Back to Bot", f"bot_{session_name}".encode())]
                    )
                
                if os.path.exists(photo_path):
                    os.remove(photo_path)
            else:
                await event.reply("❌ Failed to download photo!",
                                buttons=[Button.inline("🔙 Back to Bot", f"bot_{session_name}".encode())])
        else:
            await event.reply("❌ Please send a photo!",
                            buttons=[Button.inline("🔙 Back to Bot", f"bot_{session_name}".encode())])
        
        manager.current_menu.pop(event.sender_id, None)
        return
    
    if state.startswith('waiting_post_'):
        parts = state.split('_')
        if len(parts) >= 4:
            session_name = parts[2]
            channel_id = int(parts[3])
            
            if session_name in manager.bots:
                message = event.text
                file = None
                
                if event.photo or event.document:
                    file = await event.download_media(file=PHOTOS_DIR)
                
                success, result = await manager.bots[session_name].post_to_channel(channel_id, message, file)
                
                if file and os.path.exists(file):
                    os.remove(file)
                
                await event.reply(f"{'✅' if success else '❌'} {result}",
                                buttons=[Button.inline("🔙 Back to Channels", f"channels_{session_name}".encode())])
        
        manager.current_menu.pop(event.sender_id, None)
        return
    
    if state == 'waiting_default_interval':
        try:
            interval = int(event.text)
            if interval < 5:
                await event.reply("⚠️ Minimum interval is 5 seconds!")
            else:
                manager.global_settings['default_interval'] = interval
                manager.save_settings()
                await event.reply(f"✅ Default interval set to {interval}s",
                                buttons=[Button.inline("🔙 Back to Settings", b"settings")])
        except ValueError:
            await event.reply("❌ Please send a valid number!")
        
        manager.current_menu.pop(event.sender_id, None)
        return
    
    if state == 'waiting_max_bots':
        try:
            max_bots = int(event.text)
            if max_bots < 1:
                await event.reply("⚠️ Minimum is 1 bot!")
            else:
                manager.global_settings['max_bots'] = max_bots
                manager.save_settings()
                await event.reply(f"✅ Max bots set to {max_bots}",
                                buttons=[Button.inline("🔙 Back to Settings", b"settings")])
        except ValueError:
            await event.reply("❌ Please send a valid number!")
        
        manager.current_menu.pop(event.sender_id, None)
        return
    
    if state.startswith('waiting_msg_'):
        session_name = state.replace('waiting_msg_', '')
        if session_name in manager.bots:
            manager.bots[session_name].settings['broadcast_message'] = event.text
            manager.save_settings()
            await event.reply("✅ Broadcast message saved!",
                            buttons=[Button.inline("🔙 Back to Bot", f"bot_{session_name}".encode())])
        manager.current_menu.pop(event.sender_id, None)
        return
    
    if state.startswith('waiting_welcome_'):
        session_name = state.replace('waiting_welcome_', '')
        if session_name in manager.bots:
            manager.bots[session_name].settings['welcome_message'] = event.text
            manager.save_settings()
            await event.reply("✅ Welcome message saved!",
                            buttons=[Button.inline("🔙 Back to Bot", f"bot_{session_name}".encode())])
        manager.current_menu.pop(event.sender_id, None)
        return
    
    if state.startswith('waiting_gcreply_'):
        session_name = state.replace('waiting_gcreply_', '')
        if session_name in manager.bots:
            manager.bots[session_name].settings['gc_reply_message'] = event.text
            manager.save_settings()
            await event.reply("✅ GC reply message saved!",
                            buttons=[Button.inline("🔙 Back to Bot", f"bot_{session_name}".encode())])
        manager.current_menu.pop(event.sender_id, None)
        return
    
    if state.startswith('waiting_name_'):
        session_name = state.replace('waiting_name_', '')
        if session_name in manager.bots:
            success, result = await manager.bots[session_name].change_name(event.text)
            await event.reply(f"{'✅' if success else '❌'} {result}",
                            buttons=[Button.inline("🔙 Back to Bot", f"bot_{session_name}".encode())])
        manager.current_menu.pop(event.sender_id, None)
        return
    
    if state.startswith('waiting_interval_'):
        session_name = state.replace('waiting_interval_', '')
        try:
            interval = int(event.text)
            if interval < 5:
                await event.reply("⚠️ Minimum interval is 5 seconds!")
            else:
                # Active bot mein bhi save karo
                if session_name in manager.bots:
                    manager.bots[session_name].settings['broadcast_interval'] = interval
                # Settings dict mein bhi directly save karo (inactive bot ke liye)
                if session_name in manager.settings:
                    manager.settings[session_name]['broadcast_interval'] = interval
                manager.save_settings()
                await event.reply(f"✅ Interval set to {interval}s",
                                buttons=[Button.inline("🔙 Back to Bot", f"bot_{session_name}".encode())])
        except ValueError:
            await event.reply("❌ Please send a valid number!")
        manager.current_menu.pop(event.sender_id, None)
        return

# ============= MY BOTS =============
async def my_bots(event):
    uploaded = manager.get_all_sessions()
    active = list(manager.bots.keys())
    
    if not uploaded:
        await event.edit("📂 **No Sessions Found**\n\nUpload a session file first.",
                        buttons=[Button.inline("🔙 Back to Menu", b"back_to_menu")])
        return
    
    buttons = []
    row = []
    
    for session in uploaded:
        status = "🟢" if session in active else "🔴"
        row.append(Button.inline(f"{status} {session}", f"bot_{session}".encode()))
        if len(row) == 2:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    buttons.append([Button.inline("🔙 Back to Menu", b"back_to_menu")])
    
    await event.edit(
        f"🤖 **My Bots**\n\nTotal: {len(uploaded)} | Active: {len(active)}",
        buttons=buttons
    )

# ============= BOT DETAILS =============
async def bot_details(event, session_name):
    if session_name not in manager.bots:
        await event.edit(
            f"⚠️ **Bot {session_name} is not active**\n\nActivate it?",
            buttons=[
                [Button.inline("✅ Activate", f"activate_{session_name}".encode())],
                [Button.inline("🗑️ Delete", f"delete_{session_name}".encode())],
                [Button.inline("🔙 Back", b"my_bots")]
            ]
        )
        return
    
    bot = manager.bots[session_name]
    settings = bot.settings
    
    # Check if joining in progress
    join_status = ""
    if bot.joining_in_progress:
        join_status = f"\n🔄 **Joining in progress...** ({bot.joined_success + bot.joined_failed}/{bot.total_links_to_join})"
    
    text = f"""
🤖 **Bot: {session_name}**

📊 **Statistics:**
• Status: {'🟢 Running' if settings.get('status') == 'running' else '🔴 Stopped'}
• Groups: {len(settings.get('groups', []))}
• Channels: {len(settings.get('channels', []))}
• DMs: {settings.get('total_members', 0)}
• Broadcasts: {settings.get('total_broadcasts', 0)}
• Welcomed: {len(bot.welcomed_users)}
• Joined Groups: {settings.get('joined_groups_count', 0)}{join_status}

⚙️ **Settings:**
• Spam: {'✅' if settings.get('auto_spam') else '❌'} | Welcome: {'✅' if settings.get('auto_welcome') else '❌'}
• VC Join: {'✅' if settings.get('auto_vc_join') else '❌'} | React: {'✅' if settings.get('auto_react') else '❌'}
• GC Reply: {'✅' if settings.get('auto_gc_reply') else '❌'} | Interval: {settings.get('broadcast_interval', 25)}s

📝 **Messages:**
• Broadcast: {settings.get('broadcast_message', 'Not set')[:20]}...
• Welcome: {settings.get('welcome_message', 'Not set')[:20]}...
"""
    
    buttons = [
        # Row 1: Start/Stop
        [
            Button.inline("▶️ Start", f"start_{session_name}".encode()),
            Button.inline("⏹️ Stop", f"stop_{session_name}".encode())
        ],
        # Row 2: Messages
        [
            Button.inline("📢 Set Msg", f"setmsg_{session_name}".encode()),
            Button.inline("👋 Set Welcome", f"setwelcome_{session_name}".encode())
        ],
        # Row 3: Profile
        [
            Button.inline("✏️ Name", f"setname_{session_name}".encode()),
            Button.inline("🖼️ Photo", f"setphoto_{session_name}".encode())
        ],
        # Row 4: Toggles
        [
            Button.inline("🔄 Spam", f"togglespam_{session_name}".encode()),
            Button.inline("👋 Welcome", f"togglewelcome_{session_name}".encode())
        ],
        # Row 5: New Features
        [
            Button.inline("🎤 VC Join", f"togglevc_{session_name}".encode()),
            Button.inline("❤️ React", f"togglereact_{session_name}".encode())
        ],
        # Row 6: GC Reply
        [
            Button.inline("💬 GC Reply", f"togglegcreply_{session_name}".encode()),
            Button.inline("✏️ Set GC Msg", f"setgcreply_{session_name}".encode())
        ],
        # Row 7: ADD TO GROUPS BUTTON
        [
            Button.inline("➕ Add to Groups", f"addtogroups_{session_name}".encode())
        ],
        # Row 7: Channel & Settings
        [
            Button.inline("📢 Channels", f"channels_{session_name}".encode()),
            Button.inline("⏱️ Interval", f"setinterval_{session_name}".encode())
        ],
        # Row 8: Other Actions
        [
            Button.inline("🗑️ Remove Photo", f"removephoto_{session_name}".encode()),
            Button.inline("📊 Refresh", f"refresh_{session_name}".encode())
        ],
        # Row 9: Progress & Delete & Back
        []
    ]
    
    # Add progress button if joining in progress
    if bot.joining_in_progress:
        buttons[8].append(Button.inline("📈 Progress", f"progress_{session_name}".encode()))
    
    # Add Delete and Back buttons
    buttons[8].extend([
        Button.inline("🗑️ Delete Bot", f"delete_{session_name}".encode()),
        Button.inline("🔙 Back", b"my_bots")
    ])
    
    try:
        await event.edit(text, buttons=buttons)
    except Exception as e:
        if 'MessageNotModified' not in type(e).__name__:
            raise

# ============= BOT ACTIONS =============
async def activate_bot(event, session_name):
    file_path = os.path.join(SESSIONS_DIR, f"{session_name}.session")
    
    if os.path.exists(file_path):
        await event.edit("⏳ **Activating bot...**")
        bot_instance = await manager.add_bot(file_path)
        
        if bot_instance:
            await event.answer("✅ Bot activated!")
            await bot_details(event, session_name)
        else:
            await event.edit("❌ Failed to activate bot!",
                           buttons=[Button.inline("🔙 Back to Bots", b"my_bots")])
    else:
        await event.edit("❌ Session file not found!",
                        buttons=[Button.inline("🔙 Back to Bots", b"my_bots")])

async def start_bot(event, session_name):
    if session_name in manager.bots:
        await manager.start_bot_services(session_name)
        await event.answer("✅ Bot started!")
        await bot_details(event, session_name)

async def stop_bot(event, session_name):
    if session_name in manager.bots:
        await manager.stop_bot_services(session_name)
        await event.answer("⏹️ Bot stopped!")
        await bot_details(event, session_name)

async def toggle_spam(event, session_name):
    if session_name in manager.bots:
        bot = manager.bots[session_name]
        bot.settings['auto_spam'] = not bot.settings.get('auto_spam', False)
        manager.save_settings()
        await event.answer(f"🔄 Auto Spam: {'ON' if bot.settings['auto_spam'] else 'OFF'}")
        await bot_details(event, session_name)

async def toggle_welcome(event, session_name):
    if session_name in manager.bots:
        bot = manager.bots[session_name]
        bot.settings['auto_welcome'] = not bot.settings.get('auto_welcome', False)
        
        if bot.settings['auto_welcome']:
            await bot.register_welcome_handler()
        else:
            bot.welcomed_users.clear()
        
        manager.save_settings()
        await event.answer(f"👋 Auto Welcome: {'ON' if bot.settings['auto_welcome'] else 'OFF'}")
        await bot_details(event, session_name)

async def setmsg_prompt(event, session_name):
    await event.edit(f"📝 **Set Broadcast Message**\n\nSend the message:",
                    buttons=[Button.inline("🔙 Cancel", f"bot_{session_name}".encode())])
    manager.current_menu[event.sender_id] = f'waiting_msg_{session_name}'

async def setwelcome_prompt(event, session_name):
    await event.edit(f"👋 **Set Welcome Message**\n\nSend the message:",
                    buttons=[Button.inline("🔙 Cancel", f"bot_{session_name}".encode())])
    manager.current_menu[event.sender_id] = f'waiting_welcome_{session_name}'

async def setname_prompt(event, session_name):
    await event.edit(f"✏️ **Change Name**\n\nSend new name (First Last):",
                    buttons=[Button.inline("🔙 Cancel", f"bot_{session_name}".encode())])
    manager.current_menu[event.sender_id] = f'waiting_name_{session_name}'

async def setphoto_prompt(event, session_name):
    await event.edit(f"🖼️ **Set Profile Photo**\n\nSend a photo:",
                    buttons=[Button.inline("🔙 Cancel", f"bot_{session_name}".encode())])
    manager.current_menu[event.sender_id] = f'waiting_photo_{session_name}'

async def remove_photo(event, session_name):
    if session_name in manager.bots:
        await event.edit("⏳ **Removing profile photo...**")
        success, message = await manager.bots[session_name].remove_profile_photo()
        await event.answer(f"{'✅' if success else '❌'} {message}")
        await bot_details(event, session_name)

async def setinterval_prompt(event, session_name):
    await event.edit(f"⏱️ **Set Interval**\n\nSend interval in seconds:",
                    buttons=[Button.inline("🔙 Cancel", f"bot_{session_name}".encode())])
    manager.current_menu[event.sender_id] = f'waiting_interval_{session_name}'

async def refresh_stats(event, session_name):
    if session_name in manager.bots:
        await event.edit("⏳ **Refreshing statistics...**")
        await manager.bots[session_name].get_all_dialogs(force_refresh=True)
        await event.answer("✅ Stats refreshed!")
        await bot_details(event, session_name)

async def delete_bot(event, session_name):
    await event.edit(
        f"⚠️ **Delete {session_name}?**",
        buttons=[
            [
                Button.inline("✅ Yes", f"confirm_delete_{session_name}".encode()),
                Button.inline("❌ No", f"bot_{session_name}".encode())
            ]
        ]
    )

async def confirm_delete(event, session_name):
    if session_name in manager.bots:
        await manager.remove_bot(session_name)
    
    file_path = os.path.join(SESSIONS_DIR, f"{session_name}.session")
    if os.path.exists(file_path):
        os.remove(file_path)
    
    await event.edit(f"✅ **Bot {session_name} deleted!**",
                    buttons=[Button.inline("🔙 Back to Bots", b"my_bots")])

# ============= STATUS =============
async def show_status(event):
    uploaded = manager.get_all_sessions()
    active = list(manager.bots.keys())
    running = [s for s in active if manager.settings.get(s, {}).get('status') == 'running']
    
    total_groups = 0
    total_channels = 0
    total_members = 0
    total_welcomed = 0
    total_joined = 0
    
    for session in active:
        settings = manager.settings.get(session, {})
        total_groups += len(settings.get('groups', []))
        total_channels += len(settings.get('channels', []))
        total_members += settings.get('total_members', 0)
        total_joined += settings.get('joined_groups_count', 0)
        if hasattr(manager.bots[session], 'welcomed_users'):
            total_welcomed += len(manager.bots[session].welcomed_users)
    
    text = f"""
📊 **Global Status**

**Sessions:** {len(uploaded)} total | {len(active)} active | {len(running)} running
**Coverage:** {total_groups} groups | {total_channels} channels | {total_members} users
**Joins:** {total_joined} groups joined via bot
**Welcome:** {total_welcomed} users welcomed

**Active Bots:**
"""
    
    for session in active[:10]:
        status = "🟢" if session in running else "🔴"
        text += f"\n{status} {session}"
    
    buttons = [[Button.inline("🔄 Refresh", b"status"), Button.inline("🔙 Back", b"back_to_menu")]]
    await event.edit(text, buttons=buttons)

# ============= START =============
async def main():
    print("""
    ╔════════════════════════════════════╗
    ║    USERBOT MANAGER - v5.3          ║
    ║    Fixed: Public/Private Groups    ║
    ║    Added: Smart Link Detection     ║
    ╚════════════════════════════════════╝
    """)
    
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("🚀 Bot started!")
    
    for session_name in manager.bots:
        if manager.settings.get(session_name, {}).get('status') == 'running':
            logger.info(f"🔄 Auto-starting {session_name}")
            await manager.start_bot_services(session_name)
    
    await bot.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped")
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
