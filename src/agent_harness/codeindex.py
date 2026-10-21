"""Code map and search, so a small model knows where to look.

The project is split into chunks (one per function, class or Markdown
section). search_code ranks them with BM25, a classic keyword ranking.
If HARNEASY_EMBED_MODEL is set, it also ranks them by meaning with an
embedding model and merges both rankings, so "desenvolvimento" can find
code about "development".
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .permissions import PROJECT_ROOT

IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", "dist", "build"}
SOURCE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".rb", ".php",
    ".c", ".h", ".cpp", ".cs", ".swift", ".md", ".html", ".css", ".toml", ".yaml", ".yml", ".json",
}
MAX_FILE_BYTES = 300_000
MAX_CHUNK_LINES = 80
WINDOW_LINES = 40

# Lines that start a function or class in languages other than Python.
SYMBOL_PATTERNS = [
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)"),     # JS/TS function
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)"),           # JS/TS/Java/PHP class
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\(|\w+\s*=>)"),  # arrow function
    re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)"),                                        # Go
    re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)"),                     # Rust
    re.compile(r"^\s*def\s+(\w+)"),                                                         # Ruby
    re.compile(r"^\s*(?:(?:public|private|protected|internal|static|final|override|virtual|async)\s+)+[\w<>\[\],]+\s+(\w+)\s*\("),  # Java/C#
]
HEADING_PATTERN = re.compile(r"^#{1,4}\s+\S")  # Markdown section


@dataclass
class Chunk:
    path: str  # relative to the project root
    start: int
    end: int
    name: str  # e.g. "def total(self)", "class Cart", "## Instalação" or "" for a plain window
    doc: str   # first line of the docstring, if any
    text: str  # the code itself


# ---------------------------------------------------------------- files

def walk_files(base: Path):
    """Yield every file under base, skipping dependency and cache folders."""
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
        for name in sorted(files):
            yield Path(root) / name


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------- chunking

def _python_chunks(path: str, text: str) -> list[Chunk]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()
    chunks = []
    definitions = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    # Module-level code (imports, constants, config) between definitions
    # becomes one chunk per contiguous block.
    module_doc = (ast.get_docstring(tree) or "").strip().splitlines()
    block: list[ast.stmt] = []
    for node in [*tree.body, None]:
        if node is not None and not isinstance(node, definitions):
            block.append(node)
            continue
        if block:
            start, end = block[0].lineno, block[-1].end_lineno or block[-1].lineno
            doc = module_doc[0] if module_doc and start == 1 else ""
            chunks.append(Chunk(path, start, end, "", doc, "\n".join(lines[start - 1:end])[:4000]))
            block = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = ", ".join(arg.arg for arg in node.args.args)
            name = f"def {node.name}({args})"
        elif isinstance(node, ast.ClassDef):
            name = f"class {node.name}"
        else:
            continue
        doc = (ast.get_docstring(node) or "").strip().splitlines()
        end = min(node.end_lineno or node.lineno, node.lineno + MAX_CHUNK_LINES - 1)
        chunks.append(Chunk(path, node.lineno, end, name, doc[0] if doc else "", "\n".join(lines[node.lineno - 1:end])))
    chunks.sort(key=lambda chunk: chunk.start)
    return chunks


def _starts_chunk(line: str, markdown: bool) -> bool:
    if markdown:
        return bool(HEADING_PATTERN.match(line))
    return any(pattern.match(line) for pattern in SYMBOL_PATTERNS)


def _pattern_chunks(path: str, text: str, markdown: bool) -> list[Chunk]:
    """Split at lines that look like a function, class or Markdown heading."""
    lines = text.splitlines()
    starts = [(number, line.strip()[:100]) for number, line in enumerate(lines, start=1) if _starts_chunk(line, markdown)]
    chunks = []
    for index, (start, name) in enumerate(starts):
        next_start = starts[index + 1][0] if index + 1 < len(starts) else len(lines) + 1
        end = min(next_start - 1, start + MAX_CHUNK_LINES - 1)
        chunks.append(Chunk(path, start, end, name, "", "\n".join(lines[start - 1:end])))
    return chunks


def _window_chunks(path: str, text: str) -> list[Chunk]:
    lines = text.splitlines()
    return [
        Chunk(path, start, min(start + WINDOW_LINES - 1, len(lines)), "", "", "\n".join(lines[start - 1:start + WINDOW_LINES - 1]))
        for start in range(1, len(lines) + 1, WINDOW_LINES)
    ]


def chunk_file(path: Path) -> list[Chunk]:
    """Split one file into searchable chunks."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return []
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    relative = _relative(path)
    if path.suffix == ".py":
        chunks = _python_chunks(relative, text)
    else:
        chunks = _pattern_chunks(relative, text, markdown=path.suffix == ".md")
    # Files without functions (configs, scripts) are still searchable by windows.
    return chunks or _window_chunks(relative, text)


# ---------------------------------------------------------------- BM25

def tokenize(text: str) -> list[str]:
    """Words for search: no accents, camelCase and snake_case split, simple plurals."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    words = []
    for word in re.findall(r"[A-Za-z][A-Za-z0-9]+", text):
        word = word.lower()
        if len(word) > 3 and word.endswith("s"):
            word = word[:-1]  # "tarefas" and "tarefa" become the same word
        words.append(word)
    return words


# Common programming words in Portuguese and their English names in code,
# so "desfazer edição" also finds undo_last_edit without an embedding model.
PT_TO_EN = {
    "adicionar": "add", "apagar": "delete remove", "arquivo": "file", "atualizar": "update",
    "autenticacao": "auth authentication login", "banco": "database db", "bloquear": "block deny",
    "buscar": "search find", "cadastro": "register signup", "carregar": "load", "comando": "command",
    "compactar": "compact", "conexao": "connection connect", "configuracao": "config settings",
    "contexto": "context", "criar": "create", "dado": "data", "desenvolvimento": "development dev debug",
    "desfazer": "undo", "edicao": "edit", "editar": "edit", "enviar": "send", "erro": "error exception",
    "escrever": "write", "excluir": "delete", "ferramenta": "tool", "historico": "history",
    "lembrete": "reminder", "ler": "read", "limite": "limit", "lista": "list", "mensagem": "message",
    "modelo": "model", "pagamento": "payment", "perigoso": "dangerous", "permissao": "permission",
    "pesquisa": "search", "prompt": "prompt", "registro": "log record", "repetir": "repeat",
    "resposta": "response reply", "rota": "route", "salvar": "save", "senha": "password",
    "tarefa": "task todo", "tela": "screen view", "tempo": "time timeout", "teste": "test",
    "token": "token", "usuario": "user", "validar": "validate", "verificar": "check verify",
}
EXPANSIONS = {tokenize(pt)[0]: tokenize(en) for pt, en in PT_TO_EN.items()}
DOC_WEIGHT = 0.5  # Markdown ranks below code that matches as well


def expand_query(query: str) -> list[str]:
    words = tokenize(query)
    return words + [english for word in words for english in EXPANSIONS.get(word, [])]


def _chunk_tokens(chunk: Chunk) -> list[str]:
    # Path, name and docstring count three times: they describe the chunk best.
    title = tokenize(f"{chunk.path} {chunk.name} {chunk.doc}")
    return title * 3 + tokenize(chunk.text)


def bm25_scores(query: list[str], documents: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Score every document for the query with the BM25 formula."""
    if not documents:
        return []
    counts = [Counter(document) for document in documents]
    average_length = sum(len(document) for document in documents) / len(documents) or 1
    document_frequency = Counter(word for count in counts for word in count)
    scores = []
    for count, document in zip(counts, documents):
        score = 0.0
        for word in set(query):
            frequency = count.get(word, 0)
            if not frequency:
                continue
            rarity = math.log(1 + (len(documents) - document_frequency[word] + 0.5) / (document_frequency[word] + 0.5))
            score += rarity * frequency * (k1 + 1) / (frequency + k1 * (1 - b + b * len(document) / average_length))
        scores.append(score)
    return scores


# ---------------------------------------------------------------- embeddings (optional)

EMBED_BATCH = 32
CACHE_DIR = Path(os.getenv("HARNEASY_CACHE_DIR", Path.home() / ".cache" / "harneasy"))


def embed_model() -> str:
    return os.getenv("HARNEASY_EMBED_MODEL", "").strip()


def _embed(texts: list[str]) -> list[list[float]]:
    from .llm import client  # imported here so the index works without a server

    vectors = []
    for start in range(0, len(texts), EMBED_BATCH):
        response = client.embeddings.create(model=embed_model(), input=texts[start:start + EMBED_BATCH])
        vectors.extend(item.embedding for item in response.data)
    return vectors


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    size = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / size if size else 0.0


class EmbeddingCache:
    """Vectors saved on disk by content hash, so unchanged chunks are never re-embedded."""

    def __init__(self) -> None:
        project = hashlib.sha1(str(PROJECT_ROOT).encode()).hexdigest()[:12]
        self.path = CACHE_DIR / f"embeddings-{project}.json"
        try:
            self.vectors: dict[str, list[float]] = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.vectors = {}

    @staticmethod
    def key(text: str) -> str:
        return hashlib.sha1(f"{embed_model()}\n{text}".encode()).hexdigest()

    def vectors_for(self, texts: list[str]) -> list[list[float]]:
        missing = [text for text in dict.fromkeys(texts) if self.key(text) not in self.vectors]
        if missing:
            for text, vector in zip(missing, _embed(missing)):
                self.vectors[self.key(text)] = vector
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.vectors))
        return [self.vectors[self.key(text)] for text in texts]


def _embedding_text(chunk: Chunk) -> str:
    return f"{chunk.path}\n{chunk.name}\n{chunk.doc}\n{chunk.text[:1500]}"


# ---------------------------------------------------------------- index

class CodeIndex:
    """Chunks of every project file, refreshed only for files that changed."""

    def __init__(self, root: Path = PROJECT_ROOT) -> None:
        self.root = root
        self.files: dict[Path, tuple[float, list[Chunk]]] = {}
        self.embeddings: EmbeddingCache | None = None

    def refresh(self, base: Path | None = None) -> list[Chunk]:
        base = base or self.root
        current = {}
        for path in ([base] if base.is_file() else walk_files(base)):
            if path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            cached = self.files.get(path)
            current[path] = cached if cached and cached[0] == mtime else (mtime, chunk_file(path))
        # Forget files under base that were deleted since the last refresh.
        for path in [p for p in self.files if (p == base or base in p.parents) and p not in current]:
            del self.files[path]
        self.files.update(current)
        return [chunk for _, chunks in current.values() for chunk in chunks]

    def search(self, query: str, max_results: int = 8) -> tuple[list[Chunk], str]:
        """Return the best chunks and a note about how they were ranked."""
        chunks = self.refresh()
        keyword_scores = bm25_scores(expand_query(query), [_chunk_tokens(chunk) for chunk in chunks])
        keyword_scores = [
            score * DOC_WEIGHT if chunk.path.endswith(".md") else score
            for score, chunk in zip(keyword_scores, chunks)
        ]
        keyword_rank = [i for i in sorted(range(len(chunks)), key=lambda i: -keyword_scores[i]) if keyword_scores[i] > 0]
        note = "busca por palavras (BM25)"

        meaning_rank: list[int] = []
        if embed_model() and chunks:
            try:
                self.embeddings = self.embeddings or EmbeddingCache()
                vectors = self.embeddings.vectors_for([_embedding_text(chunk) for chunk in chunks])
                [query_vector] = _embed([query])
                similarity = [_cosine(query_vector, vector) for vector in vectors]
                meaning_rank = sorted(range(len(chunks)), key=lambda i: -similarity[i])[:50]
                note = f"busca por palavras + significado ({embed_model()})"
            except Exception as error:  # a missing embedding model must not break search
                note = f"busca por palavras (embeddings indisponíveis: {type(error).__name__})"

        # Reciprocal rank fusion: a chunk ranked high in either list wins.
        fused: Counter[int] = Counter()
        for ranking in (keyword_rank, meaning_rank):
            for position, index in enumerate(ranking):
                fused[index] += 1 / (60 + position)
        best = [index for index, _ in fused.most_common(max_results)]
        return [chunks[index] for index in best], note


INDEX = CodeIndex()


# ---------------------------------------------------------------- tools

MAX_MAP_LINES = 200


def code_map(path: str = ".") -> str:
    """List files with their classes and functions: a table of contents of the code."""
    base = Path(path).expanduser()
    base = (base if base.is_absolute() else PROJECT_ROOT / base).resolve()
    INDEX.refresh(base)
    lines = []
    for file_path in sorted(p for p in INDEX.files if p == base or base in p.parents):
        chunks = [chunk for chunk in INDEX.files[file_path][1] if chunk.name]
        lines.append(_relative(file_path))
        for chunk in chunks:
            doc = f" — {chunk.doc[:80]}" if chunk.doc else ""
            lines.append(f"  {chunk.start}: {chunk.name}{doc}")
    if not lines:
        return f"Nenhum arquivo de código em {_relative(base)}."
    if len(lines) > MAX_MAP_LINES:
        hidden = len(lines) - MAX_MAP_LINES
        lines = lines[:MAX_MAP_LINES] + [f"[... mais {hidden} linhas. Passe um path mais específico.]"]
    return "\n".join(lines)


def search_code(query: str, max_results: int = 8) -> str:
    """Find the functions, classes and sections most related to a subject."""
    if not query.strip():
        return "Erro: informe o assunto a buscar."
    results, note = INDEX.search(query, max(1, min(max_results, 20)))
    if not results:
        return f"Nada encontrado para '{query}' ({note}). Tente outras palavras ou o grep."
    lines = [f"[{note}]"]
    for number, chunk in enumerate(results, start=1):
        first_line = next((line.strip() for line in chunk.text.splitlines() if line.strip()), "")
        # Under the location, show the docstring; for plain chunks, their first line.
        detail = chunk.doc or ("" if chunk.name else first_line)
        lines.append(f"{number}. {chunk.path}:{chunk.start}-{chunk.end}  {chunk.name or '(trecho)'}")
        if detail:
            lines.append(f"   {detail[:120]}")
    lines.append("Use read_file com start_line para ler um resultado.")
    return "\n".join(lines)
