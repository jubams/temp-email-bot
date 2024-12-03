import requests
import json
import os
import string
import secrets
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext, MessageHandler, filters

API_URL = "https://api.mail.tm"
EMAIL_STORAGE_FILE = "temporary_emails.json"

TELEGRAM_TOKEN = os.getenv(
    'BOT_TOKEN')  # Get the token from environment variable


def generate_random_password(length=12):
    alphabet = string.ascii_letters + string.digits + string.punctuation
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    return password


async def create_temp_email(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    try:
        domain_response = requests.get(f"{API_URL}/domains")
        domain_response.raise_for_status()
        domain = domain_response.json()["hydra:member"][0]["domain"]

        base_address = f"temp_{os.urandom(4).hex()}"
        address = f"{base_address}@{domain}"
        password = generate_random_password()

        response = requests.post(f"{API_URL}/accounts",
                                 json={
                                     "address": address,
                                     "password": password
                                 })
        response.raise_for_status()

        email_data = response.json()
        email_data['password'] = password

        await update.message.reply_text(
            f"New Temporary Email Created:\nEmail: {email_data['address']}\nPassword: {password}"
        )
        save_email(user_id, email_data)
    except requests.RequestException as e:
        await update.message.reply_text(f"An error occurred: {e}")
    finally:
        await start(update, context)


def save_email(user_id, email_data):
    emails = load_saved_emails()

    if str(user_id) not in emails:
        emails[str(user_id)] = []
    emails[str(user_id)].append(email_data)

    with open(EMAIL_STORAGE_FILE, "w") as file:
        json.dump(emails, file, indent=4)


def load_saved_emails():
    if os.path.exists(EMAIL_STORAGE_FILE):
        with open(EMAIL_STORAGE_FILE, "r") as file:
            try:
                data = json.load(file)
                if isinstance(data, list):
                    return {}
                return data
            except json.JSONDecodeError:
                return {}
    return {}


async def list_emails_with_indices(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    emails = load_saved_emails().get(str(user_id), [])
    if not emails:
        await update.message.reply_text("No saved emails found.")
    else:
        message = "Saved Emails:\n"
        for i, email in enumerate(emails):
            message += f"{i + 1}. Email: {email['address']} | Password: {email['password']}\n"
        await update.message.reply_text(message)


async def start(update: Update, context: CallbackContext):
    start_message = ("Welcome to the Temporary Email Bot!\n\n"
                     "Here are the commands you can use:\n"
                     "/create - Create a new temporary email.\n"
                     "/check - Check the inbox for a specific email.\n"
                     "/delete - Delete a saved email by index.\n"
                     "/list - List all saved emails.")
    await update.message.reply_text(start_message)


async def check_inbox(update: Update, context: CallbackContext):
    await list_emails_with_indices(update, context)
    await update.message.reply_text(
        "Please provide the index of the email you want to check.")
    context.user_data['action'] = 'check'


async def delete_email(update: Update, context: CallbackContext):
    await list_emails_with_indices(update, context)
    await update.message.reply_text(
        "Please provide the index of the email you want to delete.")
    context.user_data['action'] = 'delete'


async def handle_user_input(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    action = context.user_data.get('action')
    emails = load_saved_emails().get(str(user_id), [])

    if action in ['check', 'delete']:
        try:
            index = int(update.message.text) - 1
            if 0 <= index < len(emails):
                email = emails[index]
                if action == 'check':
                    await perform_check(update, email)
                elif action == 'delete':
                    perform_delete(user_id, index)
                    await update.message.reply_text(
                        f"Email {email['address']} deleted successfully.")
            else:
                await update.message.reply_text(
                    "Invalid index. Please provide a valid index.")
        except (IndexError, ValueError):
            await update.message.reply_text(
                "Invalid index format. Please provide a number.")
    else:
        await update.message.reply_text(
            "Please use /check or /delete command to start.")
    await start(update, context)


async def perform_check(update: Update, email):
    password = email['password']
    session = requests.Session()
    try:
        response = session.post(f"{API_URL}/token",
                                json={
                                    "address": email['address'],
                                    "password": password
                                })
        response.raise_for_status()
        token = response.json()["token"]
        session.headers.update({"Authorization": f"Bearer {token}"})

        response = session.get(f"{API_URL}/messages")
        response.raise_for_status()
        messages = response.json()["hydra:member"]
        if not messages:
            await update.message.reply_text("No messages found.")
        else:
            for i, msg in enumerate(messages):
                await display_full_email(msg['id'], session, update)
    except requests.RequestException as e:
        await update.message.reply_text(f"An error occurred: {e}")


def perform_delete(user_id, index):
    emails = load_saved_emails()
    user_emails = emails.get(str(user_id), [])
    del user_emails[index]
    emails[str(user_id)] = user_emails

    with open(EMAIL_STORAGE_FILE, "w") as file:
        json.dump(emails, file, indent=4)


async def display_full_email(email_id, session, update: Update):
    try:
        response = session.get(f"{API_URL}/messages/{email_id}")
        response.raise_for_status()
        message = response.json()

        formatted_message = (f"➖➖➖➖➖➖➖➖➖\n"
                             f"From: {message['from']['address']}\n"
                             f"To: {message['to'][0]['address']}\n"
                             f"Subject: {message['subject']}\n"
                             f"➖➖➖➖➖➖➖➖➖\n"
                             f"{message['text']}")

        max_length = 4096
        if len(formatted_message) > max_length:
            for i in range(0, len(formatted_message), max_length):
                await update.message.reply_text(formatted_message[i:i +
                                                                  max_length])
        else:
            await update.message.reply_text(formatted_message)
    except requests.RequestException as e:
        await update.message.reply_text(f"An error occurred: {e}")


def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("create", create_temp_email))
    application.add_handler(CommandHandler("check", check_inbox))
    application.add_handler(CommandHandler("delete", delete_email))
    application.add_handler(CommandHandler("list", list_emails_with_indices))

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_input))

    application.run_polling()


if __name__ == "__main__":
    main()
