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
AGNES_API_KEY = (ENV.get("AGNES_API_KEY") or "").strip()
FAL_KEY = (ENV.get("FAL_KEY") or "").strip()

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
        "providers": [
            "agnes-video-2.5-flash",
            "agnes-video-2.5",
            "LTX",
            "fal-ai/wan/v2.7/text-to-video"
        ],
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




def generate_agnes(data):
    """Generate a video with Agnes 2.5 and save it locally."""
    import json

    if not AGNES_API_KEY:
        raise RuntimeError("کلید AGNES_API_KEY در فایل .env پیدا نشد.")

    engine = str(data.get("engine", "auto")).lower()
    model = (
        "agnes-video-2.5"
        if engine == "quality"
        else "agnes-video-2.5-flash"
    )

    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        raise RuntimeError("متن ویدیو خالی است.")

    try:
        seconds = int(data.get("duration", 5))
    except (TypeError, ValueError):
        seconds = 5
    seconds = max(4, min(12, seconds))

    ratio = str(data.get("ratio", "16:9"))
    allowed_ratios = ("16:9", "9:16", "1:1", "4:3", "3:4")
    if ratio not in allowed_ratios:
        ratio = "16:9"

    payload = {
        "model": model,
        "prompt": prompt,
        "mode": "text",
        "seconds": str(seconds),
        "size": "720P",
        "aspect_ratio": ratio,
        "n": 1
    }

    headers = {
        "Authorization": "Bearer " + AGNES_API_KEY,
        "Content-Type": "application/json"
    }

    print("AGNES: submitting", model, flush=True)

    response = requests.post(
        "https://apihub.agnes-ai.com/v1/videos",
        headers=headers,
        json=payload,
        timeout=60
    )

    if response.status_code not in (200, 201, 202):
        raise RuntimeError(
            "Agnes create error HTTP "
            + str(response.status_code)
            + ": "
            + response.text[:500]
        )

    created = response.json()
    video_id = created.get("video_id")

    if not video_id:
        raise RuntimeError(
            "Agnes video_id دریافت نشد: " + str(created)[:500]
        )

    print("AGNES VIDEO ID:", video_id, flush=True)

    result = None

    for attempt in range(120):
        time.sleep(5)

        check = requests.get(
            "https://apihub.agnes-ai.com/agnesapi",
            headers=headers,
            params={
                "video_id": video_id,
                "model_name": model
            },
            timeout=45
        )

        if check.status_code != 200:
            print(
                "AGNES POLL HTTP:",
                check.status_code,
                flush=True
            )
            continue

        status_data = check.json()
        status = str(status_data.get("status", "")).lower()

        print(
            "AGNES STATUS:",
            status,
            status_data.get("progress", ""),
            flush=True
        )

        if status in ("completed", "succeeded", "success", "done"):
            result = status_data
            break

        if status in ("failed", "error", "cancelled"):
            raise RuntimeError(
                "Agnes generation failed: "
                + str(status_data.get("error") or status_data)[:500]
            )

    if not result:
        raise RuntimeError("زمان انتظار برای ساخت ویدیوی Agnes تمام شد.")

    remote_url = result.get("url")
    if not remote_url:
        raise RuntimeError("آدرس ویدیوی نهایی Agnes دریافت نشد.")

    download = requests.get(
        remote_url,
        stream=True,
        timeout=(30, 300)
    )

    if download.status_code != 200:
        download.close()
        raise RuntimeError(
            "دریافت فایل Agnes ناموفق بود: HTTP "
            + str(download.status_code)
        )

    filename = "agnes_" + str(int(time.time())) + ".mp4"
    filepath = VIDEO_DIR / filename

    try:
        with open(filepath, "wb") as f:
            for chunk in download.iter_content(256 * 1024):
                if chunk:
                    f.write(chunk)
    finally:
        download.close()

    size = filepath.stat().st_size

    if size < 1000:
        filepath.unlink(missing_ok=True)
        raise RuntimeError("فایل ویدیوی Agnes معتبر نیست.")

    print("AGNES VIDEO SAVED:", filename, size, flush=True)

    return jsonify({
        "success": True,
        "message": "ویدیو با موفقیت ساخته شد!",
        "filename": filename,
        "video_url": "/videos/" + filename,
        "size_bytes": size,
        "model": model,
        "provider": "Agnes AI"
    })


@app.route("/api/generate-real", methods=["POST"])


def generate_fal(data):
    """Generate a video using fal.ai WAN 2.7 queue API."""
    from urllib.parse import urlparse

    if not FAL_KEY:
        return jsonify({
            "success": False,
            "provider": "fal.ai",
            "message": "کلید FAL_KEY در فایل .env پیدا نشد."
        }), 500

    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({
            "success": False,
            "message": "متن ویدیو خالی است."
        }), 400

    if len(prompt) > 5000:
        return jsonify({
            "success": False,
            "message": "متن ویدیو نباید بیشتر از ۵۰۰۰ حرف باشد."
        }), 400

    try:
        duration = int(data.get("duration", 5))
    except (TypeError, ValueError):
        duration = 5
    duration = max(2, min(15, duration))

    ratio = str(data.get("ratio", "16:9"))
    allowed_ratios = ("16:9", "9:16", "1:1", "4:3", "3:4")
    if ratio not in allowed_ratios:
        ratio = "16:9"

    model = "fal-ai/wan/v2.7/text-to-video"
    queue_url = "https://queue.fal.run/" + model

    headers = {
        "Authorization": "Key " + FAL_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "prompt": prompt,
        "aspect_ratio": ratio,
        "resolution": "720p",
        "duration": duration,
        "enable_prompt_expansion": True,
        "enable_safety_checker": True
    }

    print("FAL: submitting WAN 2.7 request", flush=True)

    try:
        submitted = requests.post(
            queue_url,
            headers=headers,
            json=payload,
            timeout=60
        )
    except requests.Timeout:
        return jsonify({
            "success": False,
            "provider": "fal.ai",
            "message": "پاسخ ثبت درخواست دریافت نشد. ممکن است درخواست ثبت شده باشد؛ برای جلوگیری از هزینه تکراری دوباره ارسال نکن."
        }), 504
    except requests.RequestException as e:
        return jsonify({
            "success": False,
            "provider": "fal.ai",
            "message": "ارتباط با fal.ai برقرار نشد.",
            "details": str(e)[:250]
        }), 502

    if submitted.status_code not in (200, 201, 202):
        print("FAL SUBMIT HTTP:", submitted.status_code, flush=True)
        return jsonify({
            "success": False,
            "provider": "fal.ai",
            "http_status": submitted.status_code,
            "message": (
                "اعتبار حساب fal.ai کافی نیست یا درخواست پذیرفته نشد."
                if submitted.status_code == 403
                else "fal.ai درخواست ساخت ویدیو را نپذیرفت."
            ),
            "details": submitted.text[:400]
        }), 502

    try:
        job = submitted.json()
    except ValueError:
        return jsonify({
            "success": False,
            "message": "پاسخ صف fal.ai قابل خواندن نیست."
        }), 502

    request_id = job.get("request_id")
    status_url = job.get("status_url")
    response_url = job.get("response_url")

    def valid_queue_url(url):
        if not isinstance(url, str):
            return False
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and parsed.netloc == "queue.fal.run"
        )

    if not request_id or not valid_queue_url(status_url) or not valid_queue_url(response_url):
        return jsonify({
            "success": False,
            "message": "اطلاعات صف fal.ai ناقص یا نامعتبر است.",
            "request_id": request_id
        }), 502

    print("FAL REQUEST ID:", request_id, flush=True)

    completed = False

    for attempt in range(180):
        time.sleep(5)

        try:
            check = requests.get(
                status_url,
                headers={"Authorization": "Key " + FAL_KEY},
                timeout=30
            )
        except requests.RequestException:
            return jsonify({
                "success": False,
                "provider": "fal.ai",
                "request_id": request_id,
                "message": "بررسی وضعیت صف قطع شد. درخواست دوباره ارسال نشده؛ شناسه را نگه دار."
            }), 504

        if check.status_code != 200:
            return jsonify({
                "success": False,
                "request_id": request_id,
                "message": "بررسی وضعیت درخواست fal.ai ناموفق بود.",
                "http_status": check.status_code
            }), 502

        try:
            status_data = check.json()
        except ValueError:
            continue

        status = str(status_data.get("status", "")).upper()
        print("FAL STATUS:", status, flush=True)

        if status == "COMPLETED":
            completed = True
            break

        if status in ("FAILED", "CANCELLED"):
            return jsonify({
                "success": False,
                "provider": "fal.ai",
                "request_id": request_id,
                "message": "ساخت ویدیو در fal.ai ناموفق شد.",
                "details": str(status_data.get("error") or status_data)[:400]
            }), 502

    if not completed:
        return jsonify({
            "success": False,
            "provider": "fal.ai",
            "request_id": request_id,
            "message": "زمان انتظار تمام شد. درخواست دوباره ارسال نشده؛ ممکن است هنوز در صف باشد."
        }), 504

    try:
        result_response = requests.get(
            response_url,
            headers={"Authorization": "Key " + FAL_KEY},
            timeout=60
        )
        result_response.raise_for_status()
        result = result_response.json()
    except (requests.RequestException, ValueError) as e:
        return jsonify({
            "success": False,
            "request_id": request_id,
            "message": "دریافت نتیجه نهایی fal.ai ناموفق بود.",
            "details": str(e)[:250]
        }), 502

    video = result.get("video") or {}
    remote_url = video.get("url")

    if not isinstance(remote_url, str) or urlparse(remote_url).scheme != "https":
        return jsonify({
            "success": False,
            "request_id": request_id,
            "message": "آدرس ویدیوی نهایی معتبر نیست."
        }), 502

    filename = "fal_wan27_" + str(int(time.time())) + ".mp4"
    filepath = VIDEO_DIR / filename

    try:
        download = requests.get(
            remote_url,
            stream=True,
            timeout=(30, 300)
        )
        if download.status_code != 200:
            download.close()
            return jsonify({
                "success": False,
                "message": "ویدیو ساخته شد اما دانلود آن ناموفق بود."
            }), 502

        with open(filepath, "wb") as f:
            for chunk in download.iter_content(256 * 1024):
                if chunk:
                    f.write(chunk)
        download.close()

        size = filepath.stat().st_size

        if size < 1000:
            filepath.unlink(missing_ok=True)
            return jsonify({
                "success": False,
                "message": "فایل ویدیویی دریافتی معتبر نیست."
            }), 502

    except Exception as e:
        filepath.unlink(missing_ok=True)
        return jsonify({
            "success": False,
            "message": "ذخیره ویدیوی fal.ai ناموفق بود.",
            "details": str(e)[:250]
        }), 500

    print("FAL VIDEO SAVED:", filename, size, flush=True)

    return jsonify({
        "success": True,
        "message": "ویدیو با موفقیت ساخته شد!",
        "filename": filename,
        "video_url": "/videos/" + filename,
        "size_bytes": size,
        "model": model,
        "provider": "fal.ai - WAN 2.7",
        "request_id": request_id
    })



def generate_real():
    import json
    from urllib.parse import urljoin, quote

    data = request.get_json(silent=True) or {}
    retry_count = int(request.environ.get("yaser_ltx_retry", 0))
    prompt = str(data.get("prompt") or "").strip()

    if not prompt:
        return jsonify({"success": False, "message": "متن ویدیو را وارد کن"}), 400

    selected_engine = str(data.get("engine", "auto")).lower()

    if selected_engine == "fal":
        return generate_fal(data)

    try:
        return generate_agnes(data)
    except Exception as agnes_error:
        error_text = str(agnes_error)
        print("AGNES ERROR:", error_text, flush=True)

        if "video_queue_full" in error_text or "HTTP 503" in error_text:
            return jsonify({
                "success": False,
                "provider": "Agnes AI",
                "error_code": "video_queue_full",
                "message": "صف ساخت ویدیوی Agnes فعلاً پُر است. لطفاً کمی بعد دوباره تلاش کنید.",
                "retry": True
            }), 503

        print("AGNES FAILED; FALLING BACK TO LTX:", error_text, flush=True)

    base_url = "https://lightricks-ltx-video-distilled.hf.space"
    api_name = "text_to_video"
    auth_headers = {"Authorization": f"Bearer {HF_TOKEN}"} if HF_TOKEN else {}

    ratio = str(data.get("ratio", "16:9"))
    sizes = {
        "16:9": (704, 512),
        "9:16": (512, 704),
        "1:1": (512, 512),
        "4:3": (640, 512),
        "3:4": (512, 640)
    }
    width, height = sizes.get(ratio, (704, 512))

    # تنظیم ثابت برای آزمایش مطابق درخواست موفق مستقیم LTX
    duration = 2.0

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
            headers={**auth_headers, "Content-Type": "application/json"},
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
        sse_error = False
        stream = requests.get(
            base_url + "/gradio_api/call/" + api_name + "/" + event_id,
            headers={**auth_headers, "Accept": "text/event-stream"},
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

            print("LTX SSE LINE:", repr(line), flush=True)

            if line.startswith("data:"):
                raw = line[5:].strip()
                debug_events.append(raw[:2000])

                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                print("LTX EVENT:", repr(event)[:3000], flush=True)

                if event is None:
                    continue

                if isinstance(event, list):
                    if event and isinstance(event[0], dict) and "msg" in event[0]:
                        event = event[0]
                    else:
                        result_data = event
                        break

                if isinstance(event, dict):
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

            elif line.startswith("event:"):
                print("LTX SSE EVENT NAME:", line, flush=True)
                if line.strip().lower() == "event: error":
                    sse_error = True

        stream.close()

        if sse_error or not result_data or not isinstance(result_data, list):
            if retry_count < 2:
                request.environ["yaser_ltx_retry"] = retry_count + 1
                wait_seconds = 4 * (retry_count + 1)
                print(
                    f"LTX retry {retry_count + 1}/2 after {wait_seconds}s",
                    flush=True
                )
                time.sleep(wait_seconds)
                return generate_real()

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
            headers=auth_headers,
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
