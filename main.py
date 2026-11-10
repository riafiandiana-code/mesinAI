import sys
from typing import List, Dict, Any, Optional

# Pastikan konsol Windows menggunakan UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich import box

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.styles import Style

from ai_engine import (
    CustomAIClient,
    load_config,
    list_available_prompts,
    get_system_prompt,
)

console = Console()

COMMANDS = {
    "/help": "Bantuan & daftar semua perintah",
    "/prompt": "Ganti template system prompt (mis: /prompt coder)",
    "/system": "Lihat teks system prompt yang sedang aktif",
    "/models": "Lihat daftar model yang tersedia di API",
    "/model": "Ganti model aktif (mis: /model glm-5.3-flash)",
    "/history": "Lihat statistik riwayat percakapan",
    "/clear": "Bersihkan riwayat percakapan (reset konteks)",
    "/exit": "Keluar dari sesi chat",
}


class SlashCommandCompleter(Completer):
    """
    Menampilkan menu saran hanya ketika pengguna mengetik '/' di awal baris.
    Jika tidak mengetik '/', menu tidak akan muncul sama sekali.
    Mendukung deteksi template baru secara otomatis (live reload).
    """

    def __init__(self, commands: Dict[str, str]):
        self.commands = commands

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Hanya munculkan saran jika diawali '/'
        if not text.startswith("/"):
            return

        # Jika mengetik '/prompt ', muat ulang daftar template langsung dari folder prompts/
        if text.startswith("/prompt "):
            current_templates = list_available_prompts()
            sub = text[8:].strip().lower()
            for t in current_templates:
                if t.lower().startswith(sub):
                    yield Completion(
                        t,
                        start_position=-len(text[8:]),
                        display=t,
                        display_meta="Template Prompt",
                    )
            return

        # Tampilkan daftar slash command yang cocok
        for cmd, desc in self.commands.items():
            if cmd.lower().startswith(text.lower()):
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display=cmd,
                    display_meta=desc,
                )


# Gaya minimalis untuk popup menu prompt_toolkit
pt_style = Style.from_dict({
    "completion-menu": "bg:#2b2b2b #ffffff",
    "completion-menu.completion": "bg:#2b2b2b #d0d0d0",
    "completion-menu.completion.current": "bg:#3c3c3c #00d7d7 bold",
    "completion-menu.meta": "bg:#2b2b2b #888888",
    "completion-menu.meta.current": "bg:#3c3c3c #aaaaaa",
})


def print_banner(config, active_prompt_name: str, available_prompts: List[str]):
    """Menampilkan banner status awal yang rapi dan minimalis."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold white", justify="left")
    table.add_column(style="dim", justify="left")

    table.add_row("Base URL", config.base_url)
    table.add_row("Model", config.model)
    table.add_row("System Prompt", f"{active_prompt_name} (tersedia: {', '.join(available_prompts)})")
    table.add_row("Perintah Cepat", "Ketik '/' untuk melihat menu perintah kapan saja")

    panel = Panel(
        table,
        title="[bold]MESIN AI - TERMINAL[/bold]",
        subtitle="[dim]Ketik '/' untuk bantuan • /exit untuk keluar[/dim]",
        border_style="bright_black",
        box=box.SQUARE,
        expand=False,
    )
    console.print(panel)
    console.print()


def show_help():
    """Tampilkan tabel bantuan minimalis."""
    table = Table(
        title="Daftar Perintah Slash (/)",
        box=box.SQUARE,
        border_style="bright_black",
        header_style="bold white",
        expand=False,
    )
    table.add_column("Perintah", style="bold cyan")
    table.add_column("Keterangan", style="dim white")

    for cmd, desc in COMMANDS.items():
        table.add_row(cmd, desc)

    console.print(table)
    console.print()


def main():
    config = load_config()

    if not config.base_url or (
        not config.is_local
        and (not config.api_key or config.api_key == "your_sumopod_api_key_here")
    ):
        console.print(
            Panel(
                "[red]File .env belum dikonfigurasi.[/red]\nPastikan AI_API_BASE_URL dan AI_API_KEY telah diisi.",
                title="Konfigurasi Hilang",
                box=box.SQUARE,
                border_style="red",
            )
        )
        sys.exit(1)

    client = CustomAIClient(config)
    available_prompts = list_available_prompts()
    active_prompt_name = "default" if "default" in available_prompts else available_prompts[0]
    active_system_prompt = get_system_prompt(active_prompt_name)
    active_model = config.model

    print_banner(config, active_prompt_name, available_prompts)

    conversation_history: List[Dict[str, str]] = [
        {"role": "system", "content": active_system_prompt}
    ]

    completer = SlashCommandCompleter(COMMANDS)
    session = PromptSession(completer=completer, style=pt_style, complete_while_typing=True)

    while True:
        try:
            user_input = session.prompt("Anda > ").strip()
        except KeyboardInterrupt:
            continue
        except EOFError:
            console.print("\n[dim]Sesi diakhiri.[/dim]")
            break

        if not user_input:
            continue

        # Penanganan Slash Commands
        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd in ("/exit", "/quit"):
                console.print("[dim]Sampai jumpa![/dim]")
                break

            elif cmd == "/help":
                show_help()
                continue

            elif cmd == "/clear":
                conversation_history = [{"role": "system", "content": active_system_prompt}]
                console.print("[dim]Riwayat percakapan telah dibersihkan (konteks baru).[/dim]\n")
                continue

            elif cmd == "/system":
                active_system_prompt = get_system_prompt(active_prompt_name)
                console.print(
                    Panel(
                        active_system_prompt,
                        title=f"System Prompt Aktif: [bold]{active_prompt_name}[/bold]",
                        box=box.SQUARE,
                        border_style="bright_black",
                    )
                )
                console.print()
                continue

            elif cmd == "/history":
                user_count = sum(1 for m in conversation_history if m["role"] == "user")
                ai_count = sum(1 for m in conversation_history if m["role"] == "assistant")
                console.print(
                    f"[dim]Konteks saat ini: {user_count} pesan Anda, {ai_count} respons AI.[/dim]\n"
                )
                continue

            elif cmd == "/models":
                console.print("[dim]Mengambil daftar model dari server...[/dim]")
                try:
                    models = client.list_models()
                    table = Table(
                        title="Model Tersedia di Akun",
                        box=box.SQUARE,
                        border_style="bright_black",
                    )
                    table.add_column("No", justify="right", style="dim")
                    table.add_column("Model ID", style="bold white")
                    table.add_column("Status", style="cyan")

                    for i, m in enumerate(models, start=1):
                        status = "AKTIF" if m == active_model else ""
                        table.add_row(str(i), m, status)
                    console.print(table)
                except Exception as e:
                    console.print(f"[red]Gagal memuat model:[/red] {e}")
                console.print()
                continue

            elif cmd == "/model":
                if not arg:
                    console.print(f"[dim]Model saat ini:[/dim] [bold]{active_model}[/bold]")
                    console.print("Gunakan format: [cyan]/model <nama-model>[/cyan]\n")
                else:
                    active_model = arg
                    console.print(f"[green]Model berhasil diubah ke:[/green] [bold]{active_model}[/bold]\n")
                continue

            elif cmd == "/prompt":
                current_prompts = list_available_prompts()
                if not arg:
                    console.print(f"[dim]Prompt saat ini: [bold]{active_prompt_name}[/bold][/dim]")
                    console.print(f"[dim]Tersedia: {', '.join(current_prompts)}[/dim]")
                    console.print("Gunakan format: [cyan]/prompt <nama_template>[/cyan]\n")
                elif arg in current_prompts:
                    active_prompt_name = arg
                    active_system_prompt = get_system_prompt(active_prompt_name)
                    # Perbarui pesan system di awal riwayat
                    conversation_history = [m for m in conversation_history if m["role"] != "system"]
                    conversation_history.insert(0, {"role": "system", "content": active_system_prompt})
                    console.print(f"[green]System prompt diubah ke template:[/green] [bold]{active_prompt_name}[/bold]\n")
                else:
                    console.print(f"[red]Template '{arg}' tidak ditemukan.[/red] Tersedia: {', '.join(current_prompts)}\n")
                continue

            else:
                console.print(f"[yellow]Perintah '{cmd}' tidak dikenali.[/yellow] Ketik [cyan]/help[/cyan] untuk bantuan.\n")
                continue

        # Sinkronkan perubahan file prompt secara live sebelum mengirim
        active_system_prompt = get_system_prompt(active_prompt_name)
        if conversation_history and conversation_history[0]["role"] == "system":
            conversation_history[0]["content"] = active_system_prompt

        # Alur pesan obrolan biasa (tanpa awalan '/')
        conversation_history.append({"role": "user", "content": user_input})

        console.print("[dim]AI sedang merespons...[/dim]", end="\r")

        try:
            response = client.chat(messages=conversation_history, model=active_model)
            ai_reply = response.content

            # Hapus teks tunggu
            console.print(" " * 35, end="\r")

            # Render panel respons minimalis kotak lurus
            md = Markdown(ai_reply)
            panel = Panel(
                md,
                title=f"[bold white]{active_model}[/bold white]",
                border_style="bright_black",
                box=box.SQUARE,
            )
            console.print(panel)
            console.print()

            conversation_history.append({"role": "assistant", "content": ai_reply})

        except Exception as e:
            console.print(" " * 35, end="\r")
            console.print(f"[red]Gagal mendapatkan respons:[/red] {e}\n")
            conversation_history.pop()


if __name__ == "__main__":
    main()
