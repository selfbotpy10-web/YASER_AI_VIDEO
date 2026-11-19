import requests

url = "https://huggingface.co/api/models"

params = {
    "inference_provider": "all",
    "pipeline_tag": "text-to-video",
    "limit": 20
}

print("در حال پیدا کردن موتورهای ویدیویی...")

try:
    r = requests.get(url, params=params, timeout=60)
    print("HTTP:", r.status_code)

    if r.status_code != 200:
        print(r.text[:500])
        exit()

    models = r.json()

    for i, model in enumerate(models, 1):
        print(f"\n{i}. {model.get('id')}")

        mapping = model.get("inferenceProviderMapping", {})

        if mapping:
            for provider, info in mapping.items():
                print("   Provider:", provider)
                print("   Status:", info.get("status"))
        else:
            print("   Provider details unavailable")

except Exception as e:
    print("ERROR:", e)
