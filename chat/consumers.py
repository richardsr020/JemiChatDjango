from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer

from . import services


class ChatConsumer(JsonWebsocketConsumer):
    def connect(self):
        session = self.scope.get('session')
        self.user_id = int(session.get('user_id') or 0) if session else 0
        self.conversation_id = int(self.scope.get('url_route', {}).get('kwargs', {}).get('conversation_id') or 0)

        if self.user_id <= 0 or self.conversation_id <= 0:
            self.close(code=4401)
            return

        conversation = services.get_conversation_for_user(self.conversation_id, self.user_id)
        if not conversation:
            self.close(code=4403)
            return

        self.group_name = f'chat_{self.conversation_id}'
        async_to_sync(self.channel_layer.group_add)(self.group_name, self.channel_name)
        self.accept()
        self.send_json({'type': 'connection.ready', 'conversation_id': self.conversation_id})

    def disconnect(self, close_code):
        group_name = getattr(self, 'group_name', '')
        if group_name:
            async_to_sync(self.channel_layer.group_discard)(group_name, self.channel_name)

    def receive_json(self, content, **kwargs):
        action = str(content.get('action') or '')
        if action != 'send_message':
            self.send_json({'type': 'error', 'error': 'Action WebSocket non supportee.'})
            return

        if not services.get_conversation_for_user(self.conversation_id, self.user_id):
            self.send_json({'type': 'error', 'error': 'Conversation invalide.'})
            return

        moderation_reason = services.moderation_message(services.get_user_by_id(self.user_id))
        if moderation_reason:
            self.send_json({'type': 'error', 'error': moderation_reason})
            return

        message_text = (content.get('message') or '').strip()
        if message_text == '':
            self.send_json({'type': 'error', 'error': 'Le message ne peut pas etre vide.'})
            return

        try:
            message_id = services.insert_message(
                user_id=self.user_id,
                conversation_id=self.conversation_id,
                message=message_text,
                file_meta=None,
                ephemeral_week=bool(content.get('ephemeral_week')),
                broadcast=False,
            )
            payload = services.get_message_payload(message_id)
            if payload:
                services.broadcast_chat_event(self.conversation_id, 'message.created', payload)
        except Exception:
            self.send_json({'type': 'error', 'error': "Impossible d'envoyer le message."})

    def chat_event(self, event):
        self.send_json(
            {
                'type': event.get('event_type') or 'event',
                'payload': event.get('payload') or {},
            }
        )
