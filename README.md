# gdrive-last-update-checker
A simple script to check the last update time of defined subfolders in Google Drive. 
This script is useful to check if a file is being updated or not. If not updated for a certain time, 
it can send a notification to Mattermost.
Use `config.json` to define the subfolders you want to check and the time interval in hours.


# Installation & Usage

## Google Drive API
1. Create a project in Google Cloud Console
2. Enable Google Drive API
3. Create OAuth 2.0 credentials
4. Download the credentials json file and copy its content to `/credentials.json`.

## Install requirements
```bash
pip install -r requirements.txt
```

## Configuration
Edit `config.json` to define the subfolders you want to check and the time interval in hours. Set your Mattermost webhook URL.
See the example file.