import json
from typing import Optional, List, Dict, Any
import requests

from .config import AIConfig, load_config, normalize_base_url
from .models import ChatMessage, AIRequest, AIResponse
from .prompts import default_prompt_manager, get_system_prompt


class CustomAIClient:
    """Client untuk memanggil custom AI API endpoint dengan validasi dan keamanan data."""

    def __init__(self, config: Optional[AIConfig] = None):
        self.config = config or load_config()
        self.session = requests.Session()
        self.prompt_manager = default_prompt_manager

    def _build_url(self, endpoint_path: str) -> str:
        base = normalize_base_url(self.config.base_url)
        path = endpoint_path if endpoint_path.startswith("/") else f"/{endpoint_path}"
        if base.endswith("/v1") and path.startswith("/v1/"):
            path = path[3:]
        return f"{base}{path}"

    def _get_headers(self, custom_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # Hanya kirim Authorization jika ada API key valid (server lokal seperti LM Studio tidak wajib)
        if self.config.api_key and self.config.api_key != "your_sumopod_api_key_here":
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        if custom_headers:
            headers.update(custom_headers)
        return headers

    def get_models_info(self) -> List[Dict[str, Any]]:
        """Ambil informasi lengkap semua model yang tersedia dari endpoint /models."""
        if not self.config.base_url:
            raise ValueError("Base URL belum ditentukan di file .env")

        target_url = self._build_url("/models")
        headers = self._get_headers()

        try:
            res = self.session.get(target_url, headers=headers, timeout=self.config.timeout_seconds)
            res.raise_for_status()
            data = res.json()
            if "data" in data and isinstance(data["data"], list):
                return data["data"]
            return []
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Gagal terhubung ke server AI ({target_url}). Pastikan server/LM Studio sudah dijalankan."
            )
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Gagal menghubungi server AI: {type(e).__name__}")
        except Exception:
            raise RuntimeError("Gagal memproses daftar model dari server.")

    def list_models(self) -> List[str]:
        """Ambil daftar nama ID model saja."""
        models = self.get_models_info()
        return [m.get("id", "") for m in models if "id" in m]

    def chat(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        user_message: Optional[str] = None,
        system_prompt: Optional[str] = None,
        prompt_template: Optional[str] = None,
        prompt_vars: Optional[Dict[str, Any]] = None,
        endpoint_path: str = "/chat/completions",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> AIResponse:
        """
        Kirim request chat ke custom API endpoint.
        
        Mendukung custom system prompt langsung via:
        - prompt_template: nama template dari folder prompts/ (cth: 'coder', 'json_extractor')
        - system_prompt: teks system prompt kustom langsung
        - user_message: teks pertanyaan user langsung (shorthand tanpa menyusun list messages)
        """
        if not self.config.base_url:
            raise ValueError(
                "Base URL belum ditentukan. Atur AI_API_BASE_URL di file .env"
            )

        final_messages: List[Dict[str, str]] = []

        # Tentukan system prompt jika diminta
        effective_sys_prompt = None
        if prompt_template:
            effective_sys_prompt = self.prompt_manager.get_prompt(
                prompt_template, **(prompt_vars or {})
            )
        elif system_prompt:
            effective_sys_prompt = system_prompt

        if effective_sys_prompt:
            final_messages.append({"role": "system", "content": effective_sys_prompt})

        # Gabungkan messages atau user_message
        if messages:
            for m in messages:
                # Jika sudah ada system message di messages dan kita juga tentukan system_prompt di atas, hindari duplikasi
                if m.get("role") == "system" and effective_sys_prompt:
                    continue
                final_messages.append(m)
        elif user_message:
            final_messages.append({"role": "user", "content": user_message})
        else:
            raise ValueError("Harap sediakan 'messages' atau 'user_message'.")

        selected_model = (model or self.config.model or "").strip()
        if not selected_model:
            try:
                available = self.list_models()
                if available:
                    selected_model = available[0]
            except Exception:
                pass

        # Validasi struktur input menggunakan Pydantic
        chat_messages = [ChatMessage(**m) for m in final_messages]
        validated_request = AIRequest(
            messages=chat_messages,
            model=selected_model or None,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )

        target_url = self._build_url(endpoint_path)
        headers = self._get_headers(extra_headers)

        payload: Dict[str, Any] = {
            "messages": [m.model_dump(exclude_none=True) for m in validated_request.messages],
            "temperature": validated_request.temperature,
        }
        if validated_request.model:
            payload["model"] = validated_request.model
        if validated_request.max_tokens is not None:
            payload["max_tokens"] = validated_request.max_tokens
        if validated_request.tools:
            payload["tools"] = validated_request.tools
            if validated_request.tool_choice is not None:
                payload["tool_choice"] = validated_request.tool_choice

        try:
            response = self.session.post(
                url=target_url,
                headers=headers,
                data=json.dumps(payload),
                timeout=self.config.timeout_seconds,
            )
        except requests.exceptions.Timeout:
            raise RuntimeError(f"Request ke {target_url} melebihi batas waktu (timeout).")
        except requests.exceptions.ConnectionError:
            raise RuntimeError(
                f"Gagal terhubung ke {target_url}. Pastikan server/LM Studio aktif dan port sesuai."
            )
        except Exception as e:
            # Masking detail sensitif agar tidak bocor
            raise RuntimeError(f"Gagal melakukan request API: {type(e).__name__}")

        if not response.ok:
            # Jangan tampilkan header response yang mungkin memuat token atau jejak sensitif
            error_msg = f"API ({target_url}) merespons status {response.status_code}"
            try:
                err_data = response.json()
                if isinstance(err_data, dict) and "error" in err_data:
                    error_msg += f": {err_data['error']}"
                elif response.text:
                    error_msg += f": {response.text[:200]}"
            except Exception:
                if response.text:
                    error_msg += f": {response.text[:200]}"
            raise RuntimeError(error_msg)

        data = response.json()

        # Ekstraksi respons standar (OpenAI style atau format umum)
        content = ""
        tool_calls = None
        prompt_tokens = None
        completion_tokens = None

        if "choices" in data and len(data["choices"]) > 0:
            choice = data["choices"][0]
            if "message" in choice:
                msg = choice["message"]
                content = msg.get("content") or ""
                tool_calls = msg.get("tool_calls") or None
                if not content and not tool_calls and msg.get("reasoning_content"):
                    content = msg["reasoning_content"]
            elif "text" in choice:
                content = choice["text"]
        elif "response" in data:
            content = data["response"]
        elif "output" in data:
            content = str(data["output"])
        else:
            content = json.dumps(data)

        if "usage" in data:
            prompt_tokens = data["usage"].get("prompt_tokens")
            completion_tokens = data["usage"].get("completion_tokens")

        return AIResponse(
            content=content,
            tool_calls=tool_calls,
            model=data.get("model", validated_request.model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def raw_post(
        self,
        endpoint_path: str,
        payload: Dict[str, Any],
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Kirim custom payload mentah jika API menggunakan schema non-standar."""
        if not self.config.base_url:
            raise ValueError("Base URL belum ditentukan di file .env")

        target_url = self._build_url(endpoint_path)
        headers = self._get_headers(extra_headers)

        try:
            res = self.session.post(
                url=target_url,
                headers=headers,
                json=payload,
                timeout=self.config.timeout_seconds,
            )
            res.raise_for_status()
            return res.json()
        except Exception as e:
            raise RuntimeError(f"Gagal memanggil custom endpoint: {type(e).__name__}")
