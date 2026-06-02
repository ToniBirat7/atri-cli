import os
import sqlite3
import hashlib
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

# tree-sitter imports
from tree_sitter import Language, Parser
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript

logger = logging.getLogger(__name__)

@dataclass
class Symbol:
    name: str
    kind: str  # function, class, method
    file_path: str
    line_start: int
    line_end: int
    signature: str
    docstring: Optional[str] = None

class IndexManager:
    def __init__(self, db_path: str, repo_root: str):
        self.db_path = db_path
        self.repo_root = repo_root
        self._init_db()
        self._init_parsers()

    def _init_db(self):
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Table for file metadata (to detect changes)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                hash TEXT,
                last_indexed DATETIME
            )
        """)
        
        # Table for symbols
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                kind TEXT,
                file_path TEXT,
                line_start INTEGER,
                line_end INTEGER,
                signature TEXT,
                docstring TEXT,
                FOREIGN KEY(file_path) REFERENCES files(path) ON DELETE CASCADE
            )
        """)
        
        # Indexes for fast search
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbol_name ON symbols(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbol_file ON symbols(file_path)")
        
        conn.commit()
        conn.close()

    def _init_parsers(self):
        self.parsers = {
            ".py": Parser(Language(tspython.language())),
            ".js": Parser(Language(tsjavascript.language())),
            ".jsx": Parser(Language(tsjavascript.language())),
            ".ts": Parser(Language(tstypescript.language_typescript())),
            ".tsx": Parser(Language(tstypescript.language_tsx())),
        }

    def _get_file_hash(self, path: str) -> str:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    def _extract_symbols(self, file_path: str, content: str, extension: str) -> List[Symbol]:
        parser = self.parsers.get(extension)
        if not parser:
            return []

        tree = parser.parse(bytes(content, "utf8"))
        symbols = []

        # Simple queries for Python (can be expanded for JS/TS)
        # We use tree-sitter queries for more robust extraction
        query_scm = ""
        if extension == ".py":
            query_scm = """
                (class_definition 
                    name: (identifier) @name) @class
                (function_definition 
                    name: (identifier) @name) @func
            """
        elif extension in [".js", ".ts", ".tsx", ".jsx"]:
            query_scm = """
                (class_declaration 
                    name: (_) @name) @class
                (function_declaration 
                    name: (_) @name) @func
                (method_definition 
                    name: (_) @name) @method
                (variable_declarator
                    name: (_) @name
                    value: [(arrow_function) (function_expression)]) @func
            """

        if not query_scm:
            return []

        query = parser.language.query(query_scm)
        captures = query.captures(tree.root_node)
        
        # In tree-sitter-python, captures can be a dict or a list of tuples
        # Version 0.23.2 returns a dict where keys are tag names and values are lists of nodes
        if isinstance(captures, dict):
            for tag, nodes in captures.items():
                if tag in ["class", "func", "method"]:
                    for node in nodes:
                        self._add_symbol(symbols, node, tag, content, file_path)
        else:
            for capture in captures:
                # Some versions return (node, tag_name)
                # Others return (node, tag_index)
                node = capture[0]
                tag = capture[1]
                if isinstance(tag, int):
                    # Resolve tag index to name
                    tag = query.capture_names[tag]
                
                if tag in ["class", "func", "method"]:
                    self._add_symbol(symbols, node, tag, content, file_path)

        return symbols

    def _add_symbol(self, symbols: list, node: Any, tag: str, content: str, file_path: str):
        # Find the name identifier for this node
        name_node = None
        for child in node.children:
            if child.type in ["identifier", "property_identifier"]:
                name_node = child
                break
        
        if not name_node:
            return

        name = content[name_node.start_byte:name_node.end_byte]
        
        # Signature is the first line of the definition
        signature_end = content.find("\n", node.start_byte)
        if signature_end == -1:
            signature_end = node.end_byte
        signature = content[node.start_byte:signature_end]
        
        symbols.append(Symbol(
            name=name,
            kind=tag,
            file_path=os.path.relpath(file_path, self.repo_root),
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=signature.strip()
        ))

    def index_project(self):
        """Walk the project and index changed files."""
        logger.info(f"Indexing project at {self.repo_root}")
        conn = sqlite3.connect(self.db_path)
        
        for root, dirs, files in os.walk(self.repo_root):
            # Skip hidden, venv, runtime, and other non-essential dirs
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in [
                "node_modules", "venv", ".venv", "runtime", "models", "dist", ".git"
            ]]
            
            for file in files:
                ext = os.path.splitext(file)[1]
                if ext not in self.parsers:
                    continue
                
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, self.repo_root)
                file_hash = self._get_file_hash(abs_path)
                
                # Check if file changed
                cursor = conn.cursor()
                cursor.execute("SELECT hash FROM files WHERE path = ?", (rel_path,))
                row = cursor.fetchone()
                
                if row and row[0] == file_hash:
                    continue
                
                logger.info(f"Indexing {rel_path}")
                try:
                    with open(abs_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    symbols = self._extract_symbols(abs_path, content, ext)
                    
                    # Update DB
                    cursor.execute("DELETE FROM symbols WHERE file_path = ?", (rel_path,))
                    cursor.execute("REPLACE INTO files (path, hash, last_indexed) VALUES (?, ?, ?)", 
                                 (rel_path, file_hash, datetime.now().isoformat()))
                    
                    for s in symbols:
                        cursor.execute("""
                            INSERT INTO symbols (name, kind, file_path, line_start, line_end, signature, docstring)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (s.name, s.kind, s.file_path, s.line_start, s.line_end, s.signature, s.docstring))
                    
                    conn.commit()
                except Exception as e:
                    logger.error(f"Failed to index {rel_path}: {e}")

        conn.close()

    def search_symbols(self, query: str) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Simple LIKE search for now
        cursor.execute("""
            SELECT name, kind, file_path, line_start, signature 
            FROM symbols 
            WHERE name LIKE ? 
            LIMIT 1000
        """, (f"%{query}%",))
        
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results

if __name__ == "__main__":
    # Test run
    logging.basicConfig(level=logging.INFO)
    manager = IndexManager("runtime/state/code_index.db", ".")
    manager.index_project()
    print(f"Found {len(manager.search_symbols(''))} total symbols")
