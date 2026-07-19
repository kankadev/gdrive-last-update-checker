import datetime
import json
import logging
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

shutdown_event = threading.Event()


def parse_interval(value):
    """Parse interval to seconds. Accepts strings like '30m', '2h', '1d' or numbers (treated as hours for backward compat)."""
    if isinstance(value, (int, float)):
        return int(value * 3600)
    match = re.match(r'^(\d+)\s*([mhd])$', str(value).strip().lower())
    if not match:
        raise ValueError(f"Invalid interval format: {value}. Expected format like '30m', '2h', '1d'")
    num = int(match.group(1))
    unit = match.group(2)
    multipliers = {'m': 60, 'h': 3600, 'd': 86400}
    return num * multipliers[unit]


def load_json_file(filename):
    try:
        with open(filename, 'r') as file:
            return json.load(file)
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in {filename}: {e}")
    except FileNotFoundError:
        logger.error(f"File not found: {filename}")
    except Exception as e:
        logger.error(f"Error reading {filename}: {e}")
    return None


def send_mattermost_message(message):
    try:
        full_message = f"{CONFIG['prefix']} {message}"
        requests.post(CONFIG['mattermost_webhook_url'], json={"text": full_message})
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send Mattermost message: {e}")
    except KeyError:
        logger.error("CONFIG not loaded, cannot send Mattermost message")


CONFIG = load_json_file('config.json')
if CONFIG is None:
    logger.critical("Could not load config.json. Exiting.")
    sys.exit(1)


def authenticate_google_drive():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', scopes=CONFIG['scopes'])
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open('token.json', 'w') as token_file:
                token_file.write(creds.to_json())
            logger.info("Google Drive token refreshed and saved.")
        else:
            send_mattermost_message(
                "Google Drive Token abgelaufen und konnte nicht erneuert werden. "
                "Bitte lokal 'python token-generator.py' ausfuehren (oeffnet Browser), "
                "dann die neue token.json auf den Server kopieren."
            )
            raise Exception("No valid credentials. Please re-authenticate using token-generator.py.")
    return creds


MAX_WORKERS = 10


def check_for_recent_files(service, folder_ids, threshold_str):
    batch_size = 30
    batches = []
    for i in range(0, len(folder_ids), batch_size):
        batch = folder_ids[i:i + batch_size]
        parents_query = ' or '.join(f"'{fid}' in parents" for fid in batch)
        query = f"({parents_query}) and modifiedTime > '{threshold_str}' and trashed=false"
        batches.append(query)

    def execute_query(q):
        return service.files().list(q=q, fields='files(id)', pageSize=1).execute()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(execute_query, q): q for q in batches}
        for future in as_completed(futures):
            if future.result().get('files'):
                executor.shutdown(wait=False, cancel_futures=True)
                return True
    return False


def get_subfolders(service, folder_ids):
    """Get immediate subfolder IDs for a list of folder IDs, sorted by modifiedTime desc.
    Batches queries for efficiency."""
    subfolders = []
    batch_size = 30
    for i in range(0, len(folder_ids), batch_size):
        batch = folder_ids[i:i + batch_size]
        parents_query = ' or '.join(f"'{fid}' in parents" for fid in batch)
        query = f"({parents_query}) and mimeType='application/vnd.google-apps.folder' and trashed=false"
        page_token = None
        while True:
            response = service.files().list(
                q=query, fields='files(id, modifiedTime), nextPageToken', pageSize=1000,
                pageToken=page_token, orderBy='modifiedTime desc'
            ).execute()
            for folder in response.get('files', []):
                subfolders.append((folder['id'], folder.get('modifiedTime', '')))
            page_token = response.get('nextPageToken')
            if not page_token:
                break
    subfolders.sort(key=lambda x: x[1], reverse=True)
    return [fid for fid, _ in subfolders]


def check_folder_recursive_dfs(service, folder_id, threshold_str, depth=0, max_depth=20):
    """DFS traversal: check current folder for recent files, then recurse into subfolders
    sorted by modifiedTime desc (newest first). Stops immediately when a recent file is found."""
    if depth > max_depth:
        logger.warning(f"Max depth {max_depth} reached for folder {folder_id}, skipping.")
        return False

    if check_for_recent_files(service, [folder_id], threshold_str):
        logger.info(f"Found recent file at depth {depth}.")
        return True

    subfolders = get_subfolders(service, [folder_id])
    if subfolders:
        logger.info(f"DFS depth {depth}: {len(subfolders)} subfolders (sorted newest-first)")

    for subfolder_id in subfolders:
        if check_folder_recursive_dfs(service, subfolder_id, threshold_str, depth + 1, max_depth):
            return True

    return False


def check_folder(service, folder_config, now):
    try:
        folder_id = folder_config['id']
        interval_str = folder_config['interval']
        interval_seconds = parse_interval(interval_str)
        name = folder_config.get('name', 'Unknown Folder')
        recursive = folder_config.get('recursive', False)

        threshold = now - datetime.timedelta(seconds=interval_seconds)
        threshold_str = threshold.strftime('%Y-%m-%dT%H:%M:%S.%fZ')

        if recursive:
            found_recent = check_folder_recursive_dfs(service, folder_id, threshold_str)
        else:
            found_recent = check_for_recent_files(service, [folder_id], threshold_str)

        if not found_recent:
            send_mattermost_message(
                f"Im Ordner '{name}' wurde in den letzten {interval_str} keine neue Datei hochgeladen."
            )
        else:
            logger.info(f"Folder '{name}': OK - recent file found.")
    except Exception as e:
        logger.error(f"Error checking folder: {e}", exc_info=True)
        send_mattermost_message(f"Error checking folder '{folder_config.get('name', 'Unknown')}': {str(e)}")


last_message_time = None


def send_daily_message(message):
    global last_message_time
    now = datetime.datetime.now(datetime.timezone.utc)
    daily_hour = CONFIG.get('daily_message_hour', 0)
    local_hour = datetime.datetime.now().hour

    due = last_message_time is None or (now - last_message_time).total_seconds() > 86400
    if due and local_hour >= daily_hour:
        disabled_folders = [f.get('name', 'Unknown') for f in CONFIG['folders'] if f.get('disabled', False)]
        if disabled_folders:
            message += f"\nDeaktivierte Ordner (uebersprungen): {', '.join(disabled_folders)}"
        send_mattermost_message(message)
        last_message_time = now


def main():
    global last_message_time
    check_interval = parse_interval(CONFIG.get('check_interval', '2h'))
    logger.info(f"Starting gdrive-last-update-checker (check interval: {CONFIG.get('check_interval', '2h')})")

    while not shutdown_event.is_set():
        try:
            send_daily_message("Daily reminder... I'm still working.")
            creds = authenticate_google_drive()
            service = build('drive', 'v3', credentials=creds)
            now = datetime.datetime.now(datetime.timezone.utc)
            for folder_config in CONFIG['folders']:
                if folder_config.get('disabled', False):
                    logger.info(f"Folder '{folder_config.get('name', 'Unknown')}' is disabled, skipping.")
                    continue
                check_folder(service, folder_config, now)
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            send_mattermost_message(f"Unexpected error: {str(e)}")
        finally:
            shutdown_event.wait(check_interval)

    logger.info("Shutting down gracefully.")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        shutdown_event.set()
