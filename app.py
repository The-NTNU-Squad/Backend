from flask import Flask, jsonify
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import requests
import os
from dotenv import load_dotenv
from flask_bcrypt import Bcrypt
import secrets

load_dotenv()

app = Flask(__name__)
CORS(app)

# 資料庫設定
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
migrate = Migrate(app, db)

PLUGIN_API = os.getenv("PLUGIN_API", "http://localhost:8080")

# User 模型
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    mc_username = db.Column(db.String(50), nullable=True)
    discord_id = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "token": self.token,
            "mc_username": self.mc_username,
            "discord_id": self.discord_id,
            "created_at": str(self.created_at)
        }


@app.route('/')
def index():
    return jsonify({'message': 'Hello, World!'})


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/api/auth/register', methods=['POST'])
def register():
    from flask import request
    data = request.get_json()

    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify({'error': '請填寫帳號和密碼'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'error': '帳號已存在'}), 409

    password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
    token = secrets.token_hex(32)

    user = User(username=username, password_hash=password_hash, token=token)
    db.session.add(user)
    db.session.commit()

    return jsonify({
        'message': '註冊成功',
        'token': token
    }), 201


@app.route('/api/auth/login', methods=['POST'])
def login():
    from flask import request
    data = request.get_json()

    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify({'error': '請填寫帳號和密碼'}), 400

    user = User.query.filter_by(username=username).first()

    if not user or not bcrypt.check_password_hash(user.password_hash, password):
        return jsonify({'error': '帳號或密碼錯誤'}), 401

    return jsonify({
        'message': '登入成功',
        'token': user.token
    }), 200


@app.route('/api/auth/me', methods=['GET'])
def me():
    from flask import request
    token = request.headers.get('X-Token')

    if not token:
        return jsonify({'error': '未提供 token'}), 401

    user = User.query.filter_by(token=token).first()

    if not user:
        return jsonify({'error': 'token 無效'}), 401

    return jsonify(user.to_dict()), 200

@app.route('/api/bind/mc', methods=['POST'])
def bind_mc():
    from flask import request
    data = request.get_json()

    token = data.get('token', '').strip()
    mc_username = data.get('mc_username', '').strip()

    if not token or not mc_username:
        return jsonify({'error': '缺少 token 或 mc_username'}), 400

    user = User.query.filter_by(token=token).first()
    if not user:
        return jsonify({'error': 'token 無效'}), 401

    user.mc_username = mc_username
    db.session.commit()

    return jsonify({'message': f'成功綁定 {mc_username}'}), 200

@app.route('/api/bind/discord', methods=['POST'])
def bind_discord():
    from flask import request
    data = request.get_json()

    token = data.get('token', '').strip()
    discord_id = data.get('discord_id', '').strip()

    if not token or not discord_id:
        return jsonify({'error': '缺少 token 或 discord_id'}), 400

    user = User.query.filter_by(token=token).first()
    if not user:
        return jsonify({'error': 'token 無效'}), 401

    user.discord_id = discord_id
    db.session.commit()

    return jsonify({'message': f'成功綁定 Discord'}), 200

@app.route('/api/players', methods=['GET'])
def online_players():
    try:
        res = requests.get(f"{PLUGIN_API}/players", timeout=5)
        res.raise_for_status()
        data = res.json()
        players = data.get("players", "")
        player_list = players.split(",") if players else []
        return jsonify({ "online": player_list })
    except Exception as e:
        return jsonify({ "error": str(e) }), 500


@app.route('/api/player/<name>', methods=['GET'])
def player_info(name):
    try:
        res = requests.get(f"{PLUGIN_API}/players", timeout=5)
        res.raise_for_status()
        data = res.json()
        players = data.get("players", "")
        player_list = players.split(",") if players else []
        is_online = name in player_list

        location = None
        if is_online:
            loc_res = requests.get(f"{PLUGIN_API}/player/{name}", timeout=5)
            if loc_res.status_code == 200:
                location = loc_res.json()

        return jsonify({
            "name": name,
            "online": is_online,
            "location": location
        })
    except Exception as e:
        return jsonify({ "error": str(e) }), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')