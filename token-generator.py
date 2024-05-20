from google_auth_oauthlib.flow import InstalledAppFlow

# Pfade zu den Dateien
credentials_path = 'credentials.json'
token_path = 'token.json'

# Berechtigungsbereiche
scopes = ['https://www.googleapis.com/auth/drive']


def authorize():
    flow = InstalledAppFlow.from_client_secrets_file(
        credentials_path,
        scopes=scopes
    )
    creds = flow.run_local_server(port=0)
    with open(token_path, 'w') as token_file:
        token_file.write(creds.to_json())
    print("Authorization successful. Token saved to 'token.json'.")


if __name__ == '__main__':
    authorize()
