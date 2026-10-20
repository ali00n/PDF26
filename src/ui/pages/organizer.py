"""Organizador visual de páginas: miniaturas com seleção, arrastar para reordenar, girar, duplicar e excluir."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Dict, List, Optional, Sequence, Set, Tuple

import customtkinter as ctk
import pymupdf
from PIL import Image, ImageDraw

from ...domain.tool import PDF_TYPES, ToolSpec
from ...services.pdf.organize import PageRef, assemble
from .. import icons, theme
from ..runner import JobRunner
from ..system import describe_error, reveal
from ..widgets.dnd import enable_drop
from ..widgets.header import PageHeader

THUMB_WIDTH = 128
_RENDER_BATCH = 6
_DRAG_THRESHOLD = 6
_HISTORY_LIMIT = 40
_ids = itertools.count(1)


@dataclass(frozen=True)
class Item:
    uid: int
    ref: PageRef


class ThumbCard(ctk.CTkFrame):
    def __init__(self, master, page: "OrganizerPage", item: Item):
        super().__init__(master, width=THUMB_WIDTH + 20, height=int(THUMB_WIDTH * 1.414) + 46, fg_color=theme.SURFACE, corner_radius=10, border_width=2, border_color=theme.SURFACE)
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.page, self.item = page, item
        self.image_label = ctk.CTkLabel(self, text="…", text_color=theme.TEXT_MUTED)
        self.image_label.grid(row=0, column=0, padx=8, pady=(8, 2))
        self.caption = ctk.CTkLabel(self, text="", font=theme.font(11), text_color=theme.TEXT_MUTED, height=18)
        self.caption.grid(row=1, column=0, pady=(0, 6))
        for widget in (self, self.image_label, self.caption):
            widget.bind("<ButtonPress-1>", lambda event: page.on_press(self, event), add="+")
            widget.bind("<B1-Motion>", lambda event: page.on_motion(event), add="+")
            widget.bind("<ButtonRelease-1>", lambda event: page.on_release(event), add="+")

    def paint(self, selected: bool, drop_target: bool = False) -> None:
        color = theme.WARNING if drop_target else theme.ACCENT if selected else theme.SURFACE
        self.configure(border_color=color, fg_color=theme.ACCENT_SOFT if selected else theme.SURFACE)


class OrganizerPage(ctk.CTkFrame):
    def __init__(self, master, app, tool: ToolSpec, files: Sequence[Path] = ()):
        super().__init__(master, fg_color="transparent")
        self.app, self.tool = app, tool
        self.runner = JobRunner(self)
        self.sources: List[Path] = []
        self.docs: List[pymupdf.Document] = []
        self.items: List[Item] = []
        self.selected: Set[int] = set()
        self.cards: Dict[int, ThumbCard] = {}
        self._history: List[List[Item]] = []
        self._base_images: Dict[Tuple[int, int], Image.Image] = {}
        self._pending: List[int] = []
        self._anchor: Optional[int] = None
        self._drag: Optional[dict] = None
        self._columns = 0
        self._dirty = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        PageHeader(self, tool, app.show_home, app.prefs.is_favorite(tool.id), lambda: app.toggle_favorite(tool.id)).grid(
            row=0, column=0, sticky="ew", padx=theme.PAD * 2, pady=(theme.PAD * 1.5, theme.GAP)
        )
        self._build_toolbar()
        self._grid_holder = ctk.CTkScrollableFrame(self, fg_color=theme.CANVAS, corner_radius=theme.RADIUS)
        self._grid_holder.grid(row=2, column=0, sticky="nsew", padx=theme.PAD * 2)
        self._empty = ctk.CTkLabel(
            self._grid_holder,
            text="Adicione um ou mais PDFs para montar o documento.\nArraste as miniaturas para reordenar · Ctrl/Shift para selecionar várias.",
            font=theme.font(14),
            text_color=theme.TEXT_MUTED,
            justify="center",
        )
        self.status = ctk.CTkLabel(self, text="", font=theme.font(12), text_color=theme.TEXT_MUTED, anchor="w")
        self.status.grid(row=3, column=0, sticky="ew", padx=theme.PAD * 2, pady=theme.GAP)
        self.bind("<Configure>", lambda _event: self._layout(), add="+")
        enable_drop(self._grid_holder, self.add_files)
        self._layout(force=True)
        if files:
            self.after(50, lambda: self.add_files(files))

    # ------------------------------------------------------------------ construção
    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=theme.RADIUS, border_width=1, border_color=theme.BORDER)
        bar.grid(row=1, column=0, sticky="ew", padx=theme.PAD * 2, pady=(0, theme.GAP))
        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.pack(side="left", padx=8, pady=6)
        theme.neutral_button(left, "Adicionar PDF", self._browse, width=126, image=icons.icon("plus", 14)).pack(side="left")
        for image, tip, action in (
            ("rotate_ccw", "Girar à esquerda", lambda: self._rotate(-90)),
            ("rotate_cw", "Girar à direita", lambda: self._rotate(90)),
            ("duplicate", "Duplicar selecionadas", self._duplicate),
            ("file", "Inserir página em branco após a seleção", self._insert_blank),
            ("swap", "Inverter a ordem", self._reverse),
            ("undo", "Desfazer (Ctrl+Z)", self.undo),
        ):
            theme.icon_button(left, icons.icon(image, 18), action, tip, size=34).pack(side="left", padx=(4, 0))
        theme.icon_button(left, icons.icon("trash", 18, theme.DANGER), self._delete, "Excluir selecionadas (Delete)", size=34).pack(side="left", padx=(4, 0))
        theme.neutral_button(left, "Selecionar tudo", self._select_all, width=120).pack(side="left", padx=(12, 0))
        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.pack(side="right", padx=8, pady=6)
        self.save_button = theme.primary_button(right, "Salvar PDF", self.save, width=140, image=icons.icon("save", 15, ("#FFFFFF", "#FFFFFF")))
        self.save_button.pack(side="right")

    # ------------------------------------------------------------------ fontes
    def _browse(self) -> None:
        names = filedialog.askopenfilenames(parent=self, title="Adicionar PDFs", filetypes=list(PDF_TYPES))
        if names:
            self.add_files([Path(name) for name in names])

    def add_files(self, paths: Sequence[Path]) -> None:
        added = 0
        for path in map(Path, paths):
            if path.suffix.lower() != ".pdf":
                continue
            try:
                doc = pymupdf.open("pdf", path.read_bytes())
            except Exception as error:
                messagebox.showerror("PDF26", f"Não foi possível abrir '{path.name}': {error}", parent=self)
                continue
            if doc.needs_pass:
                messagebox.showwarning("PDF26", f"'{path.name}' está protegido por senha. Use 'Desbloquear PDF' antes.", parent=self)
                doc.close()
                continue
            self._remember()
            source = len(self.sources)
            self.sources.append(path)
            self.docs.append(doc)
            self.items += [Item(next(_ids), PageRef(source, number)) for number in range(doc.page_count)]
            added += doc.page_count
        if added:
            self._sync_cards()
            self._status(f"{added} página(s) adicionada(s).")

    # ------------------------------------------------------------------ miniaturas
    def _base_image(self, ref: PageRef) -> Image.Image:
        key = (-1, -1) if ref.blank else (ref.source, ref.page)
        if key not in self._base_images:
            if ref.blank:
                image = Image.new("RGB", (THUMB_WIDTH * 2, int(THUMB_WIDTH * 2 * 1.414)), "white")
                ImageDraw.Draw(image).rectangle((0, 0, image.width - 1, image.height - 1), outline="#CBD5E1", width=2)
            else:
                page = self.docs[ref.source][ref.page]
                zoom = THUMB_WIDTH * 2 / max(page.rect.width, page.rect.height * 0.75)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), annots=True)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            self._base_images[key] = image
        return self._base_images[key]

    def _thumbnail(self, ref: PageRef) -> ctk.CTkImage:
        image = self._base_image(ref)
        if ref.rotation:
            image = image.rotate(-ref.rotation, expand=True)
        image = image.copy()
        image.thumbnail((THUMB_WIDTH * 2, int(THUMB_WIDTH * 2 * 1.414)))
        return ctk.CTkImage(light_image=image, dark_image=image, size=(image.width // 2, image.height // 2))

    def _sync_cards(self) -> None:
        """Cria/destrói cartões conforme `self.items` e agenda renderização das miniaturas novas."""
        alive = {item.uid for item in self.items}
        for uid in [uid for uid in self.cards if uid not in alive]:
            self.cards.pop(uid).destroy()
        self.selected &= alive
        for item in self.items:
            card = self.cards.get(item.uid)
            if card is None:
                self.cards[item.uid] = ThumbCard(self._grid_holder, self, item)
                self._pending.append(item.uid)
            elif card.item != item:
                card.item = item
                self._pending.append(item.uid)
        self._layout(force=True)
        self.after(10, self._render_pending)

    def _render_pending(self) -> None:
        batch, self._pending = self._pending[:_RENDER_BATCH], self._pending[_RENDER_BATCH:]
        for uid in batch:
            card = self.cards.get(uid)
            if card is not None and card.winfo_exists():
                card.image_label.configure(image=self._thumbnail(card.item.ref), text="")
        if self._pending:
            self.after(15, self._render_pending)

    def _layout(self, force: bool = False) -> None:
        scaling = ctk.ScalingTracker.get_widget_scaling(self)
        columns = max(1, int((self.winfo_width() - (theme.PAD * 4 + 30) * scaling) // ((THUMB_WIDTH + 32) * scaling)))
        if columns == self._columns and not force:
            return
        self._columns = columns
        if not self.items:
            self._empty.grid(row=0, column=0, padx=40, pady=80)
        else:
            self._empty.grid_forget()
        sources_count = len(self.sources)
        for index, item in enumerate(self.items):
            card = self.cards[item.uid]
            card.grid(row=index // columns, column=index % columns, padx=6, pady=6)
            source = "branca" if item.ref.blank else (f"{self.sources[item.ref.source].stem[:10]} · p{item.ref.page + 1}" if sources_count > 1 else f"pág. original {item.ref.page + 1}")
            card.caption.configure(text=f"{index + 1}  ·  {source}")
            card.paint(item.uid in self.selected)
        self._status(f"{len(self.items)} página(s) · {len(self.selected)} selecionada(s)")

    # ------------------------------------------------------------------ seleção e arrastar
    def on_press(self, card: ThumbCard, event) -> None:
        uid = card.item.uid
        ctrl, shift = bool(event.state & 0x0004), bool(event.state & 0x0001)
        order = [item.uid for item in self.items]
        if shift and self._anchor in order:
            start, end = sorted((order.index(self._anchor), order.index(uid)))
            self.selected = set(order[start : end + 1])
        elif ctrl:
            self.selected ^= {uid}
            self._anchor = uid
        elif uid not in self.selected:
            self.selected = {uid}
            self._anchor = uid
        self._drag = {"uid": uid, "x": event.x_root, "y": event.y_root, "active": False, "target": None}
        self._layout(force=True)

    def on_motion(self, event) -> None:
        if not self._drag:
            return
        if not self._drag["active"] and abs(event.x_root - self._drag["x"]) + abs(event.y_root - self._drag["y"]) < _DRAG_THRESHOLD:
            return
        self._drag["active"] = True
        self.configure(cursor="fleur")
        target = self._card_at(event.x_root, event.y_root)
        previous = self._drag["target"]
        if previous is not target:
            if previous is not None and previous.winfo_exists():
                previous.paint(previous.item.uid in self.selected)
            if target is not None:
                target.paint(target.item.uid in self.selected, drop_target=True)
            self._drag["target"] = target

    def on_release(self, event) -> None:
        drag, self._drag = self._drag, None
        self.configure(cursor="")
        if not drag:
            return
        if not drag["active"]:
            if not (event.state & 0x0005):  # clique simples sem Ctrl/Shift seleciona só este
                self.selected = {drag["uid"]}
                self._layout(force=True)
            return
        target = self._card_at(event.x_root, event.y_root)
        if target is None or target.item.uid in self.selected:
            self._layout(force=True)
            return
        after = event.x_root > target.winfo_rootx() + target.winfo_width() / 2
        self._move_selection(target.item.uid, after)

    def _card_at(self, x: int, y: int) -> Optional[ThumbCard]:
        widget = self.winfo_containing(x, y)
        while widget is not None and not isinstance(widget, ThumbCard):
            widget = getattr(widget, "master", None)
        return widget

    def _move_selection(self, target_uid: int, after: bool) -> None:
        self._remember()
        moving = [item for item in self.items if item.uid in self.selected]
        rest = [item for item in self.items if item.uid not in self.selected]
        position = next(index for index, item in enumerate(rest) if item.uid == target_uid) + (1 if after else 0)
        self.items = rest[:position] + moving + rest[position:]
        self._layout(force=True)

    def _select_all(self) -> None:
        self.selected = {item.uid for item in self.items}
        self._layout(force=True)

    # ------------------------------------------------------------------ ações
    def _remember(self) -> None:
        self._history.append(list(self.items))
        del self._history[:-_HISTORY_LIMIT]
        self._dirty = True

    def _require_selection(self) -> bool:
        if not self.selected:
            self._status("Selecione uma ou mais páginas (clique na miniatura).")
            return False
        return True

    def _rotate(self, delta: int) -> None:
        if not self._require_selection():
            return
        self._remember()
        self.items = [replace(item, ref=replace(item.ref, rotation=(item.ref.rotation + delta) % 360)) if item.uid in self.selected else item for item in self.items]
        self._sync_cards()

    def _duplicate(self) -> None:
        if not self._require_selection():
            return
        self._remember()
        result = []
        for item in self.items:
            result.append(item)
            if item.uid in self.selected:
                result.append(Item(next(_ids), item.ref))
        self.items = result
        self._sync_cards()

    def _insert_blank(self) -> None:
        self._remember()
        positions = [index for index, item in enumerate(self.items) if item.uid in self.selected]
        index = (max(positions) + 1) if positions else len(self.items)
        self.items.insert(index, Item(next(_ids), PageRef(0, 0, blank=True)))
        self._sync_cards()

    def _reverse(self) -> None:
        self._remember()
        self.items.reverse()
        self._layout(force=True)

    def _delete(self) -> None:
        if not self._require_selection():
            return
        self._remember()
        self.items = [item for item in self.items if item.uid not in self.selected]
        self.selected.clear()
        self._sync_cards()

    def on_key_delete(self) -> None:
        if self.selected:
            self._delete()

    def on_key_undo(self) -> None:
        self.undo()

    def undo(self) -> None:
        if self._history:
            self.items = self._history.pop()
            self._sync_cards()

    def run(self) -> None:
        self.save()

    def save(self) -> None:
        if not self.items or self.runner.running:
            self._status("Adicione páginas antes de salvar.")
            return
        first = self.sources[0] if self.sources else Path.home()
        name = filedialog.asksaveasfilename(
            parent=self, title="Salvar PDF", defaultextension=".pdf", filetypes=list(PDF_TYPES), initialdir=str(first.parent), initialfile=f"{first.stem}_organizado.pdf"
        )
        if not name:
            return
        refs = [item.ref for item in self.items]
        self.save_button.configure(state="disabled")
        self._status("Salvando…")
        self.runner.start(lambda job: assemble(job, list(self.sources), refs, Path(name)), on_success=self._saved, on_error=self._failed)

    def _saved(self, result) -> None:
        self._dirty = False
        self.save_button.configure(state="normal")
        target = result.files[0]
        self._status(f"Salvo: {target}")
        if messagebox.askyesno("PDF26", f"PDF salvo com {len(self.items)} páginas.\n\nAbrir a pasta?", parent=self):
            reveal(target)

    def _failed(self, error: BaseException) -> None:
        self.save_button.configure(state="normal")
        self._status("Falha ao salvar.")
        messagebox.showerror("PDF26", describe_error(error), parent=self)

    def _status(self, text: str) -> None:
        self.status.configure(text=text)

    def can_leave(self) -> bool:
        if self.runner.running:
            return False
        if self._dirty and self.items and not messagebox.askyesno("PDF26", "Sair sem salvar a montagem?", parent=self):
            return False
        for doc in self.docs:
            doc.close()
        return True
