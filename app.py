import os
import tempfile
import threading
import logging
from datetime import datetime
from flask import Flask, request, jsonify
import yt_dlp
from urllib.parse import quote

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# インメモリストレージ（本番ではデータベースを使用）
jobs_db = {}

@app.route('/')
def home():
    return jsonify({
        "status": "MP3 Converter API is running!",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "convert": "POST /api/convert",
            "status": "GET /api/status/<job_id>",
            "health": "GET /health"
        }
    })

@app.route('/api/convert', methods=['POST'])
def convert_mp3():
    try:
        data = request.get_json()
        
        # 必須フィールドの検証
        required_fields = ['songName', 'videoUrl', 'userEmail']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    "success": False,
                    "error": f"Missing required field: {field}"
                }), 400
        
        song_name = data['songName']
        video_url = data['videoUrl']
        user_email = data['userEmail']
        
        logger.info(f"変換リクエスト受信: {song_name} - {user_email}")
        
        # ジョブIDを生成
        job_id = generate_job_id(song_name)
        
        # ジョブ情報を保存
        jobs_db[job_id] = {
            "status": "processing",
            "song_name": song_name,
            "user_email": user_email,
            "video_url": video_url,
            "created_at": datetime.now().isoformat(),
            "progress": "開始待機中"
        }
        
        # 非同期で変換を開始
        thread = threading.Thread(
            target=process_conversion,
            args=(job_id, song_name, video_url, user_email),
            daemon=True
        )
        thread.start()
        
        logger.info(f"ジョブ開始: {job_id}")
        
        return jsonify({
            "success": True,
            "jobId": job_id,
            "status": "processing",
            "message": "MP3変換を開始しました",
            "estimatedTime": "2-5分"
        })
        
    except Exception as e:
        logger.error(f"変換エラー: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"内部サーバーエラー: {str(e)}"
        }), 500

def process_conversion(job_id, song_name, video_url, user_email):
    """非同期でMP3変換を処理"""
    try:
        # ジョブステータスを更新
        jobs_db[job_id].update({
            "status": "downloading",
            "progress": "YouTubeからダウンロード中",
            "started_at": datetime.now().isoformat()
        })
        
        # 一時ディレクトリで処理
        with tempfile.TemporaryDirectory() as temp_dir:
            # MP3をダウンロード
            mp3_path = download_audio(video_url, song_name, temp_dir, job_id)
            
            if not mp3_path:
                raise Exception("MP3のダウンロードに失敗しました")
            
            # ファイルサイズを確認
            file_size = os.path.getsize(mp3_path)
            jobs_db[job_id].update({
                "progress": "ダウンロード完了",
                "file_size": f"{file_size / 1024 / 1024:.1f}MB"
            })
            
            # ここでファイルを永続ストレージにアップロード
            # 一時的にダウンロードURLを生成（Railwayの特性上）
            download_url = create_temporary_download(mp3_path, song_name, job_id)
            
            # 完了ステータスを更新
            jobs_db[job_id].update({
                "status": "completed",
                "progress": "完了",
                "download_url": download_url,
                "completed_at": datetime.now().isoformat(),
                "file_name": f"{sanitize_filename(song_name)}.mp3"
            })
            
            logger.info(f"変換完了: {job_id} - {song_name}")
            
    except Exception as e:
        logger.error(f"変換処理エラー {job_id}: {str(e)}")
        jobs_db[job_id].update({
            "status": "failed",
            "progress": "エラー",
            "error": str(e),
            "failed_at": datetime.now().isoformat()
        })

def download_audio(video_url, song_name, output_dir, job_id):
    """yt-dlpで音声をダウンロード"""
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(output_dir, f'{sanitize_filename(song_name)}.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': False,
        'no_warnings': False,
        'progress_hooks': [lambda d: progress_hook(d, job_id)],
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 情報を取得（ダウンロード前）
            info = ydl.extract_info(video_url, download=False)
            jobs_db[job_id].update({
                "video_title": info.get('title', '不明'),
                "duration": info.get('duration', 0)
            })
            
            # ダウンロード実行
            ydl.download([video_url])
            
            # 生成されたファイルパスを探す
            expected_path = os.path.join(output_dir, f"{sanitize_filename(song_name)}.mp3")
            if os.path.exists(expected_path):
                return expected_path
            else:
                # ファイルが見つからない場合、ディレクトリ内を検索
                for file in os.listdir(output_dir):
                    if file.endswith('.mp3'):
                        return os.path.join(output_dir, file)
                return None
                
    except Exception as e:
        logger.error(f"ダウンロードエラー: {str(e)}")
        raise e

def progress_hook(d, job_id):
    """進捗状況を更新"""
    if d['status'] == 'downloading':
        jobs_db[job_id]['progress'] = f"ダウンロード中: {d.get('_percent_str', '0%')}"
    elif d['status'] == 'processing':
        jobs_db[job_id]['progress'] = "MP3に変換中"

def create_temporary_download(file_path, song_name, job_id):
    """一時的なダウンロード方法（本番ではGoogle Drive等に変更）"""
    # 注意: Railwayはエフェメラルストレージなので、実際のプロダクションでは
    # Google Drive, S3, または永続ストレージを使用してください
    
    # ここではファイル情報を返すだけ（実際のダウンロードは別途実装）
    file_size = os.path.getsize(file_path)
    return {
        "note": "ファイルはサーバー上に一時保存されています",
        "file_name": f"{sanitize_filename(song_name)}.mp3",
        "file_size": file_size,
        "job_id": job_id,
        "action": "contact_admin_for_download"
    }

def sanitize_filename(filename):
    """安全なファイル名に変換"""
    import re
    # 危険な文字を除去
    cleaned = re.sub(r'[<>:"/\\|?*]', '', filename)
    # スペースをアンダースコアに
    cleaned = re.sub(r'\s+', '_', cleaned)
    # 長さ制限
    return cleaned[:50]

def generate_job_id(song_name):
    """一意のジョブIDを生成"""
    import hashlib
    import time
    unique_string = f"{song_name}{time.time_ns()}"
    return hashlib.md5(unique_string.encode()).hexdigest()[:12]

@app.route('/api/status/<job_id>', methods=['GET'])
def get_status(job_id):
    """ジョブステータスを取得"""
    job = jobs_db.get(job_id)
    
    if not job:
        return jsonify({
            "success": False,
            "error": "ジョブが見つかりません"
        }), 404
    
    return jsonify({
        "success": True,
        "jobId": job_id,
        **job
    })

@app.route('/health', methods=['GET'])
def health_check():
    """ヘルスチェック"""
    return jsonify({
        "status": "healthy",
        "service": "MP3 Converter API",
        "timestamp": datetime.now().isoformat(),
        "active_jobs": len([j for j in jobs_db.values() if j['status'] == 'processing'])
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
