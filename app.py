import os
import json
import tempfile
import subprocess
import threading
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import dropbox
from dropbox.exceptions import AuthError

app = Flask(__name__)

# 環境変数の設定
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
DROPBOX_ACCESS_TOKEN = os.environ.get('DROPBOX_ACCESS_TOKEN')

# 環境変数チェック
if not all([LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET]):
    print("❌ LINEの環境変数が設定されていません")
if not DROPBOX_ACCESS_TOKEN:
    print("❌ Dropboxの環境変数が設定されていません")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ユーザーの状態管理
user_states = {}

@app.route("/", methods=['GET'])
def home():
    return "🎵 LINE Music Bot が動作中です！Dropbox連携済み"

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
    
    print(f"👤 {user_id}: {message_text}")
    
    if message_text == "テスト":
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="✅ ボットは正常に動作しています！Dropbox連携OK")
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
    usage_text = """🎵 LINE音楽ダウンローダー

【使い方】
• 「テスト」: 接続確認
• 「曲をダウンロード」: MP3をダウンロード
• 「使い方」: この説明

※ MP3はDropboxに保存され、ダウンロードリンクが送信されます"""
    
    line_bot_api.reply_message(
        reply_token,
        TextSendMessage(text=usage_text)
    )

def get_dropbox_client():
    """Dropboxクライアントを取得"""
    try:
        if not DROPBOX_ACCESS_TOKEN:
            return None
        return dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)
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
        safe_name = safe_name[:100]  # 長すぎる名前を制限
        
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
        print(f"🔗 共有リンク: {shared_link.url}")
        return shared_link.url
        
    except AuthError as e:
        print(f"Dropbox認証エラー: {e}")
        return None
    except Exception as e:
        print(f"Dropboxアップロードエラー: {e}")
        return None

def search_youtube(query):
    """改善版YouTube検索"""
    try:
        # 検索クエリを強化
        enhanced_query = f"{query} 音楽"
        print(f"🔍 検索クエリ: {enhanced_query}")
        
        cmd = [
            'yt-dlp',
            f"ytsearch3:{enhanced_query}",  # 3件検索
            '--dump-json',
            '--no-warnings',
            '--quiet',
            '--match-filter', "duration < 600"  # 10分以内の動画のみ
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        videos = []
        for line in result.stdout.strip().split('\n'):
            if line:
                try:
                    data = json.loads(line)
                    video_info = {
                        'title': data.get('title', ''),
                        'url': data.get('webpage_url', ''),
                        'duration': data.get('duration', 0),
                        'uploader': data.get('uploader', ''),
                        'view_count': data.get('view_count', 0)
                    }
                    
                    # 音楽らしい動画を優先
                    score = calculate_music_score(video_info)
                    video_info['score'] = score
                    videos.append(video_info)
                    
                    print(f"🎵 検索結果: {video_info['title']} (スコア: {score})")
                    
                except Exception as e:
                    print(f"解析エラー: {e}")
                    continue
        
        # スコアが高い順にソート
        if videos:
            videos.sort(key=lambda x: x['score'], reverse=True)
            best_video = videos[0]
            print(f"✅ 最適な動画を選択: {best_video['title']}")
            return best_video
        
        print("❌ 検索結果が見つかりませんでした")
        return None
        
    except Exception as e:
        print(f"検索エラー: {e}")
        return None

def calculate_music_score(video_info):
    """音楽動画らしさをスコアリング"""
    score = 0
    title = video_info['title'].lower()
    duration = video_info['duration']
    uploader = video_info['uploader'].lower()
    
    # タイトルに音楽関連キーワードがあるか
    music_keywords = [
        'official', 'mv', 'music', 'audio', 'full',
        'lyric', 'lyrics', '歌ってみた', 'カバー'
    ]
    
    for keyword in music_keywords:
        if keyword in title:
            score += 2
    
    # 適切な長さか（2分〜8分）
    if 120 <= duration <= 480:  # 2-8分
        score += 3
    elif 60 <= duration <= 600:  # 1-10分
        score += 1
    
    # アーティスト名らしいか
    artist_keywords = ['topic', 'vevo', 'records', 'music']
    if any(keyword in uploader for keyword in artist_keywords):
        score += 1
    
    # 閲覧数が多いほど高スコア
    view_count = video_info.get('view_count', 0)
    if view_count > 1000000:  # 100万回以上
        score += 2
    elif view_count > 100000:  # 10万回以上
        score += 1
    
    return score

def search_and_process(user_id, song_name):
    """改善版検索処理"""
    try:
        line_bot_api.push_message(user_id, TextSendMessage(text="🔍 最適な曲を検索中..."))
        
        # YouTube検索
        video_info = search_youtube(song_name)
        if not video_info:
            line_bot_api.push_message(
                user_id, 
                TextSendMessage(text="❌ 曲が見つかりませんでした\n別のキーワードでお試しください")
            )
            return
        
        # 動画情報を表示
        duration = video_info['duration']
        mins, secs = divmod(duration, 60)
        
        message = f"""✅ 見つかりました！

🎵 タイトル: {video_info['title']}
👤 アーティスト: {video_info['uploader']}
⏱ 長さ: {mins}分{secs}秒
👁 閲覧数: {video_info.get('view_count', 0):,}回

🔗 {video_info['url']}"""

        line_bot_api.push_message(user_id, TextSendMessage(text=message))
        
        # MP3ダウンロードオプションを提供
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text="📥 この曲をMP3でダウンロードしますか？\n（現在準備中）")
        )
        
    except Exception as e:
        print(f"処理エラー: {e}")
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text="😢 エラーが発生しました")
        )

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
                # ファイルサイズをチェック
                file_size = os.path.getsize(mp3_file) / (1024 * 1024)  # MB
                print(f"📦 ダウンロード成功: {mp3_file} ({file_size:.1f}MB)")
                return mp3_file
        return None
        
    except Exception as e:
        print(f"ダウンロードエラー: {e}")
        return None

def search_and_process(user_id, song_name):
    """検索とダウンロード処理のメイン関数"""
    try:
        line_bot_api.push_message(user_id, TextSendMessage(text="🔍 YouTubeを検索中..."))
        
        # YouTube検索
        video_info = search_youtube(song_name)
        if not video_info:
            line_bot_api.push_message(user_id, TextSendMessage(text="❌ 曲が見つかりませんでした"))
            return
        
        # 動画情報を表示
        duration = video_info['duration']
        mins, secs = divmod(duration, 60)
        line_bot_api.push_message(
            user_id, 
            TextSendMessage(
                text=f"✅ 見つかりました！\n"
                     f"タイトル: {video_info['title']}\n"
                     f"アーティスト: {video_info['uploader']}\n"
                     f"長さ: {mins}分{secs}秒\n\n"
                     f"📥 MP3をダウンロード中..."
            )
        )
        
        # MP3ダウンロード
        mp3_file = download_audio(video_info['url'])
        if not mp3_file:
            line_bot_api.push_message(user_id, TextSendMessage(text="❌ MP3のダウンロードに失敗しました"))
            return
        
        line_bot_api.push_message(user_id, TextSendMessage(text="☁️ Dropboxにアップロード中..."))
        
        # Dropboxにアップロード
        file_name = f"{video_info['title']}.mp3"
        dropbox_link = upload_to_dropbox(mp3_file, file_name)
        
        # 一時ファイルを削除
        try:
            os.unlink(mp3_file)
            print(f"🗑️ 一時ファイル削除: {mp3_file}")
        except Exception as e:
            print(f"ファイル削除エラー: {e}")
        
        if dropbox_link:
            # 成功メッセージ
            line_bot_api.push_message(
                user_id,
                TextSendMessage(
                    text=f"🎉 MP3の準備が完了しました！\n\n"
                         f"📁 ファイル名: {video_info['title']}.mp3\n"
                         f"🔗 ダウンロードリンク:\n"
                         f"{dropbox_link}\n\n"
                         f"※ リンクをタップしてダウンロードしてください"
                )
            )
        else:
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text="❌ Dropboxへのアップロードに失敗しました")
            )
            
    except Exception as e:
        print(f"処理エラー: {e}")
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text="😢 エラーが発生しました。しばらくしてから再度お試しください")
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Server starting on port {port}")
    print(f"✅ LINE_TOKEN: {'設定済み' if LINE_CHANNEL_ACCESS_TOKEN else '未設定'}")
    print(f"✅ DROPBOX_TOKEN: {'設定済み' if DROPBOX_ACCESS_TOKEN else '未設定'}")
    app.run(host='0.0.0.0', port=port)

