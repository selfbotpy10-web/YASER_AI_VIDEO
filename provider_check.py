import requests

models = [
    "Wan-AI/Wan2.2-TI2V-5B",
    "Wan-AI/Wan2.1-T2V-1.3B",
    "Wan-AI/Wan2.1-T2V-14B",
    "tencent/HunyuanVideo",
    "genmo/mochi-1-preview",
    "Lightricks/LTX-Video"
]

for model in models:
    print("\n" + "=" * 40)
    print("MODEL:", model)

    url = f"https://huggingface.co/api/models/{model}"

    try:
        r = requests.get(
            url,
            params={"expand": "inferenceProviderMapping"},
            timeout=40
        )

        print("HTTP:", r.status_code)

        if r.status_code != 200:
            print(r.text[:200])
            continue

        data = r.json()
        providers = data.get("inferenceProviderMapping")

        if not providers:
            print("ارائه‌دهنده فعال پیدا نشد")
            continue

        for name, info in providers.items():
            print("Provider:", name)
            print("Status:", info.get("status"))
            print("Task:", info.get("task"))
            print("Provider model:", info.get("providerId"))

    except Exception as e:
        print("ERROR:", e)
