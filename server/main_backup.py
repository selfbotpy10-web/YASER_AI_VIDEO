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
    import json
    from urllib.parse import urljoin, quote

    data = request.get_json(silent=True) or {}
    prompt = str(data.get("prompt") or "").strip()

    if not prompt:
        return jsonify({"success": False, "message": "متن ویدیو را وارد کن"}), 400

    base_url = "https://lightricks-ltx-video-distilled.hf.space"
    api_name = "text_to_video"

    ratio = str(data.get("ratio", "16:9"))
    sizes = {
        "16:9": (704, 512),
        "9:16": (512, 704),
        "1:1": (512, 512),
        "4:3": (640, 512),
        "3:4": (512, 640)
    }
    width, height = sizes.get(ratio, (704, 512))

    try:
        duration = float(data.get("duration", 2))
    except (ValueError, TypeError):
        duration = 2.0
    duration = max(0.3, min(duration, 8.5))

    negative_prompt = (
        "worst quality, inconsistent motion, blurry, jittery, distorted"
    )

    # ترتیب ورودی‌ها دقیقاً مطابق مستندات رسمی Space
    inputs = [
        prompt,
        negative_prompt,
        None,
        None,
        height,
        width,
        "text-to-video",
        duration,
        9,
        42,
        True,
        1,
        True
    ]

    try:
        print("LTX: submitting video task")

        create = requests.post(
            base_url + "/gradio_api/call/" + api_name,
            json={"data": inputs},
            headers={"Content-Type": "application/json"},
            timeout=60
        )

        if create.status_code not in (200, 201, 202):
            print("LTX create error:", create.status_code, create.text[:500])
            return jsonify({
                "success": False,
                "message": "موتور LTX درخواست را قبول نکرد.",
                "http_status": create.status_code,
                "details": create.text[:400]
            }), 502

        created = create.json()
        event_id = created.get("event_id")

        if not event_id:
            return jsonify({
                "success": False,
                "message": "شناسه صف LTX دریافت نشد.",
                "details": str(created)[:400]
            }), 502

        print("LTX task queued:", event_id)

        result_data = None
        debug_events = []
        stream = requests.get(
            base_url + "/gradio_api/call/" + api_name + "/" + event_id,
            headers={"Accept": "text/event-stream"},
            stream=True,
            timeout=(30, 1200)
        )

        if stream.status_code != 200:
            return jsonify({
                "success": False,
                "message": "دریافت نتیجه از صف LTX ناموفق بود.",
                "http_status": stream.status_code
            }), 502

        for line in stream.iter_lines(decode_unicode=True):
            if not line:
                continue

            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")

            if not line.startswith("data:"):
                continue

            raw = line[5:].strip()
            debug_events.append(raw[:2000])
            print("LTX SSE RAW:", raw[:3000], flush=True)

            try:
                event = json.loads(raw)
                print("LTX EVENT TYPE:", type(event).__name__, flush=True)
            except json.JSONDecodeError:
                continue

            # پشتیبانی از پاسخ فهرستی و دیکشنری
            if isinstance(event, list):
                if event and isinstance(event[0], dict) and "msg" in event[0]:
                    event = event[0]
                else:
                    result_data = event
                    break

            if not isinstance(event, dict):
                continue

            message = event.get("msg", "")

            if message == "process_completed":
                if event.get("success") is False:
                    return jsonify({
                        "success": False,
                        "message": "موتور LTX در ساخت ویدیو خطا داد.",
                        "details": str(event.get("output", ""))[:400]
                    }), 502

                output = event.get("output") or {}

                if isinstance(output, list):
                    result_data = output
                elif isinstance(output, dict):
                    result_data = output.get("data")

                break

            if message == "close_stream":
                break

        stream.close()

        if not result_data or not isinstance(result_data, list):
            return jsonify({
                "success": False,
                "message": "صف LTX نتیجه ویدیویی برنگرداند.",
                "details": debug_events[-5:]
            }), 502

        video_info = result_data[0]

        # پیدا کردن فایل ویدیو در ساختار مستقیم یا تو در تو
        def find_video_file(value):
            if isinstance(value, dict):
                if value.get("url") or value.get("path"):
                    return value

                # خروجی LTX ممکن است داخل کلید video باشد
                for key in ("video", "file", "value"):
                    if key in value:
                        found = find_video_file(value[key])
                        if found:
                            return found

                for item in value.values():
                    found = find_video_file(item)
                    if found:
                        return found

            elif isinstance(value, list):
                for item in value:
                    found = find_video_file(item)
                    if found:
                        return found

            return None

        file_info = find_video_file(video_info)

        if not file_info:
            print("LTX VIDEO DATA:", repr(video_info)[:2000])
            return jsonify({
                "success": False,
                "message": "اطلاعات فایل ویدیو در پاسخ LTX پیدا نشد.",
                "details": str(video_info)[:1000]
            }), 502

        remote_url = file_info.get("url")
        remote_path = file_info.get("path")

        if remote_url:
            download_url = urljoin(base_url + "/", remote_url)
        elif remote_path:
            download_url = (
                base_url + "/gradio_api/file=" + quote(remote_path, safe="/")
            )
        else:
            return jsonify({
                "success": False,
                "message": "آدرس فایل ویدیوی ساخته‌شده پیدا نشد."
            }), 502

        print("LTX video ready; downloading")

        download = requests.get(
            download_url,
            stream=True,
            timeout=(30, 300)
        )

        if download.status_code != 200:
            return jsonify({
                "success": False,
                "message": "ویدیو ساخته شد اما دریافت فایل ناموفق بود.",
                "http_status": download.status_code
            }), 502

        filename = "ltx_" + str(int(time.time())) + ".mp4"
        filepath = VIDEO_DIR / filename

        with open(filepath, "wb") as f:
            for chunk in download.iter_content(chunk_size=256 * 1024):
                if chunk:
                    f.write(chunk)

        download.close()
        size = filepath.stat().st_size

        if size < 1000:
            filepath.unlink(missing_ok=True)
            return jsonify({
                "success": False,
                "message": "فایل دریافتی معتبر نیست یا خالی است."
            }), 502

        print("LTX video saved:", filename, size)

        return jsonify({
            "success": True,
            "message": "ویدیو با موفقیت ساخته شد!",
            "filename": filename,
            "video_url": "/videos/" + filename,
            "size_bytes": size,
            "model": "Lightricks/LTX-Video",
            "provider": "Hugging Face Space"
        })

    except requests.Timeout:
        return jsonify({
            "success": False,
            "message": "زمان انتظار موتور LTX تمام شد؛ ممکن است صف شلوغ باشد."
        }), 504

    except Exception as e:
        print("LTX ERROR:", str(e))
        return jsonify({
            "success": False,
            "message": "خطا هنگام ارتباط با موتور LTX.",
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
