#!/usr/bin/env python3
"""
YouTube -> Google Drive Downloader
Flask server + yt-dlp (Python API) + n8n webhook (Google Drive upload)
"""
import os, json, tempfile, threading, uuid, shutil
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp
import urllib.request, urllib.error

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

N8N_WEBHOOK = "https://n8n-n8n.xktssy.easypanel.host/webhook/youtube-drive-upload"

# Track download jobs
jobs = {}

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/api/info", methods=["POST"])
def video_info():
    """Get video info without downloading."""
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400

    try:
        ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extractor_args": {"youtube": {"player_client": ["tv"]}}}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        return jsonify({
            "title": info.get("title", ""),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail", ""),
            "uploader": info.get("uploader", ""),
            "view_count": info.get("view_count", 0),
            "upload_date": info.get("upload_date", ""),
            "description": (info.get("description", "") or "")[:200],
            "filesize_approx": info.get("filesize_approx", 0),
        })
    except Exception as e:
        return jsonify({"error": str(e)[:500]}), 400

@app.route("/api/download", methods=["POST"])
def start_download():
    """Start download + upload job."""
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "downloading", "progress": 0, "message": "Iniciando download..."}

    thread = threading.Thread(target=_process_video, args=(job_id, url))
    thread.daemon = True
    thread.start()

    return jsonify({"job_id": job_id})

@app.route("/api/status/<job_id>")
def job_status(job_id):
    """Check job status."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)

def _progress_hook(job_id):
    """Create a yt-dlp progress hook for the given job."""
    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                pct = int((downloaded / total) * 40) + 10  # 10-50%
                size_mb = total / (1024 * 1024)
                jobs[job_id] = {
                    "status": "downloading",
                    "progress": pct,
                    "message": f"Baixando... {pct - 10}% ({size_mb:.0f} MB total)"
                }
        elif d["status"] == "finished":
            jobs[job_id] = {
                "status": "downloading",
                "progress": 48,
                "message": "Download concluido, processando..."
            }
    return hook

def _process_video(job_id, url):
    """Download video with yt-dlp, then upload to Google Drive via n8n."""
    tmp_dir = tempfile.mkdtemp()
    try:
        # Step 1: Download with yt-dlp
        jobs[job_id] = {"status": "downloading", "progress": 10, "message": "Baixando video do YouTube..."}

        output_template = os.path.join(tmp_dir, "%(title)s.%(ext)s")
        ydl_opts = {
            "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]",
            "merge_output_format": "mp4",
            "outtmpl": output_template,
            "noplaylist": True,
            "progress_hooks": [_progress_hook(job_id)],
            "quiet": True,
            "no_warnings": True,
            "extractor_args": {"youtube": {"player_client": ["tv"]}},
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Find the downloaded file
        files = [f for f in os.listdir(tmp_dir) if f.endswith((".mp4", ".webm", ".mkv"))]
        if not files:
            jobs[job_id] = {"status": "error", "message": "Nenhum arquivo encontrado apos download"}
            return

        filepath = os.path.join(tmp_dir, files[0])
        filename = files[0]
        filesize = os.path.getsize(filepath)
        filesize_mb = filesize / (1024 * 1024)

        jobs[job_id] = {
            "status": "uploading",
            "progress": 55,
            "message": f"Enviando para Google Drive ({filesize_mb:.1f} MB)..."
        }

        # Step 2: Upload to n8n webhook (multipart)
        drive_result = _upload_to_n8n(filepath, filename)

        if drive_result and drive_result.get("success"):
            jobs[job_id] = {
                "status": "done",
                "progress": 100,
                "message": "Upload concluido!",
                "driveLink": drive_result.get("driveLink", ""),
                "fileName": drive_result.get("fileName", filename),
                "fileSize": f"{filesize_mb:.1f} MB"
            }
        else:
            error_msg = drive_result.get("message", "Erro desconhecido") if drive_result else "Sem resposta do n8n"
            jobs[job_id] = {"status": "error", "message": f"Erro no upload: {error_msg}"}

    except Exception as e:
        jobs[job_id] = {"status": "error", "message": f"Erro: {str(e)[:300]}"}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

def _upload_to_n8n(filepath, filename):
    """Upload file to n8n webhook as multipart/form-data."""
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"

    body = b""

    # fileName field
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="fileName"\r\n\r\n'.encode()
    body += f"{filename}\r\n".encode()

    # videoTitle field
    title = os.path.splitext(filename)[0]
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="videoTitle"\r\n\r\n'.encode()
    body += f"{title}\r\n".encode()

    # Binary file
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="data"; filename="{filename}"\r\n'.encode()
    body += f"Content-Type: video/mp4\r\n\r\n".encode()

    with open(filepath, "rb") as f:
        body += f.read()

    body += f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        N8N_WEBHOOK,
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body))
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"n8n webhook error {e.code}: {error_body}")
        return {"success": False, "message": f"HTTP {e.code}: {error_body[:200]}"}
    except Exception as e:
        print(f"Upload error: {e}")
        return {"success": False, "message": str(e)}

if __name__ == "__main__":
    print("=" * 50)
    print("  YouTube -> Google Drive Downloader")
    print("  http://localhost:5555")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5555, debug=False)
