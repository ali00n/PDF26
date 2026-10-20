"""Formulário gerado a partir das opções declaradas no catálogo (Choice, Number, Text, Flag, Color, FilePick, Signature)."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog
from typing import Any, Callable, Dict, Optional, Sequence

import customtkinter as ctk
from PIL import Image

from ...domain.tool import Choice, Color, FilePick, Flag, Number, Option, Signature, Text
from ...utils.exceptions import ValidationError
from .. import theme

_FIELD_WIDTH = 300


class OptionField:
    """Controle de uma opção: monta o widget, lê/escreve o valor e sinaliza erro."""

    def __init__(self, form: "OptionForm", option: Option, row: int):
        self.option = option
        self.frame = ctk.CTkFrame(form, fg_color="transparent")
        self.frame.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        self.frame.grid_columnconfigure(0, weight=1)
        self._on_change = form.refresh_visibility
        self.widget = self._build(option)
        if option.help:
            ctk.CTkLabel(self.frame, text=option.help, font=theme.font(11), text_color=theme.TEXT_MUTED, anchor="w", justify="left", wraplength=_FIELD_WIDTH).grid(
                row=3, column=0, sticky="w", pady=(2, 0)
            )

    # ------------------------------------------------------------------ construção
    def _label(self, text: str) -> None:
        ctk.CTkLabel(self.frame, text=text, font=theme.font(12, "bold"), text_color=theme.TEXT, anchor="w").grid(row=0, column=0, sticky="w", pady=(0, 4))

    def _build(self, option: Option):
        if isinstance(option, Flag):
            self.var = tk.BooleanVar(value=bool(option.default))
            box = ctk.CTkCheckBox(
                self.frame,
                text=option.label,
                variable=self.var,
                command=self._on_change,
                font=theme.font(12),
                text_color=theme.TEXT,
                fg_color=theme.ACCENT,
                hover_color=theme.ACCENT_HOVER,
                checkbox_width=20,
                checkbox_height=20,
            )
            box.grid(row=1, column=0, sticky="w")
            self.frame.grid_configure(pady=(0, 8))
            return box
        self._label(option.label)
        if isinstance(option, Choice):
            return self._build_choice(option)
        if isinstance(option, Number):
            return self._build_number(option)
        if isinstance(option, Text):
            return self._build_text(option)
        if isinstance(option, Color):
            return self._build_color(option)
        if isinstance(option, FilePick):
            return self._build_file(option)
        if isinstance(option, Signature):
            return self._build_signature()
        raise TypeError(f"Tipo de opção não suportado: {type(option).__name__}")

    def _build_choice(self, option: Choice):
        self._labels = {value: label for value, label in option.choices}
        self._values = {label: value for value, label in option.choices}
        self.var = tk.StringVar(value=self._labels.get(option.default, option.choices[0][1]))
        if option.segmented and len(option.choices) <= 6:
            widget = theme.segmented(self.frame, self._values, command=lambda _value: self._on_change(), variable=self.var)
            widget.grid(row=1, column=0, sticky="w")
        else:
            widget = ctk.CTkOptionMenu(
                self.frame,
                values=list(self._values),
                variable=self.var,
                command=lambda _value: self._on_change(),
                width=_FIELD_WIDTH,
                font=theme.font(12),
                dropdown_font=theme.font(12),
                fg_color=theme.SURFACE_ALT,
                button_color=theme.NEUTRAL_BUTTON_HOVER,
                button_hover_color=theme.BORDER,
                text_color=theme.TEXT,
                dynamic_resizing=False,
            )
            widget.grid(row=1, column=0, sticky="w")
        return widget

    def _build_number(self, option: Number):
        holder = ctk.CTkFrame(self.frame, fg_color="transparent")
        holder.grid(row=1, column=0, sticky="w")
        self.var = tk.StringVar(value=self._format_number(option.default))
        entry = ctk.CTkEntry(holder, textvariable=self.var, width=96, font=theme.font(12), justify="right")
        entry.pack(side="left")
        for symbol, delta in (("−", -option.step), ("+", option.step)):
            ctk.CTkButton(
                holder,
                text=symbol,
                width=28,
                height=28,
                font=theme.font(14, "bold"),
                fg_color=theme.NEUTRAL_BUTTON,
                hover_color=theme.NEUTRAL_BUTTON_HOVER,
                text_color=theme.TEXT,
                command=lambda d=delta: self._step(d),
            ).pack(side="left", padx=(4, 0))
        if option.unit:
            ctk.CTkLabel(holder, text=option.unit, font=theme.font(12), text_color=theme.TEXT_MUTED).pack(side="left", padx=(8, 0))
        return entry

    def _build_text(self, option: Text):
        if option.multiline:
            box = ctk.CTkTextbox(self.frame, height=option.height, font=theme.font(12), border_width=1, border_color=theme.BORDER, fg_color=theme.SURFACE_ALT, wrap="word")
            box.grid(row=1, column=0, sticky="ew")
            if option.default:
                box.insert("1.0", option.default)
            if option.placeholder and not option.default:
                self._placeholder_hint(option.placeholder)
            return box
        entry = ctk.CTkEntry(self.frame, placeholder_text=option.placeholder or None, show="•" if option.secret else "", width=_FIELD_WIDTH, font=theme.font(12))
        entry.grid(row=1, column=0, sticky="ew")
        theme.set_entry_text(entry, option.default or "")
        return entry

    def _placeholder_hint(self, text: str) -> None:
        ctk.CTkLabel(self.frame, text=f"Ex.: {text}".replace("\n", "  ·  "), font=theme.font(11), text_color=theme.TEXT_MUTED, anchor="w").grid(row=2, column=0, sticky="w", pady=(2, 0))

    def _build_color(self, option: Color):
        self.var = tk.StringVar(value=option.default or "#000000")
        button = ctk.CTkButton(self.frame, text=self.var.get().upper(), width=120, height=30, fg_color=self.var.get(), hover=False, border_width=1, border_color=theme.BORDER, command=self._pick_color)
        self._paint_color_button(button)
        button.grid(row=1, column=0, sticky="w")
        return button

    def _build_file(self, option: FilePick):
        holder = ctk.CTkFrame(self.frame, fg_color="transparent")
        holder.grid(row=1, column=0, sticky="ew")
        holder.grid_columnconfigure(0, weight=1)
        entry = ctk.CTkEntry(holder, placeholder_text="Nenhum arquivo selecionado", font=theme.font(12))
        entry.grid(row=0, column=0, sticky="ew")
        theme.set_entry_text(entry, option.default or "")
        theme.neutral_button(holder, "Escolher…", self._pick_file, width=90).grid(row=0, column=1, padx=(6, 0))
        return entry

    def _build_signature(self):
        self.var = tk.StringVar(value="")
        holder = ctk.CTkFrame(self.frame, fg_color=theme.SURFACE_ALT, corner_radius=8, border_width=1, border_color=theme.BORDER)
        holder.grid(row=1, column=0, sticky="ew")
        holder.grid_columnconfigure((0, 1, 2), weight=1)
        self._signature_preview = ctk.CTkLabel(holder, text="Nenhuma assinatura", height=72, font=theme.font(12), text_color=theme.TEXT_MUTED)
        self._signature_preview.grid(row=0, column=0, columnspan=3, sticky="ew", padx=8, pady=8)
        for column, (text, mode) in enumerate((("Desenhar", "draw"), ("Digitar", "type"), ("Imagem…", "image"))):
            theme.neutral_button(holder, text, lambda m=mode: self._pick_signature(m), width=92).grid(row=1, column=column, padx=4, pady=(0, 8))
        return holder

    # ------------------------------------------------------------------ interação
    def _format_number(self, value) -> str:
        if value is None:
            return ""
        return str(int(value)) if self.option.integer else f"{float(value):g}".replace(".", ",")

    def _step(self, delta: float) -> None:
        try:
            current = self._parse_number(self.var.get())
        except ValidationError:
            current = self.option.default or 0
        value = min(self.option.maximum, max(self.option.minimum, current + delta))
        self.var.set(self._format_number(value))

    def _parse_number(self, text: str) -> float:
        try:
            value = float(text.strip().replace(",", "."))
        except ValueError as error:
            raise ValidationError(f"'{self.option.label}': informe um número.", field=self.option.key) from error
        if not self.option.minimum <= value <= self.option.maximum:
            raise ValidationError(f"'{self.option.label}': use um valor entre {self._format_number(self.option.minimum)} e {self._format_number(self.option.maximum)}.", field=self.option.key)
        return int(value) if self.option.integer else value

    def _pick_color(self) -> None:
        _, hex_color = colorchooser.askcolor(color=self.var.get(), parent=self.frame, title=self.option.label)
        if hex_color:
            self.var.set(hex_color.upper())
            self._paint_color_button(self.widget)

    def _paint_color_button(self, button) -> None:
        value = self.var.get()
        red, green, blue = (int(value[i : i + 2], 16) for i in (1, 3, 5))
        light = red * 0.299 + green * 0.587 + blue * 0.114 > 150
        button.configure(text=value.upper(), fg_color=value, text_color="#111827" if light else "#FFFFFF")

    def _pick_file(self) -> None:
        name = filedialog.askopenfilename(parent=self.frame, title=self.option.label, filetypes=list(self.option.filetypes) + [("Todos os arquivos", "*.*")])
        if name:
            theme.set_entry_text(self.widget, name)

    def _pick_signature(self, mode: str) -> None:
        from ..dialogs.signature_pad import ask_signature

        path = ask_signature(self.frame.winfo_toplevel(), mode)
        if path:
            self.set(str(path))

    # ------------------------------------------------------------------ valor
    def get(self) -> Any:
        option = self.option
        if isinstance(option, Flag):
            return bool(self.var.get())
        if isinstance(option, Choice):
            return self._values[self.var.get()]
        if isinstance(option, Number):
            return self._parse_number(self.var.get())
        if isinstance(option, Text) and option.multiline:
            value = self.widget.get("1.0", "end-1c")
        elif isinstance(option, (Text, FilePick)):
            value = self.widget.get()
        else:
            value = self.var.get()
        if getattr(option, "required", False) and not str(value).strip():
            raise ValidationError(f"Preencha '{option.label}'.", field=option.key)
        return value

    def set(self, value: Any) -> None:
        option = self.option
        if isinstance(option, Flag):
            self.var.set(bool(value))
        elif isinstance(option, Choice):
            if value in self._labels:
                self.var.set(self._labels[value])
        elif isinstance(option, Number):
            self.var.set(self._format_number(value))
        elif isinstance(option, Text) and option.multiline:
            self.widget.delete("1.0", "end")
            self.widget.insert("1.0", value or "")
        elif isinstance(option, Signature):
            self.var.set(value or "")
            self._show_signature(Path(value) if value else None)
        elif isinstance(option, (Text, FilePick)):
            theme.set_entry_text(self.widget, value or "")
        else:
            self.var.set(value or "")
            self._paint_color_button(self.widget)

    def _show_signature(self, path: Optional[Path]) -> None:
        if not path or not path.exists():
            self._signature_preview.configure(image=None, text="Nenhuma assinatura")
            return
        with Image.open(path) as image:
            preview = image.copy()
        preview.thumbnail((280, 72))
        self._preview_image = ctk.CTkImage(light_image=preview, dark_image=preview, size=preview.size)
        self._signature_preview.configure(image=self._preview_image, text="")

    def flash_error(self) -> None:
        target = self.widget if hasattr(self.widget, "configure") else None
        try:
            target.configure(border_color=theme.DANGER)
            self.frame.after(1800, lambda: target.winfo_exists() and target.configure(border_color=theme.BORDER))
        except (ValueError, tk.TclError, AttributeError):
            pass

    def visible(self, visible: bool) -> None:
        if visible:
            self.frame.grid()
        else:
            self.frame.grid_remove()


class OptionForm(ctk.CTkFrame):
    """Monta os campos, aplica regras de visibilidade (`show_if`) e coleta os valores validados."""

    def __init__(self, master, options: Sequence[Option], on_change: Optional[Callable[[], None]] = None):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self._on_change = on_change
        self.fields: Dict[str, OptionField] = {}
        for row, option in enumerate(options):
            self.fields[option.key] = OptionField(self, option, row)
        self.refresh_visibility()

    def _raw(self, key: str) -> Any:
        try:
            return self.fields[key].get()
        except ValidationError:
            return None

    def refresh_visibility(self) -> None:
        for field in self.fields.values():
            condition = field.option.show_if
            field.visible(condition is None or self._raw(condition[0]) in condition[1])
        if self._on_change:
            self._on_change()

    def values(self) -> Dict[str, Any]:
        """Valores das opções visíveis; opções ocultas usam o valor padrão."""
        result = {}
        for key, field in self.fields.items():
            condition = field.option.show_if
            if condition and self._raw(condition[0]) not in condition[1]:
                result[key] = field.option.default
                continue
            try:
                result[key] = field.get()
            except ValidationError:
                field.flash_error()
                raise
        return result

    def set_values(self, values: Dict[str, Any]) -> None:
        for key, value in values.items():
            if key in self.fields:
                self.fields[key].set(value)
        self.refresh_visibility()
