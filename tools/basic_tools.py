import ast
import datetime
import operator
from pathlib import Path
from ai_engine.tools import tool

# Batasi akses file hanya ke direktori workspace proyek ini
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent


@tool
def waktu_sekarang() -> str:
    """Mengambil tanggal dan waktu lokal saat ini."""
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")


_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_math_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
        left = _eval_math_node(node.left)
        right = _eval_math_node(node.right)
        return float(_SAFE_OPS[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
        return float(_SAFE_OPS[type(node.op)](_eval_math_node(node.operand)))
    raise ValueError("Ekspresi matematika tidak diizinkan.")


@tool
def hitung_matematika(ekspresi: str) -> str:
    """Menghitung ekspresi matematika dasar secara aman (contoh: '125 * 4 + 10')."""
    if len(ekspresi) > 200:
        return "Ekspresi terlalu panjang."
    tree = ast.parse(ekspresi.strip(), mode="eval")
    result = _eval_math_node(tree.body)
    if result.is_integer():
        return str(int(result))
    return str(result)


@tool
def daftar_file_proyek() -> str:
    """Melihat daftar file yang ada di direktori utama proyek ini."""
    items = []
    for p in sorted(WORKSPACE_ROOT.iterdir()):
        if p.name.startswith(".") or p.name == "__pycache__":
            continue
        suffix = "/" if p.is_dir() else ""
        items.append(f"{p.name}{suffix}")
    return "\n".join(items)
