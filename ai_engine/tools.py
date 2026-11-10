import importlib.util
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union, get_args, get_origin, get_type_hints

from .mcp_client import MCPHttpClient, MCPStdioClient, load_mcp_config


def _python_type_to_json_schema(py_type: Any) -> Dict[str, Any]:
    """Konversi Python type hint sederhana ke JSON Schema."""
    origin = get_origin(py_type)
    if origin is Union:
        args = [a for a in get_args(py_type) if a is not type(None)]
        if args:
            return _python_type_to_json_schema(args[0])
        return {"type": "string"}
    if origin in (list, List):
        item_args = get_args(py_type)
        items_schema = _python_type_to_json_schema(item_args[0]) if item_args else {"type": "string"}
        return {"type": "array", "items": items_schema}
    if origin in (dict, Dict):
        return {"type": "object"}

    mapping = {
        str: {"type": "string"},
        int: {"type": "integer"},
        float: {"type": "number"},
        bool: {"type": "boolean"},
        list: {"type": "array"},
        dict: {"type": "object"},
    }
    return mapping.get(py_type, {"type": "string"})


def build_openai_schema_from_func(
    func: Callable[..., Any],
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Bangun schema OpenAI Function Calling secara otomatis dari fungsi Python."""
    tool_name = (name or func.__name__).strip()
    tool_desc = (description or inspect.getdoc(func) or f"Jalankan tool {tool_name}").strip()

    sig = inspect.signature(func)
    try:
        hints = get_type_hints(func)
    except Exception:
        hints = {}

    properties: Dict[str, Any] = {}
    required: List[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        annotation = hints.get(param_name, str)
        prop_schema = _python_type_to_json_schema(annotation)
        properties[param_name] = prop_schema

        if param.default is inspect.Parameter.empty:
            # Cek apakah Optional[...]
            origin = get_origin(annotation)
            is_optional = origin is Union and type(None) in get_args(annotation)
            if not is_optional:
                required.append(param_name)

    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": tool_desc,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def tool(
    func: Optional[Callable[..., Any]] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
):
    """
    Dekorator untuk mendaftarkan fungsi Python sebagai custom tool agent.

    Contoh:
        @tool
        def tambah(a: int, b: int) -> int:
            '''Menjumlahkan dua angka.'''
            return a + b
    """

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        f._is_mesinai_tool = True  # type: ignore[attr-defined]
        f._tool_schema = build_openai_schema_from_func(f, name=name, description=description)  # type: ignore[attr-defined]
        return f

    if func is not None:
        return decorator(func)
    return decorator


@dataclass
class ToolEntry:
    name: str
    description: str
    source: str
    schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], str]
    enabled: bool = True


class ToolManager:
    """Pengelola terpusat untuk Python custom tools (folder tools/) dan server MCP."""

    def __init__(
        self,
        tools_dir: Optional[Path] = None,
        mcp_config_path: Optional[Path] = None,
    ):
        root_dir = Path(__file__).resolve().parent.parent
        self.tools_dir = Path(tools_dir) if tools_dir else root_dir / "tools"
        self.mcp_config_path = Path(mcp_config_path) if mcp_config_path else root_dir / "mcp_servers.json"

        self._tools: Dict[str, ToolEntry] = {}
        self._enabled_states: Dict[str, bool] = {}
        self._mcp_clients: Dict[str, Any] = {}
        self.mcp_status: Dict[str, str] = {}

        self.reload_python_tools()

    def _register_entry(self, entry: ToolEntry) -> None:
        if entry.name in self._enabled_states:
            entry.enabled = self._enabled_states[entry.name]
        else:
            self._enabled_states[entry.name] = entry.enabled
        self._tools[entry.name] = entry

    def reload_python_tools(self) -> None:
        """Pindai ulang folder tools/ dan muat semua custom tool Python."""
        # Hapus entri python lama, pertahankan entri MCP yang aktif
        self._tools = {
            k: v for k, v in self._tools.items() if not v.source.startswith("python:")
        }

        if not self.tools_dir.is_dir():
            return

        for py_file in sorted(self.tools_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue

            module_name = f"mesinai_user_tool_{py_file.stem}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, str(py_file))
                if not spec or not spec.loader:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception as e:
                print(f"[PERINGATAN TOOL] Gagal memuat {py_file.name}: {e}")
                continue

            source_label = f"python:{py_file.name}"

            # 1. Deteksi fungsi berdekorator @tool
            for attr_name in dir(module):
                if attr_name.startswith("_"):
                    continue
                obj = getattr(module, attr_name)

                if callable(obj) and getattr(obj, "_is_mesinai_tool", False):
                    schema = obj._tool_schema
                    fn_info = schema["function"]

                    def make_handler(fn: Callable[..., Any]) -> Callable[[Dict[str, Any]], str]:
                        def _run(args: Dict[str, Any]) -> str:
                            res = fn(**args)
                            if isinstance(res, str):
                                return res
                            return json.dumps(res, ensure_ascii=False, default=str)
                        return _run

                    self._register_entry(
                        ToolEntry(
                            name=fn_info["name"],
                            description=fn_info["description"],
                            source=source_label,
                            schema=schema,
                            handler=make_handler(obj),
                        )
                    )

                # 2. Deteksi objek tool bergaya library eksternal (misal LangChain BaseTool)
                elif hasattr(obj, "name") and hasattr(obj, "description") and (
                    hasattr(obj, "invoke") or hasattr(obj, "run")
                ):
                    ext_name = str(getattr(obj, "name"))
                    ext_desc = str(getattr(obj, "description"))
                    params_schema = {"type": "object", "properties": {}, "required": []}
                    args_schema = getattr(obj, "args_schema", None)
                    if args_schema and hasattr(args_schema, "model_json_schema"):
                        raw_schema = args_schema.model_json_schema()
                        params_schema = {
                            "type": "object",
                            "properties": raw_schema.get("properties", {}),
                            "required": raw_schema.get("required", []),
                        }

                    schema = {
                        "type": "function",
                        "function": {
                            "name": ext_name,
                            "description": ext_desc,
                            "parameters": params_schema,
                        },
                    }

                    def make_ext_handler(tool_obj: Any) -> Callable[[Dict[str, Any]], str]:
                        def _run(args: Dict[str, Any]) -> str:
                            if hasattr(tool_obj, "invoke"):
                                res = tool_obj.invoke(args)
                            else:
                                res = tool_obj.run(**args)
                            return res if isinstance(res, str) else json.dumps(res, ensure_ascii=False, default=str)
                        return _run

                    self._register_entry(
                        ToolEntry(
                            name=ext_name,
                            description=ext_desc,
                            source=source_label,
                            schema=schema,
                            handler=make_ext_handler(obj),
                        )
                    )

    def reload_mcp_servers(self) -> Dict[str, str]:
        """Hubungkan ke server MCP yang terdaftar di mcp_servers.json."""
        self.close_mcp_servers()
        self._tools = {
            k: v for k, v in self._tools.items() if not v.source.startswith("mcp:")
        }
        self.mcp_status = {}

        servers = load_mcp_config(self.mcp_config_path)
        for server_name, cfg in servers.items():
            if not isinstance(cfg, dict) or cfg.get("disabled", False):
                self.mcp_status[server_name] = "DISABLED"
                continue

            try:
                if "url" in cfg:
                    client: Any = MCPHttpClient(
                        name=server_name,
                        url=cfg["url"],
                        headers=cfg.get("headers"),
                    )
                elif "command" in cfg:
                    client = MCPStdioClient(
                        name=server_name,
                        command=cfg["command"],
                        args=cfg.get("args", []),
                        env=cfg.get("env", {}),
                    )
                else:
                    self.mcp_status[server_name] = "CONFIG TIDAK VALID"
                    continue

                client.connect()
                mcp_tools = client.list_tools()
                self._mcp_clients[server_name] = client
                self.mcp_status[server_name] = f"AKTIF ({len(mcp_tools)} tools)"

                for mt in mcp_tools:
                    raw_name = mt.get("name", "unnamed")
                    full_name = f"mcp__{server_name}__{raw_name}"
                    desc = mt.get("description") or f"MCP tool {raw_name} dari {server_name}"
                    input_schema = mt.get("inputSchema") or {"type": "object", "properties": {}}

                    openai_schema = {
                        "type": "function",
                        "function": {
                            "name": full_name,
                            "description": desc,
                            "parameters": input_schema,
                        },
                    }

                    def make_mcp_handler(c: Any, t_name: str) -> Callable[[Dict[str, Any]], str]:
                        def _run(args: Dict[str, Any]) -> str:
                            return c.call_tool(t_name, args)
                        return _run

                    self._register_entry(
                        ToolEntry(
                            name=full_name,
                            description=desc,
                            source=f"mcp:{server_name}",
                            schema=openai_schema,
                            handler=make_mcp_handler(client, raw_name),
                        )
                    )

            except Exception as e:
                self.mcp_status[server_name] = f"ERROR ({type(e).__name__}: {str(e)[:80]})"

        return self.mcp_status

    def close_mcp_servers(self) -> None:
        for client in self._mcp_clients.values():
            try:
                client.close()
            except Exception:
                pass
        self._mcp_clients.clear()

    def list_tools(self) -> List[ToolEntry]:
        return [self._tools[k] for k in sorted(self._tools.keys())]

    def get_enabled_tools(self) -> List[ToolEntry]:
        return [t for t in self.list_tools() if t.enabled]

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """Ambil daftar schema OpenAI HANYA untuk tools yang sedang diaktifkan user."""
        return [t.schema for t in self.get_enabled_tools()]

    def set_tool_enabled(self, name: str, enabled: bool) -> bool:
        if name not in self._tools:
            return False
        self._tools[name].enabled = enabled
        self._enabled_states[name] = enabled
        return True

    def toggle_tool(self, name: str) -> Optional[bool]:
        if name not in self._tools:
            return None
        new_state = not self._tools[name].enabled
        self.set_tool_enabled(name, new_state)
        return new_state

    def set_all_enabled(self, enabled: bool) -> None:
        for name in self._tools:
            self.set_tool_enabled(name, enabled)

    def execute_tool(self, name: str, arguments: Union[str, Dict[str, Any]]) -> str:
        """Eksekusi tool dengan validasi status aktif & parsing argumen aman."""
        if name not in self._tools:
            return f"[ERROR] Tool '{name}' tidak ditemukan."

        entry = self._tools[name]
        if not entry.enabled:
            return f"[DITOLAK] Tool '{name}' sedang dinonaktifkan oleh pengguna."

        if isinstance(arguments, str):
            try:
                parsed_args = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                return "[ERROR] Argumen tool bukan JSON yang valid."
        elif isinstance(arguments, dict):
            parsed_args = arguments
        else:
            return "[ERROR] Format argumen tool tidak valid."

        try:
            return entry.handler(parsed_args)
        except Exception as e:
            return f"[ERROR EKSEKUSI TOOL '{name}'] {type(e).__name__}: {e}"
