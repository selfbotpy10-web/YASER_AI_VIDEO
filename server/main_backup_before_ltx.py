from flask import Flask, jsonify, send_from_directory, request
from pathlib import Path
from dotenv import dotenv_values
import requests
import time

app = Flask(__name__)

BASE = Path(__file__).resolve().parent.parent
WEB = BASE / "web"
VIDEO_DIR = BASE / "videos"

VIDEO_DIR.mkdir(exist_ok=True)

ENV = dotenv_values(BASE / ".env")
HF_TOKEN = (ENV.get("HF_TOKEN") or "").strip()

MODEL = "Wan-AI/Wan2.2-TI2V-5B"
PROVIDER = "fal-ai"


@app.route("/")
def home():
    return send_from_directory(WEB, "index.html")


@app.route("/api/health")
def health():
    return jsonify({
        "app": "YASER AI VIDEO",
        "status": "online",
        "version": "1.1.0"
    })


@app.route("/api/providers")
def providers():
    return jsonify({
        "automatic_selection": True,
        "providers": ["fal-ai", "wavespeed"],
        "model": MODEL
    })


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()

    if not prompt:
        return jsonify({
            "success": False,
            "message": "توضیحات ویدیو را وارد کن"
        }), 400

    return jsonify({
        "success": False,
        "message": "API اصلی تولید در /api/generate-real فعال است."
    })



@app.route("/api/generate-real", methods=["POST"])
def generate_real():
    import requests
    import time

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()

    if not prompt:
        return jsonify({"success": False, "message": "متن ویدیو را وارد کن"}), 400

    env = dotenv_values(BASE / ".env")
    api_key = (env.get("AGNES_API_KEY") or "").strip()

    if not api_key:
        return jsonify({"success": False, "message": "AGNES_API_KEY در فایل .env تنظیم نشده"}), 500

    model = "agnes-video-v2.0"
    api = "https://apihub.agnes-ai.com"

    headers = {
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json"
    }

    ratio = str(data.get("ratio", "16:9"))
    sizes = {
        "16:9": (1152, 768),
        "9:16": (768, 1152),
        "1:1": (1024, 1024),
        "4:3": (1024, 768),
        "3:4": (768, 1024)
    }

    width, height = sizes.get(ratio, (1152, 768))

    try:
        duration = int(data.get("duration", 5))
    except (ValueError, TypeError):
        duration = 5

    duration = max(4, min(duration, 12))
    frames = duration * 24 + 1

    payload = {
        "model": model,
        "prompt": prompt,
        "width": width,
        "height": height,
        "num_frames": frames,
        "frame_rate": 24
    }

    try:
        print("Agnes: creating video task")

        create = requests.post(
            api + "/v1/videos",
            headers=headers,
            json=payload,
            timeout=90
        )

        if create.status_code not in (200, 201, 202):
            print("Agnes create error:", create.status_code)
            return jsonify({
                "success": False,
                "message": "Agnes درخواست ساخت ویدیو را قبول نکرد.",
                "http_status": create.status_code,
                "details": create.text[:400]
            }), 502

        result = create.json()
        video_id = result.get("video_id") or result.get("id")

        if not video_id:
            return jsonify({
                "success": False,
                "message": "شناسه ویدیو در پاسخ موتور پیدا نشد.",
                "details": str(result)[:400]
            }), 502

        print("Agnes task created:", video_id)

        video_url = None
        last_status = ""

        for attempt in range(120):
            time.sleep(5)

            check = requests.get(
                api + "/agnesapi",
                headers={"Authorization": "Bearer " + api_key},
                params={
                    "video_id": video_id,
                    "model_name": model
                },
                timeout=60
            )

            if check.status_code != 200:
                print("Agnes poll:", check.status_code)
                continue

            status_data = check.json()
            last_status = str(status_data.get("status", "")).lower()

            print("Agnes status:", last_status, "poll:", attempt + 1)

            if last_status in ("completed", "success", "succeeded", "done"):
                video_url = (
                    status_data.get("url")
                    or status_data.get("video_url")
                )
                break

            if last_status in ("failed", "error", "cancelled"):
                return jsonify({
                    "success": False,
                    "message": "موتور Agnes نتوانست ویدیو را بسازد.",
                    "details": str(status_data.get("error", ""))[:400]
                }), 502

        if not video_url:
            return jsonify({
                "success": False,
                "message": "ساخت ویدیو طولانی شد یا نتیجه آماده نشد.",
                "status": last_status
            }), 504

        download = requests.get(video_url, timeout=180, stream=True)

        if download.status_code != 200:
            return jsonify({
                "success": False,
                "message": "ویدیو ساخته شد اما دریافت فایل ناموفق بود."
            }), 502

        filename = "agnes_" + str(int(time.time())) + ".mp4"
        filepath = VIDEO_DIR / filename

        with open(filepath, "wb") as f:
            for chunk in download.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)

        size = filepath.stat().st_size

        print("Agnes video saved:", filename, size)

        return jsonify({
            "success": True,
            "message": "ویدیو با موفقیت ساخته شد!",
            "filename": filename,
            "video_url": "/videos/" + filename,
            "size_bytes": size,
            "model": model,
            "provider": "Agnes"
        })

    except requests.Timeout:
        return jsonify({
            "success": False,
            "message": "ارتباط با Agnes زمان‌بر شد؛ درخواست Timeout شد."
        }), 504

    except Exception as e:
        print("Agnes ERROR:", str(e))
        return jsonify({
            "success": False,
            "message": "خطا هنگام ارتباط با موتور Agnes.",
            "details": str(e)[:300]
        }), 500


@app.route("/videos/<filename>")
def get_video(filename):
    return send_from_directory(VIDEO_DIR, filename)


@app.route("/api/videos")
def list_videos():
    files = sorted(
        VIDEO_DIR.glob("*.mp4"),
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )

    return jsonify([
        {
            "filename": f.name,
            "url": f"/videos/{f.name}",
            "size": f.stat().st_size
        }
        for f in files
    ])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
