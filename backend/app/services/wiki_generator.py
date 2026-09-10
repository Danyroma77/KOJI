"""
=============================================================================
WIKI GENERATOR — GENERA PAGINE MARKDOWN NAVIGABILI
=============================================================================

Genera pagine wiki semantiche a partire dai documenti processati della KB.
Le pagine sono organizzate in un indice navigabile per categorie.

STRUTTURA:
- Indice: gruppi di pagine (Regolamenti, Circolari, Procedure, FAQ, Altro)
- Pagine: contenuto Markdown con titolo, corpo e fonti
- Generazione: aggregazione automatica da sezioni dei documenti

GENERAZIONE:
- Le pagine sono create dalle sezioni dei documenti (titoli H1-H6)
- Il LLM può migliorare/introdurre le pagine (se disponibile)
- L'indice è costruito automaticamente dai nomi dei file
- Le pagine sono salvate come file Markdown (.md)

CATEGORIE (euristica basata sul nome file):
- Regolamenti: file con "regolament" nel nome
- Circolari: file con "circolar" nel nome
- Procedure: file con "procedur" o "manuale" nel nome
- FAQ: file con "faq" nel nome
- Altro: tutto il resto
"""

from __future__ import annotations
import asyncio
import re
import json
from pathlib import Path
from typing import Optional

from app.config import settings


class WikiGenerator:
    """
    Genera pagine wiki semantiche dai documenti della KB.
    
    Crea automaticamente pagine Markdown navigabili organizzate
    in categorie, con contenuto aggregato dai documenti sorgente.
    """

    def __init__(self):
        self.wiki_dir = settings.WIKI_DIR
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        self._llm_enabled = True

    async def _generate_with_llm(self, prompt: str, max_tokens: int = 1000) -> Optional[str]:
        """Genera contenuto usando il LLM. Restituisce None se il LLM non è disponibile."""
        if not self._llm_enabled:
            return None
        try:
            response = await llm_manager.generate(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return response.strip() if response else None
        except Exception:
            self._llm_enabled = False
            return None

    async def _enhance_page_content(self, title: str, content: str) -> str:
        """Migliora il contenuto di una pagina usando il LLM."""
        max_content_length = 3000
        if len(content) > max_content_length:
            content = content[:max_content_length] + "..."

        prompt = WIKI_SUMMARY_PROMPT.format(title=title, content=content)
        enhanced = await self._generate_with_llm(prompt, max_tokens=1500)

        if enhanced and not enhanced.startswith("Errore"):
            return enhanced
        return content

    async def _generate_page_intro(self, title: str, content: str) -> str:
        """Genera un'introduzione per la pagina wiki."""
        context = content[:500] if content else title

        prompt = WIKI_INTRO_PROMPT.format(title=title, context=context)
        intro = await self._generate_with_llm(prompt, max_tokens=200)

        if intro and not intro.startswith("Errore"):
            return intro
        return ""

    def generate_all_sync(self, documents: list[dict]) -> dict:
        """Versione sincrona di generate_all per compatibilità."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.generate_all(documents))

    async def generate_all(self, documents: list[dict]) -> dict:
        """Genera pagine wiki per tutti i documenti processati.

        Args:
            documents: Lista di dict con chiavi {id, filename, processed_text, metadata}.

        Returns:
            Struttura dell'indice wiki generato.
        """
        import importlib
        # Raggruppa per argomento (semplice: per titolo/sezione)
        pages = {}

        for doc in documents:
            text = doc.get("processed_text", "")
            if not text:
                continue

            # Estrai sezioni dal testo markdown
            sections = self._extract_sections(text, doc)

            for section in sections:
                page_id = self._slugify(section["title"])
                if page_id not in pages:
                    pages[page_id] = {
                        "id": page_id,
                        "title": section["title"],
                        "content": f"# {section['title']}\n\n",
                        "sources": set(),
                    }
                pages[page_id]["content"] += section["content"] + "\n\n"
                pages[page_id]["sources"].add(doc.get("filename", "Sconosciuto"))

        # Linking tra entità (semplice: parole in maiuscolo nei titoli)
        pages = self._link_entities(pages)

        # Scrivi file e costruisci indice
        index = self._build_index(pages)

        for page_id, page in pages.items():
            page_path = self.wiki_dir / f"{page_id}.md"
            content = page["content"]
            # Aggiungi fonti in fondo
            content += f"\n\n---\n\n**Fonti:** {', '.join(sorted(page['sources']))}\n"
            page_path.write_text(content, encoding="utf-8")

        # Salva indice
        index_path = self.wiki_dir / "index.json"
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

        return index

    def _extract_sections(self, text: str, doc: dict) -> list[dict]:
        """Estrae sezioni dal testo markdown."""
        sections = []
        current_title = doc.get("filename", "Senza titolo")
        current_content = []
        in_section = False

        for line in text.split("\n"):
            heading_match = re.match(r"^(#{2,4})\s+(.+)$", line)
            if heading_match:
                if in_section and current_content:
                    sections.append({
                        "title": current_title,
                        "content": "\n".join(current_content).strip(),
                    })
                current_title = heading_match.group(2).strip()
                current_content = [line]
                in_section = True
            else:
                current_content.append(line)

        # Ultima sezione
        if current_content:
            sections.append({
                "title": current_title,
                "content": "\n".join(current_content).strip(),
            })

        # Se non ci sono sezioni H2+, il documento intero è una pagina
        if not sections and text.strip():
            sections.append({
                "title": doc.get("metadata", {}).get("title", doc["filename"]),
                "content": text.strip(),
            })

        return sections

    def _link_entities(self, pages: dict) -> dict:
        """Crea collegamenti tra pagine wiki per entità condivise."""
        # Raccogli tutte le parole chiave dai titoli
        title_words = {}
        for page_id, page in pages.items():
            words = re.findall(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b", page["title"])
            for word in words:
                if len(word) > 3:
                    title_words.setdefault(word.lower(), []).append(page_id)

        # Sostituisci nei contenuti
        for page_id, page in pages.items():
            content = page["content"]
            for word, ids in title_words.items():
                if page_id not in ids and len(ids) == 1:
                    # Link alla pagina unica
                    pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
                    target_id = ids[0]
                    content = pattern.sub(
                        f"[{word}](#{target_id})",
                        content,
                    )
            page["content"] = content

        return pages

    def _build_index(self, pages: dict) -> dict:
        """Costruisce la struttura dell'indice wiki."""
        groups = {}
        for page_id, page in pages.items():
            source = list(page["sources"])[0] if page["sources"] else "Altro"
            group_name = self._categorize(source)
            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append({
                "id": page_id,
                "label": page["title"],
            })

        return {
            "groups": [
                {"title": name, "items": items}
                for name, items in groups.items()
            ]
        }

    def _categorize(self, filename: str) -> str:
        """Categorizza un file in un gruppo dell'indice."""
        fn = filename.lower()
        if "regolament" in fn:
            return "Regolamenti"
        elif "circolar" in fn:
            return "Circolari"
        elif "procedur" in fn or "manuale" in fn:
            return "Procedure"
        elif "faq" in fn:
            return "FAQ"
        else:
            return "Altro"

    def _slugify(self, text: str) -> str:
        """Converte un titolo in uno slug URL-safe."""
        text = text.lower().strip()
        text = re.sub(r"[àáâãäå]", "a", text)
        text = re.sub(r"[èéêë]", "e", text)
        text = re.sub(r"[ìíîï]", "i", text)
        text = re.sub(r"[òóôõö]", "o", text)
        text = re.sub(r"[ùúûü]", "u", text)
        text = re.sub(r"[^a-z0-9]+", "-", text)
        text = text.strip("-")
        return text[:60] or "page"

    def get_page(self, page_id: str) -> Optional[dict]:
        """Legge una pagina wiki dal disco."""
        page_path = self.wiki_dir / f"{page_id}.md"
        if page_path.exists():
            content = page_path.read_text(encoding="utf-8")
            title = page_id.replace("-", " ").title()
            first_line = content.split("\n")[0]
            if first_line.startswith("# "):
                title = first_line[2:].strip()
            sources = []
            for line in content.split("\n"):
                if line.startswith("**Fonti:**"):
                    sources_str = line.replace("**Fonti:**", "").strip()
                    sources = [s.strip() for s in sources_str.split("·")]
                    if not sources:
                        sources = [s.strip() for s in sources_str.split(",")]
            return {"id": page_id, "title": title, "content": content, "sources": sources}
        return None

    def get_index(self) -> dict:
        """Legge l'indice wiki dal disco."""
        index_path = self.wiki_dir / "index.json"
        if index_path.exists():
            return json.loads(index_path.read_text(encoding="utf-8"))
        return {"groups": []}

    def reset(self):
        """Elimina tutte le pagine wiki e l'indice.

        Invocato quando la Knowledge Base viene svuotata (e, per coerenza,
        ogni volta che una rigenerazione non ha documenti pronti): la wiki
        è un artefatto derivato e non deve sopravvivere ai suoi documenti.
        """
        if not self.wiki_dir.exists():
            return
        for f in self.wiki_dir.glob("*.md"):
            f.unlink()
        index_path = self.wiki_dir / "index.json"
        if index_path.exists():
            index_path.unlink()


# Istanza singleton
wiki_generator = WikiGenerator()