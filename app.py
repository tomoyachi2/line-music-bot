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

user_states = {}

@app.route("/", methods=['GET'])
def home():
    return "🎵 LINE Music Bot が動作中です！24時間稼働！"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    print("📨 メッセージを受信")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    message_text = event.message.text.strip()
    
    if message_text == "テスト":
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="✅ 24時間稼働ボット接続成功！")
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
        threading.Thread(
            target=search_and_process,
            args=(user_id, message_text)
        ).start()
        user_states[user_id] = None
    
    else:
        show_usage(event.reply_token)

def show_usage(reply_token):
    usage_text = """🎵 24時間音楽ボット

【使い方】
• 「テスト」: 接続確認
• 「曲をダウンロード」: 曲を検索
• 「使い方」: この説明"""

    line_bot_api.reply_message(
        reply_token,
        TextSendMessage(text=usage_text)
    )

def search_and_process(user_id, song_name):
    try:
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text="🔍 YouTubeを検索中...")
        )
        
        video_info = search_youtube(song_name)
        
        if not video_info:
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text="❌ 曲が見つかりませんでした")
            )
            return
        
        duration = video_info['duration']
        mins, secs = divmod(duration, 60)
        
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=f"✅ 見つかりました！\nタイトル: {video_info['title']}\n長さ: {mins}分{secs}秒")
        )
        
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text="🎧 検索完了！")
        )
        
    except Exception as e:
        print(f"エラー: {e}")
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text="😢 エラーが発生しました")
        )

def search_youtube(query):
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
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Server starting on port {port}")
    app.run(host='0.0.0.0', port=port)

import dropbox
from dropbox.exceptions import AuthError

def get_dropbox_client():
    """Dropboxクライアントを取得"""
    try:
        access_token = os.environ.get('DROPBOX_ACCESS_TOKEN')
        if not access_token:
            print("❌ Dropboxアクセストークンが設定されていません")
            return None
        return dropbox.Dropbox(access_token)
    except Exception as e:
        print(f"Dropbox接続エラー: {e}")
        return None

def upload_to_dropbox(file_path, file_name):
    """Dropboxにアップロードして共有リンクを生成"""
    try:
        dbx = get_dropbox_client()
        if not dbx:
            return None
        
        # ファイル名を安全な形式に
        safe_name = "".join(c for c in file_name if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
        
        # Dropboxにアップロード
        with open(file_path, 'rb') as f:
            result = dbx.files_upload(
                f.read(),
                f'/{safe_name}',
                mode=dropbox.files.WriteMode.overwrite
            )
        
        print(f"✅ Dropboxアップロード成功: {safe_name}")
        
        # 共有リンクを作成
        shared_link = dbx.sharing_create_shared_link(result.path_display)
        return shared_link.url
        
    except AuthError as e:
        print(f"Dropbox認証エラー: {e}")
        return None
    except Exception as e:
        print(f"Dropboxアップロードエラー: {e}")
        return None

def download_audio(video_url):
    """YouTubeから音声をダウンロード"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp_file:
            output_template = tmp_file.name.replace('.mp3', '.%(ext)s')
        
        cmd = [
            'yt-dlp',
            '-x',
            '--audio-format', 'mp3', 
            '--audio-quality', '0',
            '--no-overwrites',
            '--quiet',
            '-o', output_template,
            video_url
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode == 0:
            mp3_file = output_template.replace('.%(ext)s', '.mp3')
            if os.path.exists(mp3_file):
                return mp3_file
        return None
        
    except Exception as e:
        print(f"ダウンロードエラー: {e}")
        return None

