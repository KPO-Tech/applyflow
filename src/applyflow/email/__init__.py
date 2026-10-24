"""Suivi de la boîte mail : connexion IMAP, réponses et relances."""

from applyflow.email.account import (
    credentials_path,
    delete_credentials,
    load_credentials,
    normalize_password,
    save_credentials,
)
from applyflow.email.gmail import InboundEmail, fetch_messages, test_connection
from applyflow.email.service import (
    MailboxError,
    MailboxNotConnected,
    email_status,
    followup_candidates,
    list_messages,
    mark_followed_up,
    serialize_messages,
    sync_mailbox,
    update_message,
)

__all__ = [
    "InboundEmail",
    "MailboxError",
    "MailboxNotConnected",
    "credentials_path",
    "delete_credentials",
    "email_status",
    "fetch_messages",
    "followup_candidates",
    "list_messages",
    "load_credentials",
    "mark_followed_up",
    "normalize_password",
    "save_credentials",
    "serialize_messages",
    "sync_mailbox",
    "test_connection",
    "update_message",
]
