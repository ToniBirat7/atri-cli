from models.models import User, Message

class UserRepository:
    def __init__(self):
        # In a real application, this would initialize a database connection
        self._users = {}

    def get_user(self, user_id: int) -> User | None:
        return self._users.get(user_id)

    def add_user(self, user: User):
        self._users[user.user_id] = user

class MessageRepository:
    def __init__(self):
        # In a real application, this would initialize a database connection
        self._messages = {}

    def get_messages_by_user(self, user_id: int) -> list[Message]:
        return [msg for msg in self._messages.values() if msg.user_id == user_id]

    def add_message(self, message: Message):
        self._messages[message.message_id] = message