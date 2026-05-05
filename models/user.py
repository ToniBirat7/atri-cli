class User:
    def __init__(self, user_id: int, username: str, email: str):
        self.user_id = user_id
        self.username = username
        self.email = email

    def __repr__(self):
        return f"<User(id={self.user_id}, username='{self.username}')>"

class Message:
    def __init__(self, message_id: int, user_id: int, content: str):
        self.message_id = message_id
        self.user_id = user_id
        self.content = content

    def __repr__(self):
        return f"<Message(id={self.message_id}, user_id={self.user_id}, content='{self.content[:20]}...')>"