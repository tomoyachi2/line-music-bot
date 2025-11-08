# app.py - 完成版
import os
import json
import subprocess
import threading
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# LINEの設定
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ユーザーの状態を記憶する辞書
user_states = {}

@app.route("/", methods=['GET'])
def home():
    return "🎵 LINE Music Bot が動作中です！"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    print("📨 メッセージを受信:", body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    message_text = event.message.text.strip()
    
    print(f"👤 {user_id}: {message_text}")
    
    if message_text == "テスト":
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="✅ ボット接続成功！音楽ダウンロードボットです。")
        )
    
    elif message_text == "使い方":
        show_usage(event.reply_token)
    
    elif message_text == "曲をダウンロード":
        user_states[user_id] = 'waiting_song_name'
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="🎵 曲名を入力してください\n例: Lemon 米津玄師")
        )
    
    elif user_states.get(user_id) == 'waiting_song_name':
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"🔍 「{message_text}」を検索中...")
        )
        # バックグラウンドで処理
        threading.Thread(
            target=search_and_process,
            args=(user_id, message_text)
        ).start()
        user_states[user_id] = None
    
    else:
        show_usage(event.reply_token)

def show_usage(reply_token):
    usage_text = """🎵 音楽ダウンロードボット

【使い方】
• 「テスト」: 接続確認
• 「曲をダウンロード」: 曲をダウンロード開始
• 「使い方」: この説明

まずは「テスト」と送信してみてください！"""
    
    line_bot_api.reply_message(
        reply_token,
        TextSendMessage(text=usage_text)
    )

def search_and_process(user_id, song_name):
    """曲を検索して処理"""
    try:
        # 検索中メッセージ
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text="🔍 YouTubeを検索中...")
        )
        
        # YouTube検索
        video_info = search_youtube(song_name)
        
        if not video_info:
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text="❌ 曲が見つかりませんでした")
            )
            return
        
        # 検索結果を通知
        duration = video_info['duration']
        mins, secs = divmod(duration, 60)
        
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=f"✅ 見つかりました！\nタイトル: {video_info['title']}")
        )
        
        # ダウンロード機能（次のステップで実装）
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text="🎧 検索機能は動作しました！\nダウンロード機能は準備中です。")
        )
        
    except Exception as e:
        print(f"エラー: {e}")
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text="😢 エラーが発生しました")
        )

def search_youtube(query):
    """YouTubeを検索"""
    try:
        cmd = [
            'yt-dlp',
            f"ytsearch1:{query}",
            '--dump-json',
            '--no-warnings',
            '--quiet'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.stdout.strip():
            data = json.loads(result.stdout)
            return {
                'title': data.get('title', ''),
                'url': data.get('webpage_url', ''),
                'duration': data.get('duration', 0),
                'uploader': data.get('uploader', '')
            }
        return None
    except Exception as e:
        print(f"検索エラー: {e}")
        return None

if __name__ == "__main__":
    print("🚀 LINE Bot サーバーを起動します...")
    
    # ngrokで公開URLを取得
    public_url = ngrok.connect(5000).public_url
    webhook_url = f"{public_url}/callback"
    
    print("🎉 あなたのWebhook URL:")
    print("=" * 50)
    print(f"👉 {webhook_url}")
    print("=" * 50)
    print("\nこのURLをLINE Developersに設定してください")
    

    app.run(host='0.0.0.0', port=5000, debug=False)
