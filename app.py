from flask import Flask, jsonify
from flask_cors import CORS
import requests
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

PLUGIN_API = os.getenv("PLUGIN_API", "http://localhost:8080")


@app.route('/')
def index():
    return jsonify({'message': 'Hello, World!'})


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


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
        # 取得在線玩家清單
        res = requests.get(f"{PLUGIN_API}/players", timeout=5)
        res.raise_for_status()
        data = res.json()
        players = data.get("players", "")
        player_list = players.split(",") if players else []
        is_online = name in player_list

        # 如果在線才查位置
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
    app.run(debug=True)