import os
import sqlite3
from typing import List, Dict, Any, Optional

class RepoMap:
    def __init__(self, db_path: str, repo_root: str):
        self.db_path = db_path
        self.repo_root = repo_root

    def _get_symbols_for_file(self, rel_path: str) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, kind, signature 
            FROM symbols 
            WHERE file_path = ?
            ORDER BY line_start ASC
        """, (rel_path,))
        rows = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def generate_map(self, max_depth: int = 5) -> str:
        """Generate a text-based map of the project with symbol signatures."""
        lines = ["Project Map:", ""]
        
        for root, dirs, files in os.walk(self.repo_root):
            # Skip hidden and venv dirs
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ["node_modules", "venv", ".venv"]]
            
            rel_root = os.path.relpath(root, self.repo_root)
            depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1
            
            if depth > max_depth:
                continue
                
            indent = "  " * depth
            if rel_root != ".":
                lines.append(f"{indent}[dir] {os.path.basename(root)}/")
            
            for file in files:
                ext = os.path.splitext(file)[1]
                if ext not in [".py", ".js", ".ts", ".tsx", ".jsx"]:
                    continue
                    
                rel_file = os.path.relpath(os.path.join(root, file), self.repo_root)
                lines.append(f"{indent}  [file] {file}")
                
                # Add symbols
                symbols = self._get_symbols_for_file(rel_file)
                for s in symbols:
                    s_indent = indent + "    "
                    kind_sym = "C" if s["kind"] == "class" else "f"
                    lines.append(f"{s_indent}└─ {kind_sym} {s['signature']}")
                    
        return "\n".join(lines)

if __name__ == "__main__":
    rm = RepoMap("runtime/state/code_index.db", ".")
    print(rm.generate_map())
