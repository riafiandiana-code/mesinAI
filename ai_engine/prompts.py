from pathlib import Path
from typing import Dict, List, Optional
import string


class PromptManager:
    """Pengelola System Prompt berbasis template dan file (auto-reload)."""

    DEFAULT_FALLBACK = "Anda adalah asisten AI yang profesional, ramah, dan ringkas dalam bahasa Indonesia."

    def __init__(self, prompts_dir: Optional[Path] = None):
        if prompts_dir is None:
            self.prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
        else:
            self.prompts_dir = Path(prompts_dir)

        self._registered_prompts: Dict[str, str] = {
            "default": self.DEFAULT_FALLBACK,
        }
        self._prompts: Dict[str, str] = {}
        self.reload_from_disk()

    def reload_from_disk(self) -> None:
        """Muat ulang semua prompt dari folder prompts/ (*.txt, *.md)."""
        fresh_prompts: Dict[str, str] = dict(self._registered_prompts)

        if self.prompts_dir.is_dir():
            for file_path in self.prompts_dir.iterdir():
                if file_path.is_file() and file_path.suffix.lower() in (".txt", ".md"):
                    prompt_name = file_path.stem
                    try:
                        content = file_path.read_text(encoding="utf-8").strip()
                        if content:
                            fresh_prompts[prompt_name] = content
                    except Exception:
                        pass

        self._prompts = fresh_prompts

    def register_prompt(self, name: str, template: str) -> None:
        """Daftarkan atau timpa template prompt secara programatis."""
        cleaned_name = name.strip()
        cleaned_template = template.strip()
        if not cleaned_name:
            raise ValueError("Nama prompt tidak boleh kosong.")
        if not cleaned_template:
            raise ValueError("Konten template prompt tidak boleh kosong.")
        self._registered_prompts[cleaned_name] = cleaned_template
        self._prompts[cleaned_name] = cleaned_template

    def get_prompt(self, name: str = "default", **kwargs) -> str:
        """Ambil prompt berdasarkan nama (otomatis reload dari disk terlebih dahulu)."""
        self.reload_from_disk()

        template_str = self._prompts.get(name)
        if template_str is None:
            template_str = self._prompts.get("default", self.DEFAULT_FALLBACK)

        if not kwargs:
            return template_str

        try:
            template_obj = string.Template(template_str.replace("{", "${").replace("}", "}"))
            return template_obj.safe_substitute(kwargs)
        except Exception:
            return template_str

    def list_prompts(self) -> List[str]:
        """Daftar semua nama prompt yang tersedia (otomatis reload dari disk)."""
        self.reload_from_disk()
        return sorted(list(self._prompts.keys()))


# Instance singleton default
default_prompt_manager = PromptManager()


def get_system_prompt(name: str = "default", **kwargs) -> str:
    """Fungsi helper cepat untuk mengambil system prompt."""
    return default_prompt_manager.get_prompt(name, **kwargs)


def list_available_prompts() -> List[str]:
    """Fungsi helper cepat untuk melihat daftar nama system prompt."""
    return default_prompt_manager.list_prompts()
