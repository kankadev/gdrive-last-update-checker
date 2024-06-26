import datetime
import json
import os
import time

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def load_json_file(filename):
    try:
        with open(filename, 'r') as file:
            content = file.read()
            print(f"Reading {filename}: {content}")
            return json.loads(content)
    except json.JSONDecodeError as e:
        send_mattermost_message(f"JSON Decode Error in {filename}: {str(e)} - Content: {content}")
    except FileNotFoundError as e:
        send_mattermost_message(f"File not found {filename}: {str(e)}")
    except Exception as e:
        send_mattermost_message(f"An error occurred with {filename}: {str(e)}")
    return None


def send_mattermost_message(message):
    full_message = f"{CONFIG['prefix']} {message}"  # Fügt den Prefix zur Nachricht hinzu
    try:
        requests.post(CONFIG['mattermost_webhook_url'], json={"text": full_message})
    except requests.exceptions.RequestException as e:
        print(f"Failed to send Mattermost message: {str(e)}")


CONFIG = load_json_file('config.json')
TOKEN_INFO = load_json_file('token.json')


def authenticate_google_drive():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', scopes=CONFIG['scopes'])
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            send_mattermost_message("No valid credentials provided. Please re-authenticate.")
            raise Exception("No valid credentials provided. Please re-authenticate.")
    return creds


def find_latest_file(service, folder_id):
    query = f"'{folder_id}' in parents"
    results = service.files().list(q=query, fields="files(id, name, modifiedTime)",
                                   orderBy='modifiedTime desc').execute()
    files = results.get('files', [])
    if not files:
        return None, None  # Return a tuple of (None, None) if no files are found
    latest_file = files[0]  # Gibt die neueste Datei zurück
    latest_time = datetime.datetime.fromisoformat(latest_file['modifiedTime'].rstrip('Z')).replace(
        tzinfo=datetime.timezone.utc)
    return latest_file, latest_time


def check_folder(service, folder_config, now):
    try:
        folder_id = folder_config['id']
        interval = folder_config['interval']
        name = folder_config.get('name', 'Unknown Folder')
        recursive = folder_config.get('recursive', False)

        latest_file, latest_time = find_latest_file_recursive(service, folder_id) if recursive else find_latest_file(
            service, folder_id)

        if latest_file:
            if (now - latest_time).total_seconds() > interval * 3600:
                send_mattermost_message(
                    f"Die neueste Datei im Ordner '{name}' ist älter als {interval} Stunden.")
    except Exception as e:
        send_mattermost_message(f"Error checking folder: {str(e)} - Folder Config: {folder_config}")


def find_latest_file_recursive(service, folder_id, latest_file=None, latest_time=None):
    query = (f"('{folder_id}' in parents) and (mimeType='application/vnd.google-apps.folder' or "
             f"mimeType!='application/vnd.google-apps.folder')")
    response = service.files().list(q=query, fields="files(id, name, modifiedTime, mimeType)",
                                    orderBy='modifiedTime desc').execute()
    items = response.get('files', [])

    for item in items:
        item_time = datetime.datetime.fromisoformat(item['modifiedTime'].rstrip('Z')).replace(
            tzinfo=datetime.timezone.utc)
        if latest_file is None or item_time > latest_time:
            latest_file = item
            latest_time = item_time
        # Recursively check if the item is a folder
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            # Call recursively and update latest_file and latest_time
            sub_latest_file, sub_latest_time = find_latest_file_recursive(service, item['id'], latest_file, latest_time)
            if sub_latest_time > latest_time:
                latest_file, latest_time = sub_latest_file, sub_latest_time
    return latest_file, latest_time


last_message_time = None


def send_daily_message(message):
    global last_message_time
    now = datetime.datetime.now(datetime.timezone.utc)
    if last_message_time is None or (now - last_message_time).total_seconds() > 86400:  # 86400 seconds = 1 day
        send_mattermost_message(message)
        last_message_time = now


def main():
    global last_message_time
    while True:
        try:
            send_daily_message("Daily reminder... I'm still working.")
            creds = authenticate_google_drive()
            service = build('drive', 'v3', credentials=creds)
            now = datetime.datetime.now(datetime.timezone.utc)
            for folder_config in CONFIG['folders']:
                check_folder(service, folder_config, now)
        except Exception as e:
            send_mattermost_message(f"Unexpected error: {str(e)}")
        finally:
            # wait 2 hours before checking again
            time.sleep(2 * 60 * 60)


if __name__ == '__main__':
    main()
