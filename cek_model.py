import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from ai_engine import CustomAIClient, load_config


def main():
    config = load_config()

    if not config.base_url or (
        not config.is_local
        and (not config.api_key or config.api_key == "your_sumopod_api_key_here")
    ):
        print("[PERINGATAN] File .env belum dikonfigurasi.")
        print("Pastikan Anda sudah menyalin .env.example ke .env dan mengisi AI_API_KEY.")
        sys.exit(1)

    client = CustomAIClient(config)
    print(f"Menghubungi endpoint: {config.base_url}/models ...")

    try:
        models_data = client.get_models_info()
        if not models_data:
            print("Tidak ada model yang ditemukan atau akun belum memiliki model aktif.")
            return

        print(f"\n[DAFTAR MODEL TERSEDIA ({len(models_data)} model)]")
        print("-" * 60)
        for i, item in enumerate(models_data, start=1):
            model_id = item.get("id", "Unknown")
            owned_by = item.get("owned_by", "")
            owner_info = f" (owned by: {owned_by})" if owned_by else ""
            active_marker = " [AKTIF DI .ENV]" if model_id == config.model else ""
            print(f"{i:2d}. {model_id}{owner_info}{active_marker}")
        print("-" * 60)
        print(f"Model default saat ini: {config.model}")
        print("Untuk mengganti model, ubah baris AI_API_MODEL di file .env Anda.")
    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()
