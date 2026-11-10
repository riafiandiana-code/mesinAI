import sys
from typing import List, Dict, Any

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
    ToolManager,
    load_config,
    list_available_prompts,
    get_system_prompt,
)

console = Console()

COMMANDS = {
    "/help": "Bantuan & daftar semua perintah",
    "/prompt": "Ganti template system prompt (mis: /prompt coder)",
    "/system": "Lihat teks system prompt yang sedang aktif",
    "/tools": "Lihat daftar tools (Python & MCP) beserta statusnya",
    "/tool": "Pilih atau nyalakan/matikan tools yang dipakai agent",
    "/mcp": "Lihat status server MCP atau '/mcp reload' untuk muat ulang",
    "/models": "Lihat daftar model yang tersedia di API",
    "/model": "Ganti model aktif (mis: /model glm-5.3-flash)",
    "/history": "Lihat statistik riwayat percakapan",
    "/clear": "Bersihkan riwayat percakapan (reset konteks)",
    "/exit": "Keluar dari sesi chat",
}

MAX_TOOL_ITERATIONS = 8


class SlashCommandCompleter(Completer):
    """
    Menampilkan menu saran hanya ketika pengguna mengetik '/' di awal baris.
    Jika tidak mengetik '/', menu tidak akan muncul sama sekali.
    Mendukung deteksi template dan tools terbaru secara otomatis.
    """

    def __init__(self, commands: Dict[str, str], tool_manager: ToolManager):
        self.commands = commands
        self.tool_manager = tool_manager

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        if not text.startswith("/"):
            return

        # Autocomplete untuk /prompt <template>
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

        # Autocomplete untuk /tool <aksi> <nama_tool>
        if text.startswith("/tool "):
            rest = text[6:]
            for prefix in ("on ", "off ", "toggle "):
                if rest.lower().startswith(prefix):
                    query = rest[len(prefix):].lower()
                    for t in self.tool_manager.list_tools():
                        if t.name.lower().startswith(query):
                            status_txt = "AKTIF" if t.enabled else "NONAKTIF"
                            yield Completion(
                                t.name,
                                start_position=-len(rest[len(prefix):]),
                                display=t.name,
                                display_meta=f"[{status_txt}] {t.source}",
                            )
                    return

            for action in ("on ", "off ", "toggle ", "all on", "all off"):
                if action.startswith(rest.lower()):
                    yield Completion(
                        action,
                        start_position=-len(rest),
                        display=action.strip(),
                        display_meta="Aksi Tool",
                    )
            return

        # Autocomplete untuk /mcp reload
        if text.startswith("/mcp "):
            sub = text[5:].lower()
            if "reload".startswith(sub):
                yield Completion(
                    "reload",
                    start_position=-len(text[5:]),
                    display="reload",
                    display_meta="Muat ulang folder tools/ dan mcp_servers.json",
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


pt_style = Style.from_dict({
    "completion-menu": "bg:#2b2b2b #ffffff",
    "completion-menu.completion": "bg:#2b2b2b #d0d0d0",
    "completion-menu.completion.current": "bg:#3c3c3c #00d7d7 bold",
    "completion-menu.meta": "bg:#2b2b2b #888888",
    "completion-menu.meta.current": "bg:#3c3c3c #aaaaaa",
})


def print_banner(config, active_prompt_name: str, available_prompts: List[str], tool_manager: ToolManager):
    """Menampilkan banner status awal yang rapi dan minimalis."""
    all_tools = tool_manager.list_tools()
    active_tools = tool_manager.get_enabled_tools()

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold white", justify="left")
    table.add_column(style="dim", justify="left")

    table.add_row("Base URL", config.base_url)
    table.add_row("Model", config.model or "(auto-detect)")
    table.add_row("System Prompt", f"{active_prompt_name} (tersedia: {', '.join(available_prompts)})")
    table.add_row("Tools Aktif", f"{len(active_tools)} / {len(all_tools)} tools (ketik /tool untuk memilih)")
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


def show_tools_table(tool_manager: ToolManager):
    """Tampilkan daftar seluruh tools (Python & MCP) beserta statusnya."""
    tool_manager.reload_python_tools()
    tools = tool_manager.list_tools()

    if not tools:
        console.print("[dim]Belum ada tools yang terdeteksi di folder tools/ atau mcp_servers.json.[/dim]\n")
        return

    table = Table(
        title="Daftar Custom Tools & MCP",
        box=box.SQUARE,
        border_style="bright_black",
        header_style="bold white",
    )
    table.add_column("No", justify="right", style="dim")
    table.add_column("Nama Tool", style="bold white")
    table.add_column("Sumber", style="dim")
    table.add_column("Status", justify="center")
    table.add_column("Deskripsi", style="dim white")

    for idx, t in enumerate(tools, start=1):
        status = "[green]AKTIF[/green]" if t.enabled else "[red]NONAKTIF[/red]"
        desc = t.description.splitlines()[0][:65]
        table.add_row(str(idx), t.name, t.source, status, desc)

    console.print(table)
    console.print()


def interactive_tool_selector(tool_manager: ToolManager):
    """Menu interaktif agar user bisa memilih/toggle tools dengan nomor atau all/none."""
    show_tools_table(tool_manager)
    tools = tool_manager.list_tools()
    if not tools:
        return

    console.print(
        "[dim]Masukkan nomor tool dipisah koma untuk toggle (cth: 1,3), "
        "'all' untuk aktifkan semua, 'none' untuk matikan semua, atau Enter untuk selesai:[/dim]"
    )
    try:
        choice = input("Pilih tool > ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        console.print()
        return

    if not choice:
        console.print()
        return

    if choice == "all":
        tool_manager.set_all_enabled(True)
        console.print("[green]Semua tools diaktifkan.[/green]\n")
        return

    if choice == "none":
        tool_manager.set_all_enabled(False)
        console.print("[yellow]Semua tools dinonaktifkan.[/yellow]\n")
        return

    toggled = []
    for part in choice.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(tools):
                entry = tools[idx]
                new_state = tool_manager.toggle_tool(entry.name)
                label = "AKTIF" if new_state else "NONAKTIF"
                toggled.append(f"{entry.name} ({label})")

    if toggled:
        console.print(f"[cyan]Diperbarui:[/cyan] {', '.join(toggled)}\n")
    else:
        console.print("[yellow]Tidak ada pilihan nomor yang valid.[/yellow]\n")


def show_mcp_status(tool_manager: ToolManager):
    """Tampilkan status server MCP dari mcp_servers.json."""
    if not tool_manager.mcp_status:
        console.print("[dim]Tidak ada server MCP yang dikonfigurasi di mcp_servers.json.[/dim]\n")
        return

    table = Table(
        title="Status Server MCP (mcp_servers.json)",
        box=box.SQUARE,
        border_style="bright_black",
    )
    table.add_column("Nama Server", style="bold white")
    table.add_column("Status", style="cyan")

    for name, status in tool_manager.mcp_status.items():
        table.add_row(name, status)

    console.print(table)
    console.print()


def handle_tool_command(arg: str, tool_manager: ToolManager):
    """Proses argumen dari perintah /tool."""
    tool_manager.reload_python_tools()
    if not arg:
        interactive_tool_selector(tool_manager)
        return

    lower_arg = arg.lower()
    if lower_arg == "all on":
        tool_manager.set_all_enabled(True)
        console.print("[green]Semua tools diaktifkan.[/green]\n")
        return
    if lower_arg == "all off":
        tool_manager.set_all_enabled(False)
        console.print("[yellow]Semua tools dinonaktifkan.[/yellow]\n")
        return

    parts = arg.split(maxsplit=1)
    if len(parts) == 2 and parts[0].lower() in ("on", "off", "toggle"):
        action = parts[0].lower()
        target_name = parts[1].strip()
        if action == "on":
            ok = tool_manager.set_tool_enabled(target_name, True)
            msg = f"[green]Tool '{target_name}' diaktifkan.[/green]\n"
        elif action == "off":
            ok = tool_manager.set_tool_enabled(target_name, False)
            msg = f"[yellow]Tool '{target_name}' dinonaktifkan.[/yellow]\n"
        else:
            state = tool_manager.toggle_tool(target_name)
            ok = state is not None
            msg = f"[cyan]Tool '{target_name}' sekarang {'AKTIF' if state else 'NONAKTIF'}.[/cyan]\n"

        if ok:
            console.print(msg)
        else:
            console.print(f"[red]Tool '{target_name}' tidak ditemukan.[/red] Ketik /tools untuk melihat daftar.\n")
        return

    # Jika user langsung ketik '/tool <nama_tool>', toggle tool tersebut
    state = tool_manager.toggle_tool(arg.strip())
    if state is not None:
        console.print(f"[cyan]Tool '{arg.strip()}' sekarang {'AKTIF' if state else 'NONAKTIF'}.[/cyan]\n")
    else:
        console.print("[dim]Format: /tool | /tool on <nama> | /tool off <nama> | /tool all on | /tool all off[/dim]\n")


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
    tool_manager = ToolManager()

    console.print("[dim]Memuat custom tools & server MCP...[/dim]", end="\r")
    tool_manager.reload_mcp_servers()
    console.print(" " * 45, end="\r")

    available_prompts = list_available_prompts()
    active_prompt_name = "default" if "default" in available_prompts else available_prompts[0]
    active_system_prompt = get_system_prompt(active_prompt_name)
    active_model = config.model

    print_banner(config, active_prompt_name, available_prompts, tool_manager)

    conversation_history: List[Dict[str, Any]] = [
        {"role": "system", "content": active_system_prompt}
    ]

    completer = SlashCommandCompleter(COMMANDS, tool_manager)
    session = PromptSession(completer=completer, style=pt_style, complete_while_typing=True)

    try:
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

                elif cmd == "/tools":
                    show_tools_table(tool_manager)
                    continue

                elif cmd == "/tool":
                    handle_tool_command(arg, tool_manager)
                    continue

                elif cmd == "/mcp":
                    if arg.lower() == "reload":
                        console.print("[dim]Memuat ulang tools Python & server MCP...[/dim]")
                        tool_manager.reload_python_tools()
                        tool_manager.reload_mcp_servers()
                    show_mcp_status(tool_manager)
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
                        console.print(f"[dim]Model saat ini:[/dim] [bold]{active_model or '(auto)'}[/bold]")
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

            # Sinkronkan Python tools terbaru sebelum mengirim
            tool_manager.reload_python_tools()
            active_openai_tools = tool_manager.get_openai_tools() or None

            conversation_history.append({"role": "user", "content": user_input})
            snapshot_len = len(conversation_history) - 1

            try:
                ai_reply = ""
                display_model = active_model or config.model or "AI"

                for _ in range(MAX_TOOL_ITERATIONS):
                    console.print("[dim]AI sedang merespons...[/dim]", end="\r")
                    response = client.chat(
                        messages=conversation_history,
                        model=active_model,
                        tools=active_openai_tools,
                    )
                    console.print(" " * 35, end="\r")

                    if response.model:
                        display_model = response.model

                    if response.tool_calls:
                        # Simpan pesan assistant yang meminta pemanggilan tool
                        conversation_history.append(
                            {
                                "role": "assistant",
                                "content": response.content or None,
                                "tool_calls": response.tool_calls,
                            }
                        )

                        for tc in response.tool_calls:
                            fn_info = tc.get("function", {})
                            fn_name = fn_info.get("name", "")
                            fn_args = fn_info.get("arguments", "{}")
                            call_id = tc.get("id", fn_name)

                            console.print(f"[dim][TOOL] Menjalankan[/dim] [cyan]{fn_name}[/cyan][dim]({fn_args})[/dim]")
                            tool_output = tool_manager.execute_tool(fn_name, fn_args)

                            conversation_history.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": call_id,
                                    "name": fn_name,
                                    "content": tool_output,
                                }
                            )
                        continue

                    ai_reply = response.content
                    break

                if ai_reply:
                    md = Markdown(ai_reply)
                    panel = Panel(
                        md,
                        title=f"[bold white]{display_model}[/bold white]",
                        border_style="bright_black",
                        box=box.SQUARE,
                    )
                    console.print(panel)
                    console.print()
                    conversation_history.append({"role": "assistant", "content": ai_reply})
                else:
                    console.print("[yellow]AI tidak memberikan jawaban teks akhir setelah memanggil tool.[/yellow]\n")

            except Exception as e:
                console.print(" " * 35, end="\r")
                console.print(f"[red]Gagal mendapatkan respons:[/red] {e}\n")
                if active_openai_tools and "400" in str(e):
                    console.print(
                        "[dim]Tip: Jika model yang dipakai belum mendukung Tool Calling, "
                        "matikan tools sementara dengan perintah '/tool all off'.[/dim]\n"
                    )
                # Kembalikan riwayat ke sebelum pesan user ini gagal
                conversation_history = conversation_history[:snapshot_len]
    finally:
        tool_manager.close_mcp_servers()


if __name__ == "__main__":
    main()
