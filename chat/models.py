from django.db import models


class User(models.Model):
    id = models.AutoField(primary_key=True)
    username = models.TextField(unique=True)
    email = models.TextField(unique=True)
    password = models.TextField()
    profile_picture = models.TextField(null=True)
    role = models.TextField(default='user')
    is_blocked = models.IntegerField(default=0)
    sanction_reason = models.TextField(null=True)
    sanctioned_until = models.TextField(null=True)
    created_at = models.TextField()

    class Meta:
        managed = False
        db_table = 'users'


class Conversation(models.Model):
    id = models.AutoField(primary_key=True)
    type = models.TextField()
    name = models.TextField(null=True)
    created_by = models.IntegerField(null=True)
    user_one_id = models.IntegerField(null=True)
    user_two_id = models.IntegerField(null=True)
    is_archived = models.IntegerField(default=0)
    created_at = models.TextField()

    class Meta:
        managed = False
        db_table = 'conversations'


class File(models.Model):
    id = models.AutoField(primary_key=True)
    user_id = models.IntegerField()
    filename = models.TextField()
    original_name = models.TextField()
    file_type = models.TextField()
    file_size = models.IntegerField()
    description = models.TextField(null=True)
    upload_date = models.TextField()

    class Meta:
        managed = False
        db_table = 'files'


class ChatMessage(models.Model):
    id = models.AutoField(primary_key=True)
    conversation_id = models.IntegerField()
    user_id = models.IntegerField()
    message = models.TextField(null=True)
    file_id = models.IntegerField(null=True)
    is_ephemeral = models.IntegerField(default=0)
    expires_at = models.TextField(null=True)
    created_at = models.TextField()

    class Meta:
        managed = False
        db_table = 'chat_messages'


class AdminLog(models.Model):
    id = models.AutoField(primary_key=True)
    admin_id = models.IntegerField()
    action = models.TextField()
    target_type = models.TextField()
    target_id = models.IntegerField(null=True)
    details = models.TextField(null=True)
    created_at = models.TextField()

    class Meta:
        managed = False
        db_table = 'admin_logs'
