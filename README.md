# gdrive-last-update-checker

Monitors Google Drive folders for recent file uploads and sends a Mattermost notification if no new file has been uploaded within a configurable time interval. Useful for detecting when automated upload scripts (e.g. surveillance cameras, backups) stop working.

## How it works

The script runs as a continuous loop. Every `check_interval` (default: 2 hours), it checks each configured Google Drive folder:

- **Non-recursive:** Checks if any file was uploaded directly into the folder within the configured `interval`.
- **Recursive:** Traverses the subfolder tree depth-first (DFS), always checking the newest subfolder first (sorted by `modifiedTime` descending). At each folder, it checks if any file was uploaded within the configured `interval`. If a recent file is found, the check stops immediately. This finds recent files fast in deep trees (e.g. year/month/day structures). API calls are parallelized with a thread pool for large folder counts.

If no recent file is found, a notification is sent to Mattermost. A daily "I'm still working" heartbeat message is also sent.

## Setup

### 1. Google Drive API

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a project.
2. Enable the **Google Drive API**.
3. Create **OAuth 2.0 Client ID** credentials (Application type: Desktop app).
4. Download the credentials JSON file and save it as `credentials.json` in the project root.

### 2. Generate OAuth Token

Run the token generator on your local machine (needs a browser for the OAuth flow):

```bash
pip install -r requirements.txt
python token-generator.py
```

This opens a browser window for Google authentication and saves the token to `token.json`.

### 3. Configuration

Copy `config.json.example` to `config.json` and edit it:

```json
{
    "prefix": "[Google Drive Notification]",
    "scopes": ["https://www.googleapis.com/auth/drive"],
    "mattermost_webhook_url": "https://your-mattermost-instance/hooks/xxxxx",
    "check_interval": "2h",
    "folders": [
        {
            "name": "Frigate (Surveillance Cameras)",
            "id": "1Hin4cHtQ1ESf9SzflyOAnXAjjqE1ygLi",
            "interval": "3h",
            "recursive": true
        }
    ]
}
```

#### Config fields

| Field | Description |
|---|---|
| `prefix` | Prefix added to every Mattermost message. |
| `scopes` | Google Drive API scopes. Use `https://www.googleapis.com/auth/drive` for full access. |
| `mattermost_webhook_url` | Mattermost incoming webhook URL. |
| `check_interval` | How often to check all folders. Supports `m` (minutes), `h` (hours), `d` (days). Default: `2h`. |
| `folders` | Array of folder configurations (see below). |

#### Folder fields

| Field | Description |
|---|---|
| `name` | Human-readable name (used in notifications). |
| `id` | Google Drive folder ID (see below). |
| `interval` | Alert threshold — if no file is uploaded within this time, a notification is sent. Supports `m`, `h`, `d` (e.g. `3h`, `30m`, `14d`). |
| `recursive` | If `true`, checks all subfolders recursively. If `false`, only checks files directly in the folder. |
| `disabled` | Optional. If `true`, the folder is skipped. The daily heartbeat message will list disabled folders as a reminder. Default: `false`. |

> **Tip:** Folders are checked in the order they appear in the config. Put critical folders (e.g. surveillance cameras) first and less urgent or large/slow folders last. Folders without recent files take longer to check because the entire subfolder tree must be traversed.

#### How to find a Google Drive folder ID

1. Open the folder in [Google Drive](https://drive.google.com) in your browser.
2. Look at the URL: `https://drive.google.com/drive/folders/1Hin4cHtQ1ESf9SzflyOAnXAjjqE1ygLi`
3. The string after `/folders/` is the folder ID: `1Hin4cHtQ1ESf9SzflyOAnXAjjqE1ygLi`

## Deployment (Docker)

### docker-compose.yml

```yaml
services:
  app:
    build: .
    image: gdrive-last-update-checker
    container_name: gdrive_checker
    restart: unless-stopped
    volumes:
      - ./config.json:/usr/src/app/config.json:ro
      - ./credentials.json:/usr/src/app/credentials.json:ro
      - ./token.json:/usr/src/app/token.json
    environment:
      - TZ=Europe/Istanbul
```

Secrets (`config.json`, `credentials.json`, `token.json`) are mounted as volumes — they are **not** baked into the Docker image. Place these files in the project directory on your server.

`token.json` is mounted without `:ro` so the script can save refreshed tokens.

### Deploy on Proxmox / Docker host

```bash
git clone <repo-url> gdrive-last-update-checker
cd gdrive-last-update-checker

# Place your secret files
cp config.json.example config.json
# Edit config.json with your settings
# Copy credentials.json and token.json into the directory

docker compose up -d --build
```

To update:

```bash
git pull
docker compose up -d --build
```

Logs:

```bash
docker compose logs -f
```

## Testing

To verify notifications work, add a test folder with a short interval:

```json
{
    "name": "TEST - remove after testing",
    "id": "your-inactive-folder-id",
    "interval": "1m",
    "recursive": false
}
```

Set `check_interval` to `"1m"` as well. Start the container — you should receive a Mattermost notification within 1-2 minutes. Remove the test folder and restore your normal `check_interval` afterward.

## Troubleshooting

- **"Google Drive Token abgelaufen" notification:** The OAuth refresh token has expired (happens after ~6 months of inactivity). You need to re-authenticate:
  1. Run `python token-generator.py` on a machine with a browser
  2. Complete the Google authentication in the browser
  3. Copy the generated `token.json` to the server (next to `docker-compose.yml`)
  4. Restart the container: `docker compose restart`
- **Google Drive API rate limits:** If you have many recursive folders, the BFS traversal with batching minimizes API calls. If you still hit limits, increase `check_interval`.
- **No notifications at all:** Check that `mattermost_webhook_url` is correct and reachable from the container. Check logs with `docker compose logs -f`.
- **A folder check takes very long:** This happens when no recent file exists — the entire subfolder tree must be traversed. Move such folders to the end of the `folders` array so critical folders are checked first.