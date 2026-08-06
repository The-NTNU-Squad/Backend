from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import requests
import os
from functools import wraps
from datetime import date, datetime, timezone, timedelta
from dotenv import load_dotenv
from flask_bcrypt import Bcrypt
import secrets
from apscheduler.schedulers.background import BackgroundScheduler
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
PLUGIN_SECRET = os.getenv("PLUGIN_SECRET")
ADMIN_SECRET = os.getenv("ADMIN_SECRET")
# ------------------------------------------------------------------
# 驗證 decorator：保護只該由 MC plugin / DC bot 呼叫的 API
# ------------------------------------------------------------------
def require_plugin_secret(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        secret = request.headers.get('X-Plugin-Secret')
        if not PLUGIN_SECRET or not secret or secret != PLUGIN_SECRET:
            return jsonify({'error': '未授權'}), 403
        return f(*args, **kwargs)
    return wrapper

def require_admin_secret(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        secret = request.headers.get('X-Admin-Secret')
        if not ADMIN_SECRET or not secret or secret != ADMIN_SECRET:
            return jsonify({'error': '未授權'}), 403
        return f(*args, **kwargs)
    return wrapper

def require_admin_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get('X-Token')
        if not token:
            return jsonify({'error': '未提供 token'}), 401
        user = User.query.filter_by(token=token).first()
        if not user or not user.is_admin:
            return jsonify({'error': '權限不足'}), 403
        return f(*args, **kwargs)
    return wrapper
# ------------------------------------------------------------------
# 商店管理 API（僅限 admin）
# ------------------------------------------------------------------

@app.route('/api/admin/shop/items', methods=['GET'])
@require_admin_login
def admin_list_items():
    items = ShopItem.query.all()
    return jsonify([{
        "id": i.id,
        "name": i.name,
        "description": i.description,
        "price": i.price,
        "mc_give_command": i.mc_give_command,
        "image_url": i.image_url,
        "enabled": i.enabled
    } for i in items]), 200


@app.route('/api/admin/shop/items', methods=['POST'])
@require_admin_login
def admin_create_item():
    data = request.get_json()

    name = data.get('name', '').strip()
    price = data.get('price')
    mc_give_command = data.get('mc_give_command', '').strip()
    description = data.get('description', '').strip()
    image_url = data.get('image_url')
    enabled = data.get('enabled', True)

    if not name or not mc_give_command or price is None:
        return jsonify({'error': '缺少必要欄位（name, price, mc_give_command）'}), 400

    if not isinstance(price, int) or price <= 0:
        return jsonify({'error': 'price 必須是正整數'}), 400

    item = ShopItem(
        name=name,
        description=description,
        price=price,
        mc_give_command=mc_give_command,
        enchant_info=data.get('enchant_info'),
        image_url=image_url,
        enabled=enabled
    )
    db.session.add(item)
    db.session.commit()

    return jsonify({'message': f'商品「{name}」新增成功', 'id': item.id}), 201


@app.route('/api/admin/shop/items/<int:item_id>', methods=['PUT'])
@require_admin_login
def admin_update_item(item_id):
    item = ShopItem.query.get(item_id)
    if not item:
        return jsonify({'error': '找不到此商品'}), 404

    data = request.get_json()

    if 'name' in data:
        item.name = data['name'].strip()
    if 'description' in data:
        item.description = data['description'].strip()
    if 'price' in data:
        if not isinstance(data['price'], int) or data['price'] <= 0:
            return jsonify({'error': 'price 必須是正整數'}), 400
        item.price = data['price']
    if 'mc_give_command' in data:
        item.mc_give_command = data['mc_give_command'].strip()
    if 'image_url' in data:
        item.image_url = data['image_url']
    if 'enchant_info' in data:
        item.enchant_info = data['enchant_info']
    if 'enabled' in data:
        item.enabled = data['enabled']

    db.session.commit()
    return jsonify({'message': f'商品「{item.name}」已更新'}), 200


@app.route('/api/admin/shop/items/<int:item_id>', methods=['DELETE'])
@require_admin_login
def admin_delete_item(item_id):
    item = ShopItem.query.get(item_id)
    if not item:
        return jsonify({'error': '找不到此商品'}), 404

    # 用軟刪除（下架），不是真的砍掉，保留歷史購買紀錄的關聯完整性
    item.enabled = False
    db.session.commit()
    return jsonify({'message': f'商品「{item.name}」已下架'}), 200


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
    last_discord_checkin = db.Column(db.Date, nullable=True)
    pending_discord_reward = db.Column(db.Integer, default=0)
    last_web_checkin = db.Column(db.Date, nullable=True)
    pending_web_reward = db.Column(db.Integer, default=0)
    coin_balance = db.Column(db.Integer, default=0, nullable=False)  # 累積金幣，網站顯示用
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    unlocked_level = db.Column(db.Integer, default=1, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "token": self.token,
            "mc_username": self.mc_username,
            "discord_id": self.discord_id,
            "coin_balance": self.coin_balance,
            "created_at": str(self.created_at),
            "is_admin": self.is_admin,
            "unlocked_level": self.unlocked_level
        }

class ShopItem(db.Model):
    __tablename__ = "shop_items"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    price = db.Column(db.Integer, nullable=False)
    mc_give_command = db.Column(db.String(255), nullable=False)  # plugin 發放時要用的道具代號/指令
    enchant_info = db.Column(db.String(255), nullable=True) # 附魔說明
    image_url = db.Column(db.String(255), nullable=True)
    enabled = db.Column(db.Boolean, default=True, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "price": self.price,
            "enchant_info": self.enchant_info,
            "image_url": self.image_url,
        }


class PendingDelivery(db.Model):
    __tablename__ = "pending_deliveries"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("shop_items.id"), nullable=False)
    delivered = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship("User")
    item = db.relationship("ShopItem")

# 副本獎勵紀錄（防作弊稽核 + 之後排行榜用）
class DungeonReward(db.Model):
    __tablename__ = "dungeon_rewards"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    dungeon_level = db.Column(db.Integer, nullable=False)
    coins_earned = db.Column(db.Integer, nullable=False)
    clear_time_ms = db.Column(db.BigInteger, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship("User", backref="dungeon_rewards")

class PlayerCountLog(db.Model):
    __tablename__ = "player_count_logs"
    id = db.Column(db.Integer, primary_key=True)
    count = db.Column(db.Integer, nullable=False)
    recorded_at = db.Column(db.DateTime, server_default=db.func.now())

class ServerAlert(db.Model):
    __tablename__ = "server_alerts"
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False)  # 例如 "player_count_drop"
    message = db.Column(db.String(255), nullable=False)
    resolved = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "message": self.message,
            "resolved": self.resolved,
            "created_at": str(self.created_at),
        }

# 新增：每次進入副本的紀錄（不論有沒有通關）
class DungeonPlay(db.Model):
    __tablename__ = "dungeon_plays"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    dungeon_level = db.Column(db.Integer, nullable=False)
    started_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship("User", backref="dungeon_plays")

@app.route('/')
def index():
    return jsonify({'message': 'Hello, World!'})


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/api/auth/register', methods=['POST'])
def register():
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
    token = request.headers.get('X-Token')

    if not token:
        return jsonify({'error': '未提供 token'}), 401

    user = User.query.filter_by(token=token).first()

    if not user:
        return jsonify({'error': 'token 無效'}), 401

    return jsonify(user.to_dict()), 200

@app.route('/api/bind/mc', methods=['POST'])
@require_plugin_secret
def bind_mc():
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
@require_plugin_secret
def bind_discord():
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

@app.route('/api/user/me/discord', methods=['GET'])
@require_plugin_secret
def user_me_discord():
    discord_id = request.args.get('discord_id', '').strip()

    if not discord_id:
        return jsonify({'error': '缺少 discord_id'}), 400

    user = User.query.filter_by(discord_id=discord_id).first()
    if not user:
        return jsonify({'error': '找不到綁定帳號'}), 404

    return jsonify(user.to_dict()), 200

@app.route('/api/user/me/mc', methods=['GET'])
@require_plugin_secret
def user_me_mc():
    mc_username = request.args.get('mc_username', '').strip()

    if not mc_username:
        return jsonify({'error': '缺少 mc_username'}), 400

    user = User.query.filter_by(mc_username=mc_username).first()
    if not user:
        return jsonify({'error': '找不到綁定帳號'}), 404

    return jsonify(user.to_dict()), 200

@app.route('/api/players', methods=['GET'])
@require_plugin_secret
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
@require_plugin_secret
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

@app.route('/api/checkin/discord', methods=['POST'])
@require_plugin_secret
def checkin_discord():
    data = request.get_json()
    discord_id = data.get('discord_id', '').strip()

    if not discord_id:
        return jsonify({'error': '缺少 discord_id'}), 400

    user = User.query.filter_by(discord_id=discord_id).first()
    if not user:
        return jsonify({'error': '找不到綁定帳號，請先用 /bind 綁定'}), 404

    # 台灣時間 UTC+8
    tw_now = datetime.now(timezone(timedelta(hours=8))).date()

    if user.last_discord_checkin == tw_now:
        return jsonify({'error': '今天已經簽到過了'}), 409

    user.last_discord_checkin = tw_now
    user.pending_discord_reward = (user.pending_discord_reward or 0) + 1
    db.session.commit()

    return jsonify({'message': '簽到成功！登入 Minecraft 後會收到一顆綠寶石'}), 200

@app.route('/api/reward/claim', methods=['POST'])
@require_plugin_secret
def claim_reward():
    data = request.get_json()
    mc_username = data.get('mc_username', '').strip()

    if not mc_username:
        return jsonify({'error': '缺少 mc_username'}), 400

    user = User.query.filter_by(mc_username=mc_username).first()
    if not user:
        return jsonify({'reward': 0}), 200

    total = (user.pending_discord_reward or 0) + (user.pending_web_reward or 0)
    if total > 0:
        user.pending_discord_reward = 0
        user.pending_web_reward = 0
        db.session.commit()

    return jsonify({'reward': total}), 200

@app.route('/api/reward/check', methods=['GET'])
@require_plugin_secret
def check_reward():
    mc_username = request.args.get('mc_username', '').strip()

    if not mc_username:
        return jsonify({'error': '缺少 mc_username'}), 400

    user = User.query.filter_by(mc_username=mc_username).first()
    if not user:
        return jsonify({'reward': 0}), 200

    total = (user.pending_discord_reward or 0) + (user.pending_web_reward or 0)
    return jsonify({'reward': total}), 200

@app.route('/api/checkin/web', methods=['POST'])
def checkin_web():
    token = request.headers.get('X-Token')

    if not token:
        return jsonify({'error': '未提供 token'}), 401

    user = User.query.filter_by(token=token).first()
    if not user:
        return jsonify({'error': 'token 無效'}), 401

    tw_now = datetime.now(timezone(timedelta(hours=8))).date()

    if user.last_web_checkin == tw_now:
        return jsonify({'error': '今天已經簽到過了'}), 409

    user.last_web_checkin = tw_now
    user.pending_web_reward = (user.pending_web_reward or 0) + 1
    db.session.commit()

    return jsonify({'message': '簽到成功！登入 Minecraft 後會收到一顆綠寶石'}), 200

@app.route('/api/dungeon/start', methods=['POST'])
@require_plugin_secret
def dungeon_start():
    data = request.get_json()
    mc_username = data.get('mc_username', '').strip()
    dungeon_level = data.get('dungeon_level')

    if not mc_username or dungeon_level is None:
        return jsonify({'error': '缺少必要欄位'}), 400

    user = User.query.filter_by(mc_username=mc_username).first()
    if not user:
        return jsonify({'error': '找不到綁定帳號'}), 404

    db.session.add(DungeonPlay(user_id=user.id, dungeon_level=dungeon_level))
    db.session.commit()

    return jsonify({'message': 'ok'}), 200

@app.route('/api/dungeon/complete', methods=['POST'])
@require_plugin_secret
def dungeon_complete():
    data = request.get_json()
    mc_username = data.get('mc_username', '').strip()
    dungeon_level = data.get('dungeon_level')
    coins_earned = data.get('coins_earned')
    clear_time_ms = data.get('clear_time_ms')  # 新增，可為 None

    if not mc_username or dungeon_level is None or coins_earned is None:
        return jsonify({'error': '缺少必要欄位'}), 400

    if not isinstance(coins_earned, int) or coins_earned <= 0:
        return jsonify({'error': 'coins_earned 必須是正整數'}), 400

    user = User.query.filter_by(mc_username=mc_username).first()
    if not user:
        return jsonify({'error': '找不到綁定帳號'}), 404

    user.coin_balance = (user.coin_balance or 0) + coins_earned
    db.session.add(DungeonReward(
        user_id=user.id,
        dungeon_level=dungeon_level,
        coins_earned=coins_earned,
        clear_time_ms=clear_time_ms  # 新增
    ))
    db.session.commit()

    return jsonify({
        'message': f'第 {dungeon_level} 關完成，獲得 {coins_earned} 金幣',
        'coin_balance': user.coin_balance
    }), 200

@app.route('/api/dungeon/unlock', methods=['POST'])
@require_plugin_secret
def dungeon_unlock():
    data = request.get_json()
    mc_username = data.get('mc_username', '').strip()
    unlocked_level = data.get('unlocked_level')

    if not mc_username or unlocked_level is None:
        return jsonify({'error': '缺少必要欄位'}), 400

    user = User.query.filter_by(mc_username=mc_username).first()
    if not user:
        return jsonify({'error': '找不到綁定帳號'}), 404

    # 只往上解鎖，不會因為傳入較小的值而倒退
    if unlocked_level > user.unlocked_level:
        user.unlocked_level = unlocked_level
        db.session.commit()

    return jsonify({'unlocked_level': user.unlocked_level}), 200

@app.route('/api/dungeon/stats', methods=['GET'])
@require_plugin_secret
def dungeon_stats():
    mc_username = request.args.get('mc_username', '').strip()
    if not mc_username:
        return jsonify({'error': '缺少 mc_username'}), 400

    user = User.query.filter_by(mc_username=mc_username).first()
    if not user:
        return jsonify({'stats': {}}), 200

    play_counts = db.session.query(
        DungeonPlay.dungeon_level, db.func.count(DungeonPlay.id)
    ).filter_by(user_id=user.id).group_by(DungeonPlay.dungeon_level).all()

    avg_times = db.session.query(
        DungeonReward.dungeon_level, db.func.avg(DungeonReward.clear_time_ms)
    ).filter_by(user_id=user.id).filter(
        DungeonReward.clear_time_ms.isnot(None)
    ).group_by(DungeonReward.dungeon_level).all()

    stats = {}
    for level, count in play_counts:
        stats[str(level)] = {'play_count': count, 'avg_clear_time_ms': 0}
    for level, avg_ms in avg_times:
        key = str(level)
        if key not in stats:
            stats[key] = {'play_count': 0, 'avg_clear_time_ms': 0}
        stats[key]['avg_clear_time_ms'] = int(avg_ms) if avg_ms else 0

    return jsonify({'stats': stats}), 200

@app.route('/api/shop/items', methods=['GET'])
def shop_items():
    items = ShopItem.query.filter_by(enabled=True).all()
    return jsonify([i.to_dict() for i in items]), 200


@app.route('/api/shop/purchase', methods=['POST'])
def shop_purchase():
    token = request.headers.get('X-Token')
    if not token:
        return jsonify({'error': '未提供 token'}), 401

    user = User.query.filter_by(token=token).first()
    if not user:
        return jsonify({'error': 'token 無效'}), 401

    data = request.get_json()
    item_id = data.get('item_id')
    if not item_id:
        return jsonify({'error': '缺少 item_id'}), 400

    item = ShopItem.query.filter_by(id=item_id, enabled=True).first()
    if not item:
        return jsonify({'error': '找不到此商品'}), 404

    if not user.mc_username:
        return jsonify({'error': '請先綁定 Minecraft 帳號'}), 400

    if user.coin_balance < item.price:
        return jsonify({'error': '金幣不足'}), 400

    user.coin_balance -= item.price
    db.session.add(PendingDelivery(user_id=user.id, item_id=item.id))
    db.session.commit()

    return jsonify({
        'message': f'購買成功！{item.name} 將於你上線後發放',
        'coin_balance': user.coin_balance
    }), 200

@app.route('/api/delivery/check', methods=['GET'])
@require_plugin_secret
def delivery_check():
    mc_username = request.args.get('mc_username', '').strip()
    user = User.query.filter_by(mc_username=mc_username).first()
    if not user:
        return jsonify({'items': []}), 200

    pending = PendingDelivery.query.filter_by(user_id=user.id, delivered=False).all()
    return jsonify({
        'items': [{'delivery_id': p.id, 'command': p.item.mc_give_command} for p in pending]
    }), 200


@app.route('/api/delivery/claim', methods=['POST'])
@require_plugin_secret
def delivery_claim():
    data = request.get_json()
    delivery_ids = data.get('delivery_ids', [])
    PendingDelivery.query.filter(PendingDelivery.id.in_(delivery_ids)) \
        .update({'delivered': True}, synchronize_session=False)
    db.session.commit()
    return jsonify({'message': 'ok'}), 200

@app.route('/api/admin/monitor/player-count', methods=['GET'])
@require_admin_login
def monitor_player_count():
    hours = request.args.get('hours', 6, type=int)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    logs = PlayerCountLog.query.filter(PlayerCountLog.recorded_at >= since) \
        .order_by(PlayerCountLog.recorded_at.asc()).all()
    return jsonify([
        {"count": l.count, "recorded_at": str(l.recorded_at)} for l in logs
    ]), 200


@app.route('/api/admin/monitor/alerts', methods=['GET'])
@require_admin_login
def monitor_alerts():
    alerts = ServerAlert.query.order_by(ServerAlert.created_at.desc()).limit(50).all()
    return jsonify([a.to_dict() for a in alerts]), 200


@app.route('/api/admin/monitor/alerts/<int:alert_id>/resolve', methods=['POST'])
@require_admin_login
def resolve_alert(alert_id):
    alert = ServerAlert.query.get(alert_id)
    if not alert:
        return jsonify({'error': '找不到此警告'}), 404
    alert.resolved = True
    db.session.commit()
    return jsonify({'message': '已標記為已處理'}), 200

def check_player_count():
    with app.app_context():
        try:
            res = requests.get(f"{PLUGIN_API}/players", timeout=5)
            res.raise_for_status()
            data = res.json()
            players = data.get("players", "")
            count = len(players.split(",")) if players else 0
        except Exception as e:
            app.logger.warning(f"排程查詢線上人數失敗: {e}")
            return

        db.session.add(PlayerCountLog(count=count))
        db.session.commit()

        # 簡單規則：查最近 5 筆記錄，若全部都是 0 人，且過去 1 小時內平均人數 > 0，才視為異常
        recent = PlayerCountLog.query.order_by(PlayerCountLog.id.desc()).limit(5).all()
        if len(recent) == 5 and all(r.count == 0 for r in recent):
            one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
            hist = PlayerCountLog.query.filter(PlayerCountLog.recorded_at >= one_hour_ago).all()
            avg = sum(r.count for r in hist) / len(hist) if hist else 0

            if avg > 0:
                # 避免重複發同一個未解決的警告
                existing = ServerAlert.query.filter_by(type="player_count_drop", resolved=False).first()
                if not existing:
                    db.session.add(ServerAlert(
                        type="player_count_drop",
                        message="連續 5 次查詢在線人數皆為 0，可能伺服器異常"
                    ))
                    db.session.commit()

if __name__ == '__main__':
    import os
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        scheduler = BackgroundScheduler()
        scheduler.add_job(check_player_count, 'interval', minutes=1)
        scheduler.start()
    app.run(debug=True, host='0.0.0.0')