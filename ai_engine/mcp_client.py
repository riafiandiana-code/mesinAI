import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests


class MCPStdioClient:
    """Client MCP (Model Context Protocol) berbasis JSON-RPC 2.0 via stdio."""

    def __init__(
        self,
        name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: int = 20,
    ):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.timeout = timeout
        self.process: Optional[subprocess.Popen] = None
        self._req_id = 0
        self._lock = threading.Lock()
        self._pending: Dict[int, queue.Queue] = {}
        self._reader_thread: Optional[threading.Thread] = None
        self._connected = False

    def connect(self) -> None:
        if self._connected and self.process and self.process.poll() is None:
            return

        resolved_cmd = shutil.which(self.command) or self.command
        proc_env = os.environ.copy()
        # Keamanan: jangan wariskan API key utama ke subprocess MCP kecuali diminta eksplisit
        proc_env.pop("AI_API_KEY", None)
        for k, v in self.env.items():
            proc_env[str(k)] = str(v)

        self.process = subprocess.Popen(
            [resolved_cmd, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=proc_env,
            shell=False,
        )

        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

        # Handshake MCP: initialize -> notifications/initialized
        self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mesinAI", "version": "1.0.0"},
            },
        )
        self._send_notification("notifications/initialized", {})
        self._connected = True

    def _read_loop(self) -> None:
        if not self.process or not self.process.stdout:
            return
        for line in self.process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            req_id = msg.get("id")
            if req_id is not None and req_id in self._pending:
                self._pending[req_id].put(msg)

    def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            return
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        with self._lock:
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()

    def _send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.process or self.process.poll() is not None or not self.process.stdin:
            raise RuntimeError(f"Server MCP '{self.name}' tidak berjalan.")

        with self._lock:
            self._req_id += 1
            req_id = self._req_id
            resp_queue: queue.Queue = queue.Queue()
            self._pending[req_id] = resp_queue
            payload = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method,
                "params": params,
            }
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()

        try:
            msg = resp_queue.get(timeout=self.timeout)
        except queue.Empty:
            raise TimeoutError(f"Server MCP '{self.name}' timeout pada '{method}'.")
        finally:
            self._pending.pop(req_id, None)

        if "error" in msg:
            err = msg["error"]
            raise RuntimeError(f"MCP error ({self.name}): {err.get('message', err)}")

        return msg.get("result", {})

    def list_tools(self) -> List[Dict[str, Any]]:
        if not self._connected:
            self.connect()
        result = self._send_request("tools/list", {})
        return result.get("tools", [])

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        if not self._connected:
            self.connect()
        result = self._send_request(
            "tools/call", {"name": tool_name, "arguments": arguments}
        )
        return _format_mcp_tool_result(result)

    def close(self) -> None:
        self._connected = False
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                self.process.kill()
        self.process = None


class MCPHttpClient:
    """Client MCP sederhana berbasis HTTP JSON-RPC (untuk endpoint MCP remote/lokal)."""

    def __init__(
        self,
        name: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 20,
    ):
        self.name = name
        self.url = url.strip()
        self.headers = headers or {}
        self.timeout = timeout
        self._req_id = 0
        self.session = requests.Session()

    def _send_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._req_id += 1
        req_headers = {"Content-Type": "application/json", "Accept": "application/json"}
        req_headers.update(self.headers)
        payload = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": params,
        }
        res = self.session.post(
            self.url, headers=req_headers, json=payload, timeout=self.timeout
        )
        res.raise_for_status()
        msg = res.json()
        if "error" in msg:
            raise RuntimeError(f"MCP HTTP error ({self.name}): {msg['error']}")
        return msg.get("result", {})

    def connect(self) -> None:
        self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mesinAI", "version": "1.0.0"},
            },
        )

    def list_tools(self) -> List[Dict[str, Any]]:
        result = self._send_request("tools/list", {})
        return result.get("tools", [])

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        result = self._send_request(
            "tools/call", {"name": tool_name, "arguments": arguments}
        )
        return _format_mcp_tool_result(result)

    def close(self) -> None:
        self.session.close()


def _format_mcp_tool_result(result: Dict[str, Any]) -> str:
    """Konversi konten respons MCP menjadi string bersih untuk LLM."""
    content_items = result.get("content", [])
    if isinstance(content_items, list) and content_items:
        parts = []
        for item in content_items:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        output = "\n".join(parts)
    else:
        output = json.dumps(result, ensure_ascii=False)

    if result.get("isError"):
        return f"[MCP TOOL ERROR] {output}"
    return output


def load_mcp_config(config_path: Path) -> Dict[str, Dict[str, Any]]:
    """Muat konfigurasi server dari mcp_servers.json."""
    if not config_path.is_file():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        return servers if isinstance(servers, dict) else {}
    except Exception:
        return {}
