import os
import json
import secrets
import hashlib

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
CONFIG_FILE = os.path.join(DATA_DIR, 'admin_config.json')
TXT_CREDENTIALS_FILE = os.path.join(DATA_DIR, 'acesso-admin.txt')

def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
        try:
            os.chmod(DATA_DIR, 0o700)
        except Exception:
            pass

def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return key.hex(), salt

def verify_password(stored_hash, stored_salt, password_provided):
    if not stored_hash or not stored_salt or not password_provided:
        return False
    key, _ = hash_password(password_provided, stored_salt)
    return secrets.compare_digest(key, stored_hash)

def authenticate(username, password):
    cfg = get_or_create_admin_config()
    accounts = [cfg] + cfg.get('users', [])
    account = next((u for u in accounts if u.get('username') == username), None)
    if account is None:
        hash_password(password, 'unknown-account')
        return False
    return verify_password(account.get('password_hash'), account.get('password_salt'), password)

def set_user(username, password):
    cfg = get_or_create_admin_config()
    pwd_hash, salt = hash_password(password)
    account = {'username': username, 'password_hash': pwd_hash, 'password_salt': salt}
    if cfg.get('username') == username:
        cfg.update(account)
    else:
        cfg['users'] = [u for u in cfg.get('users', []) if u.get('username') != username] + [account]
    temporary = CONFIG_FILE + '.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)
    os.replace(temporary, CONFIG_FILE)

def get_or_create_admin_config():
    hosted_users = os.getenv('STYLELUX_USERS_JSON')
    if hosted_users:
        cfg = json.loads(hosted_users)
        if not isinstance(cfg, dict) or not isinstance(cfg.get('users'), list) or not cfg['users']:
            raise RuntimeError('Configuração de utilizadores inválida.')
        return cfg
    if os.getenv('VERCEL'):
        raise RuntimeError('Configure STYLELUX_USERS_JSON para ativar o login.')
    ensure_data_dir()
    
    # If config already exists, do NOT regenerate credentials
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    # Generate random strong password if not existing
    env_user = os.getenv('ADMIN_USER', 'admin')
    random_pass = secrets.token_urlsafe(16)
    env_pass = os.getenv('ADMIN_PASSWORD', random_pass)
    
    pwd_hash, salt = hash_password(env_pass)
    config_data = {
        'username': env_user,
        'password_hash': pwd_hash,
        'password_salt': salt,
        'session_secret': secrets.token_hex(32)
    }
    
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=2)
        
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except Exception:
        pass

    # Save initial plaintext credential strictly to data/acesso-admin.txt (0600) for owner
    try:
        txt_content = f"STYLE LUX AUTO DETAILS - ACESSO ADMIN\nUtilizador: {env_user}\nPalavra-passe: {env_pass}\n"
        with open(TXT_CREDENTIALS_FILE, 'w', encoding='utf-8') as f:
            f.write(txt_content)
        os.chmod(TXT_CREDENTIALS_FILE, 0o600)
    except Exception:
        pass

    return config_data

def update_admin_password(new_password):
    config_data = get_or_create_admin_config()
    pwd_hash, salt = hash_password(new_password)
    config_data['password_hash'] = pwd_hash
    config_data['password_salt'] = salt
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, indent=2)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except Exception:
        pass
        
    # Update txt file
    try:
        txt_content = f"STYLE LUX AUTO DETAILS - ACESSO ADMIN\nUtilizador: {config_data['username']}\nPalavra-passe: {new_password}\n"
        with open(TXT_CREDENTIALS_FILE, 'w', encoding='utf-8') as f:
            f.write(txt_content)
        os.chmod(TXT_CREDENTIALS_FILE, 0o600)
    except Exception:
        pass

    return True
