import os
import requests
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("HF_TOKEN", "").strip()

if not token:
    print("ERROR: HF_TOKEN در فایل .env پیدا نشد")
    raise SystemExit(1)

r = requests.get(
    "https://huggingface.co/api/whoami-v2",
    headers={"Authorization": f"Bearer {token}"},
    timeout=30
)

print("HTTP:", r.status_code)

if r.status_code == 200:
    user = r.json()
    print("TOKEN OK")
    print("Username:", user.get("name"))
else:
    print("TOKEN ERROR")
    print(r.text[:300])
