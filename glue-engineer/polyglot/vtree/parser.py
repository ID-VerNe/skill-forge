"""PolyglotParser - tree-sitter abstraction for multi-language AST parsing."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_HAS_TS = False
try:
    import tree_sitter
    _HAS_TS = True
except ImportError:
    try:
        from tree_sitter import Language, Parser
        _HAS_TS = True
    except ImportError:
        pass

_LANG_GRAMMARS = {
    "python": "tree_sitter_python",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "rust": "tree_sitter_rust",
    "java": "tree_sitter_java",
    "kotlin": "tree_sitter_kotlin",
    "c": "tree_sitter_c",
    "cpp": "tree_sitter_cpp",
}

class PolyglotParser:
    def __init__(self):
        self._parsers = {}

    def has_language(self, lang: str) -> bool:
        if not _HAS_TS: return False
        try:
            self._get_parser(lang)
            return True
        except: return False

    def _get_parser(self, lang: str):
        if lang in self._parsers: return self._parsers[lang]
        grammar_name = _LANG_GRAMMARS.get(lang)
        if not grammar_name: raise ValueError(f"Unknown language: {lang}")
        try:
            grammar_mod = __import__(grammar_name)
            lang_obj = Language(grammar_mod.language())
            parser = Parser()
            parser.set_language(lang_obj)
            self._parsers[lang] = parser
            return parser
        except ImportError as e: raise ImportError(f"Tree-sitter grammar for {lang} not installed")

    def parse(self, source: str, lang: str):
        try:
            parser = self._get_parser(lang)
            tree = parser.parse(source.encode("utf-8"))
            return tree.root_node
        except: return None

    def extract_functions(self, source: str, lang: str) -> list:
        node = self.parse(source, lang)
        if node is None: return []
        queries = {
            "python": "(function_definition name: (identifier) @name)",
            "javascript": "(function_declaration name: (identifier) @name)",
            "rust": "(function_item name: (identifier) @name)",
            "java": "(method_declaration name: (identifier) @name)",
        }
        q_str = queries.get(lang)
        if not q_str: return []
        try:
            lang_obj = Language(_LANG_GRAMMARS[lang].language())
            query = lang_obj.query(q_str)
            captures = query.captures(node)
            return [{"name": n.text.decode("utf-8") if hasattr(n, 'text') else str(n), "kind": "function"} for n, _ in captures]
        except: return []

    def available_languages(self) -> list:
        available = []
        for lang in _LANG_GRAMMARS:
            try:
                if self.has_language(lang): available.append(lang)
            except: pass
        return available

    @staticmethod
    def is_available() -> bool: return _HAS_TS
