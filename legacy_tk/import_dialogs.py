"""Import/reconcile selection dialogs for legacy Tk."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from core.hpd import FreqEntry, SystemNode
from legacy_tk.literals import (
    _LIT_BUTTON_1,
    _LIT_IMPORT_SELECTED,
    _LIT_TREE_HEADINGS,
)
from legacy_tk.rr_parsing import (
    classify_rr_tg_import_action,
    diff_cfreq_with_rr,
    diff_tgid_with_rr,
)


def _service_label(stype: int) -> str:
    from legacy_tk.scanner_manager import service_label as _fn

    return _fn(stype)


def _tgid_mode_label(canonical: str) -> str:
    from legacy_tk.scanner_manager import tgid_mode_label as _fn

    return _fn(canonical)

if TYPE_CHECKING:
    from legacy_tk.scanner_manager import ScannerManagerApp

class ConventionalImportSelectionDialog:
    """Select / reconcile conventional frequencies against RadioReference data."""

    CHECK_ON = "\u2611"
    CHECK_OFF = "\u2610"

    def __init__(
        self,
        app: "ScannerManagerApp",
        system: SystemNode,
        parsed: Dict[str, Any],
    ):
        self.app = app
        self.system = system
        self.parsed = parsed
        self.categories = parsed.get("categories") or []
        self.result: List[Tuple[str, List[Dict[str, Any]]]] = []
        self._item_meta: Dict[str, Dict[str, Any]] = {}

        self.update_mode_var = tk.BooleanVar(value=True)
        self.update_name_var = tk.BooleanVar(value=False)
        self.update_tone_var = tk.BooleanVar(value=True)
        self.update_service_var = tk.BooleanVar(value=False)

        self._existing_by_freq: Dict[int, FreqEntry] = {}
        for group in system.groups:
            for entry in group.entries:
                if entry.entry_type != "C-Freq":
                    continue
                try:
                    freq_hz = int(entry.record.get_field(5, ""))
                except ValueError:
                    continue
                if freq_hz <= 0:
                    continue
                self._existing_by_freq[freq_hz] = entry

        self.top = tk.Toplevel(app.root)
        self.top.title("Conventional Frequencies: Import / Reconcile")
        self.top.transient(app.root)
        self.top.geometry("1040x640")
        self.top.grab_set()

        header = ttk.Frame(self.top, padding=8)
        header.pack(fill=tk.X)
        source = parsed.get("title") or parsed.get("group_name") or "RadioReference"
        ttk.Label(
            header,
            text=(
                f"Source: {source}    Target system: '{system.name}'    "
                "Click a row to toggle. Existing entries compared against RR."
            ),
            wraplength=1000, justify=tk.LEFT,
        ).pack(side=tk.TOP, anchor=tk.W)

        policy = ttk.Frame(self.top, padding=(8, 0, 8, 0))
        policy.pack(fill=tk.X)
        ttk.Label(policy, text="Update fields on existing entries:").pack(side=tk.LEFT)
        ttk.Checkbutton(
            policy, text="Mode", variable=self.update_mode_var,
            command=self._on_policy_changed,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            policy, text="Tone", variable=self.update_tone_var,
            command=self._on_policy_changed,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            policy, text="Name (may overwrite user edits)",
            variable=self.update_name_var, command=self._on_policy_changed,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            policy, text="Service type (changes which scanner button plays this channel)",
            variable=self.update_service_var, command=self._on_policy_changed,
        ).pack(side=tk.LEFT, padx=4)

        tools = ttk.Frame(self.top, padding=(8, 0, 8, 0))
        tools.pack(fill=tk.X)
        ttk.Button(tools, text="Select New + Updates", command=self._on_select_new_and_updates).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(tools, text="Select Updates Only", command=self._on_select_updates_only).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(tools, text="Select All", command=self._on_select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(tools, text="Clear All", command=self._on_clear_all).pack(side=tk.LEFT, padx=2)
        self.summary_var = tk.StringVar()
        ttk.Label(tools, textvariable=self.summary_var, foreground="#333333").pack(side=tk.RIGHT)

        tree_frame = ttk.Frame(self.top, padding=8)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        columns = (
            "check", "action", "freq", "name", "mode", "tone",
            "tag", "service", "target_group", "crossref",
        )
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show=_LIT_TREE_HEADINGS, selectmode="browse"
        )
        self.tree.heading("#0", text="Category")
        self.tree.column("#0", width=200, stretch=False)
        for col, label, width, anchor in (
            ("check", "", 34, tk.CENTER),
            ("action", "Action", 160, tk.W),
            ("freq", "Freq MHz", 90, tk.E),
            ("name", "Name", 180, tk.W),
            ("mode", "Mode", 60, tk.CENTER),
            ("tone", "Tone", 110, tk.W),
            ("tag", "Tag", 110, tk.W),
            ("service", "Service", 110, tk.W),
            ("target_group", "Target Group", 180, tk.W),
            ("crossref", "Cross-ref", 200, tk.W),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.tag_configure("category", font=("TkDefaultFont", 9, "bold"))
        self.tree.tag_configure("update_available", foreground="#b8860b")
        self.tree.tag_configure("same", foreground="#808080")
        self.tree.tag_configure("crossref_callsign", background="#eaf5ff")
        self.tree.tag_configure("crossref_fuzzy", background="#fff8e1")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind(_LIT_BUTTON_1, self._on_click)

        footer = ttk.Frame(self.top, padding=8)
        footer.pack(fill=tk.X)
        ttk.Button(footer, text=_LIT_IMPORT_SELECTED, command=self._on_confirm).pack(side=tk.LEFT)
        ttk.Button(footer, text="Cancel", command=self.top.destroy).pack(side=tk.RIGHT)

        self._populate()
        self._refresh_summary()
        app.root.wait_window(self.top)

    def _filter_changes_by_policy(
        self, raw: Dict[str, Tuple[Any, Any]]
    ) -> Dict[str, Tuple[Any, Any]]:
        result: Dict[str, Tuple[Any, Any]] = {}
        if self.update_mode_var.get() and "mode" in raw:
            result["mode"] = raw["mode"]
        if self.update_tone_var.get() and "tone" in raw:
            result["tone"] = raw["tone"]
        if self.update_name_var.get() and "name" in raw:
            result["name"] = raw["name"]
        if self.update_service_var.get() and "service_type" in raw:
            result["service_type"] = raw["service_type"]
        return result

    def _target_group_name_for_existing(self, entry: FreqEntry) -> str:
        for sys_node in self.app.hpd.systems:
            for group in sys_node.groups:
                if entry in group.entries:
                    return group.name
        return "(existing)"

    def _populate(self):
        self._crossref_counts = {"callsign": 0, "fuzzy": 0}
        for cat in self.categories:
            cat_name = cat.get("name") or "Imported"
            cat_id = self.tree.insert(
                "", tk.END, text=cat_name,
                values=(self.CHECK_ON, "", "", "", "", "", "", "", "", ""),
                tags=("category",), open=True,
            )
            self._item_meta[cat_id] = {"type": "category"}
            for freq in cat.get("frequencies", []):
                try:
                    freq_hz = int(round(float(freq["mhz"]) * 1_000_000))
                except Exception:
                    continue
                existing = self._existing_by_freq.get(freq_hz)
                service = freq.get("suggested_service_type")
                raw_changes: Dict[str, Tuple[Any, Any]] = {}
                changes: Dict[str, Tuple[Any, Any]] = {}
                action = "new"
                if existing is not None:
                    raw_changes = diff_cfreq_with_rr(
                        existing.name,
                        existing.record.get_field(6, ""),
                        existing.record.get_field(7, ""),
                        existing.service_type,
                        freq.get("name") or freq.get("alpha") or "",
                        freq.get("mode") or "",
                        freq.get("tone") or "",
                        service if isinstance(service, int) else None,
                    )
                    changes = self._filter_changes_by_policy(raw_changes)
                    action = "update" if changes else "same"

                if action == "new":
                    checked = True
                    action_text = "New"
                    row_tags: Tuple[str, ...] = ()
                elif action == "update":
                    checked = True
                    change_text = ", ".join(
                        f"{k}: {changes[k][0]!r}→{changes[k][1]!r}" for k in sorted(changes)
                    )
                    action_text = f"Update ({change_text})"
                    row_tags = ("update_available",)
                else:
                    checked = False
                    action_text = "Same (skip)"
                    row_tags = ("same",)

                target_group = (
                    self._target_group_name_for_existing(existing)
                    if existing is not None else cat_name
                )
                service_text = _service_label(service) if isinstance(service, int) else ""
                hint = self.app.crossref_hint_for_rr_row(
                    freq, fallback_name=cat_name
                ) if existing is None else None
                crossref_text = hint["label"] if hint else ""
                if hint is not None:
                    kind = hint.get("kind")
                    if kind == "callsign":
                        self._crossref_counts["callsign"] += 1
                        row_tags = row_tags + ("crossref_callsign",)
                    elif kind == "fuzzy":
                        self._crossref_counts["fuzzy"] += 1
                        row_tags = row_tags + ("crossref_fuzzy",)
                iid = self.tree.insert(
                    cat_id, tk.END, text="",
                    values=(
                        self.CHECK_ON if checked else self.CHECK_OFF,
                        action_text,
                        f"{freq['mhz']:.4f}",
                        freq.get("name") or freq.get("alpha") or "",
                        freq.get("mode") or "",
                        freq.get("tone") or "",
                        freq.get("tag", ""),
                        service_text,
                        target_group,
                        crossref_text,
                    ),
                    tags=row_tags,
                )
                self._item_meta[iid] = {
                    "type": "cfreq",
                    "parent": cat_id,
                    "data": freq,
                    "freq_hz": freq_hz,
                    "checked": checked,
                    "action": action,
                    "changes": changes,
                    "raw_changes": raw_changes,
                    "existing": existing,
                    "crossref": hint,
                }
            self._refresh_category(cat_id)

    def _refresh_category(self, cat_id: str):
        children = self.tree.get_children(cat_id)
        if not children:
            self.tree.set(cat_id, "check", self.CHECK_OFF)
            return
        total = len(children)
        checked = sum(1 for c in children if self._item_meta[c].get("checked"))
        if checked == 0:
            mark = self.CHECK_OFF
        elif checked == total:
            mark = self.CHECK_ON
        else:
            mark = "\u25A3"
        self.tree.set(cat_id, "check", mark)

    def _refresh_summary(self):
        total = 0
        new_sel = 0
        update_sel = 0
        updates_available = 0
        for meta in self._item_meta.values():
            if meta.get("type") != "cfreq":
                continue
            total += 1
            if meta.get("action") == "update":
                updates_available += 1
            if meta.get("checked"):
                if meta.get("action") == "new":
                    new_sel += 1
                elif meta.get("action") == "update":
                    update_sel += 1
        xref = getattr(self, "_crossref_counts", {"callsign": 0, "fuzzy": 0})
        extra = ""
        if xref["callsign"] or xref["fuzzy"]:
            extra = f"   |  xref: {xref['callsign']} callsign, {xref['fuzzy']} fuzzy"
        self.summary_var.set(
            f"{total} frequencies; {new_sel} new, {update_sel}/{updates_available} updates"
            + extra
        )

    def _toggle_cfreq(self, iid: str, value: Optional[bool] = None):
        meta = self._item_meta[iid]
        if meta.get("type") != "cfreq":
            return
        new_val = value if value is not None else not meta.get("checked", False)
        meta["checked"] = new_val
        self.tree.set(iid, "check", self.CHECK_ON if new_val else self.CHECK_OFF)
        self._refresh_category(meta["parent"])
        self._refresh_summary()

    def _toggle_category(self, cat_id: str, value: Optional[bool] = None):
        children = self.tree.get_children(cat_id)
        if not children:
            return
        if value is None:
            current = self.tree.set(cat_id, "check")
            new_val = current != self.CHECK_ON
        else:
            new_val = value
        for c in children:
            self._toggle_cfreq(c, new_val)

    def _on_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        meta = self._item_meta.get(iid)
        if not meta:
            return
        if meta.get("type") == "category":
            self._toggle_category(iid)
        else:
            self._toggle_cfreq(iid)

    def _on_select_all(self):
        for iid, meta in self._item_meta.items():
            if meta.get("type") == "cfreq":
                self._toggle_cfreq(iid, True)

    def _on_select_new_and_updates(self):
        for iid, meta in self._item_meta.items():
            if meta.get("type") != "cfreq":
                continue
            self._toggle_cfreq(iid, meta.get("action") in ("new", "update"))

    def _on_select_updates_only(self):
        for iid, meta in self._item_meta.items():
            if meta.get("type") != "cfreq":
                continue
            self._toggle_cfreq(iid, meta.get("action") == "update")

    def _on_clear_all(self):
        for iid, meta in self._item_meta.items():
            if meta.get("type") == "cfreq":
                self._toggle_cfreq(iid, False)

    def _on_policy_changed(self):
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self._item_meta.clear()
        self._populate()
        self._refresh_summary()

    def _on_confirm(self):
        selection: List[Tuple[str, List[Dict[str, Any]]]] = []
        new_count = 0
        update_count = 0
        for cat_id in self.tree.get_children(""):
            cat_name = self.tree.item(cat_id, "text")
            items: List[Dict[str, Any]] = []
            for child in self.tree.get_children(cat_id):
                meta = self._item_meta[child]
                if not meta.get("checked"):
                    continue
                action = meta.get("action")
                if action not in ("new", "update"):
                    continue
                payload = dict(meta["data"])
                payload["__action__"] = action
                payload["__changes__"] = meta.get("changes", {})
                payload["__existing__"] = meta.get("existing")
                payload["__freq_hz__"] = meta.get("freq_hz")
                items.append(payload)
                if action == "new":
                    new_count += 1
                elif action == "update":
                    update_count += 1
            if items:
                selection.append((cat_name, items))
        if not selection:
            messagebox.showinfo("Import", "No frequencies selected.", parent=self.top)
            return
        if not messagebox.askyesno(
            _LIT_IMPORT_SELECTED,
            f"Add {new_count} new frequencies and update {update_count} existing "
            f"frequencies in '{self.system.name}'?",
            parent=self.top,
        ):
            return
        self.result = selection
        self.top.destroy()


class TrunkedImportSelectionDialog:
    """Dialog to review and check/uncheck talkgroups from a RadioReference trunk page."""

    CHECK_ON = "\u2611"
    CHECK_OFF = "\u2610"

    def __init__(
        self,
        app: "ScannerManagerApp",
        system: SystemNode,
        parsed: Dict[str, Any],
    ):
        self.app = app
        self.system = system
        self.parsed = parsed
        self.categories = parsed.get("categories") or []
        self.result: List[Tuple[str, List[Dict[str, Any]]]] = []
        self._item_meta: Dict[str, Dict[str, Any]] = {}

        # Default: only overwrite "mode" on existing entries. Name and service_type
        # are user customizations (reconciler-style): preserved unless opted in.
        self.update_mode_var = tk.BooleanVar(value=True)
        self.update_name_var = tk.BooleanVar(value=False)
        self.update_service_var = tk.BooleanVar(value=False)
        # Existing entries now reported as encrypted by RR are deleted from
        # the HPD by default (they're unscannable). User can override to
        # "skip" (leave as-is). We no longer offer an "avoid" path because
        # the BT885 doesn't honor avoid bits across power cycles.
        self.encrypted_policy_var = tk.StringVar(value="delete")
        # New encrypted TGs are excluded from the import by default. The
        # "force include" override is remembered per-system so users who
        # do want them (e.g., they're testing their own decoder) don't have
        # to tick the box every time.
        sys_key = system.system_id or system.name or ""
        include_map = app._app_settings.get("rr_import_include_encrypted") or {}
        self.include_encrypted_var = tk.BooleanVar(
            value=bool(include_map.get(sys_key, False))
        )

        self._existing_by_tgid: Dict[int, FreqEntry] = {}
        for group in system.groups:
            for entry in group.entries:
                if entry.entry_type != "TGID":
                    continue
                try:
                    tgid_val = int(entry.record.get_field(5, ""))
                except ValueError:
                    continue
                self._existing_by_tgid[tgid_val] = entry

        self.top = tk.Toplevel(app.root)
        self.top.title("Select Talkgroups to Import")
        self.top.transient(app.root)
        self.top.geometry("1020x620")
        self.top.grab_set()

        header = ttk.Frame(self.top, padding=8)
        header.pack(fill=tk.X)
        system_name = parsed.get("system_name", "RadioReference Trunk System")
        self.summary_var = tk.StringVar()
        ttk.Label(
            header,
            text=(
                f"Source: {system_name}    Target trunk: '{system.name}'    "
                "Click a row to toggle. Encrypted talkgroups are skipped by "
                "default - the BearTracker 885 can't play them."
            ),
            wraplength=980, justify=tk.LEFT,
        ).pack(side=tk.TOP, anchor=tk.W)

        policy = ttk.Frame(self.top, padding=(8, 0, 8, 0))
        policy.pack(fill=tk.X)
        ttk.Label(policy, text="Update fields on existing entries:").pack(side=tk.LEFT)
        ttk.Checkbutton(
            policy, text="Mode (lock ambiguous talkgroups to DIGITAL or ANALOG)",
            variable=self.update_mode_var, command=self._on_policy_changed,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            policy, text="Name (may overwrite user edits)",
            variable=self.update_name_var, command=self._on_policy_changed,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            policy, text="Service type (changes which scanner button plays this channel)",
            variable=self.update_service_var, command=self._on_policy_changed,
        ).pack(side=tk.LEFT, padx=4)

        policy2 = ttk.Frame(self.top, padding=(8, 0, 8, 0))
        policy2.pack(fill=tk.X)
        ttk.Label(
            policy2,
            text="Existing talkgroups RadioReference now lists as encrypted:",
        ).pack(side=tk.LEFT)
        for label, value in (
            ("Delete from HPD (default)", "delete"),
            ("Skip (leave as-is)", "skip"),
        ):
            ttk.Radiobutton(
                policy2, text=label, value=value,
                variable=self.encrypted_policy_var,
                command=self._on_policy_changed,
            ).pack(side=tk.LEFT, padx=4)

        policy3 = ttk.Frame(self.top, padding=(8, 0, 8, 0))
        policy3.pack(fill=tk.X)
        ttk.Checkbutton(
            policy3,
            text="Include encrypted talkgroups in new entries (not recommended)",
            variable=self.include_encrypted_var,
            command=self._on_policy_changed,
        ).pack(side=tk.LEFT)

        tools = ttk.Frame(self.top, padding=(8, 0, 8, 0))
        tools.pack(fill=tk.X)
        ttk.Button(tools, text="Select All Unencrypted", command=self._on_select_unencrypted).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(tools, text="Select Updates Only", command=self._on_select_updates_only).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(tools, text="Select All", command=self._on_select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(tools, text="Clear All", command=self._on_clear_all).pack(side=tk.LEFT, padx=2)
        ttk.Label(tools, textvariable=self.summary_var, foreground="#333333").pack(side=tk.RIGHT)

        tree_frame = ttk.Frame(self.top, padding=8)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("check", "action", "tgid", "name", "mode", "tag", "service", "crossref")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show=_LIT_TREE_HEADINGS, selectmode="browse"
        )
        self.tree.heading("#0", text="Category")
        self.tree.column("#0", width=220, stretch=False)
        for col, label, width, anchor in (
            ("check", "", 34, tk.CENTER),
            ("action", "Action", 130, tk.W),
            ("tgid", "TGID", 70, tk.E),
            ("name", "Name", 260, tk.W),
            ("mode", "Mode", 70, tk.CENTER),
            ("tag", "Tag", 130, tk.W),
            ("service", "Service", 130, tk.W),
            ("crossref", "Cross-ref", 180, tk.W),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.tag_configure("encrypted", foreground="#b22222")
        self.tree.tag_configure("encrypted_action", foreground="#8b0000", background="#fff5f5")
        self.tree.tag_configure("category", font=("TkDefaultFont", 9, "bold"))
        self.tree.tag_configure("update_available", foreground="#b8860b")
        self.tree.tag_configure("same", foreground="#808080")
        self.tree.tag_configure("crossref_callsign", background="#eaf5ff")
        self.tree.tag_configure("crossref_fuzzy", background="#fff8e1")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind(_LIT_BUTTON_1, self._on_click)

        footer = ttk.Frame(self.top, padding=8)
        footer.pack(fill=tk.X)
        ttk.Button(footer, text=_LIT_IMPORT_SELECTED, command=self._on_confirm).pack(side=tk.LEFT)
        ttk.Button(footer, text="Cancel", command=self.top.destroy).pack(side=tk.RIGHT)

        self._populate()
        self._refresh_summary()
        app.root.wait_window(self.top)

    def _populate(self):
        self._crossref_counts = {"callsign": 0, "fuzzy": 0}
        system_name_hint = (self.parsed.get("system_name") or "").strip()
        for cat in self.categories:
            cat_name = cat.get("name") or "Imported"
            cat_id = self.tree.insert(
                "", tk.END, text=cat_name, values=(self.CHECK_ON, "", "", "", "", "", "", ""),
                tags=("category",), open=True,
            )
            self._item_meta[cat_id] = {"type": "category"}
            for tg in cat.get("talkgroups", []):
                # Show RR's raw token alongside the HPD label so the user sees
                # e.g. "T → DIGITAL (D / T TDMA)" intent at a glance.
                rr_raw = (tg.get("mode_raw") or "").strip()
                hpd_mode = tg.get("mode") or ""
                hpd_label = _tgid_mode_label(hpd_mode) if hpd_mode else ""
                if rr_raw and hpd_label:
                    mode_text = f"{rr_raw} → {hpd_label}"
                else:
                    mode_text = hpd_label or rr_raw
                if tg.get("encrypted"):
                    mode_text = f"{mode_text} (enc)"
                service = tg.get("suggested_service_type")
                service_label_text = _service_label(service) if isinstance(service, int) else ""

                tgid_val = tg.get("tgid")
                existing = self._existing_by_tgid.get(int(tgid_val)) if tgid_val else None
                raw_changes: Dict[str, Tuple[Any, Any]] = {}
                changes: Dict[str, Tuple[Any, Any]] = {}
                if existing is not None:
                    raw_changes = diff_tgid_with_rr(
                        existing.name,
                        existing.record.get_field(6, ""),
                        existing.service_type,
                        tg.get("name") or tg.get("alpha") or "",
                        tg.get("mode") or "",
                        service if isinstance(service, int) else None,
                    )
                    changes = self._filter_changes_by_policy(raw_changes)
                action = classify_rr_tg_import_action(
                    is_encrypted=bool(tg.get("encrypted")),
                    has_existing=existing is not None,
                    has_update_diff=bool(changes),
                    encrypted_policy=self.encrypted_policy_var.get(),
                    include_encrypted=self.include_encrypted_var.get(),
                )

                if action == "new":
                    checked = True
                    action_text = "New"
                    row_tags: Tuple[str, ...] = ()
                elif action == "update":
                    checked = True
                    change_keys = sorted(changes.keys())
                    change_text = ", ".join(
                        f"{k}: {changes[k][0]!r}→{changes[k][1]!r}" for k in change_keys
                    )
                    action_text = f"Update ({change_text})"
                    row_tags = ("update_available",)
                elif action == "same":
                    checked = False
                    action_text = "Same (skip)"
                    row_tags = ("same",)
                elif action == "delete_encrypted":
                    checked = True
                    action_text = "Encrypted - DELETE"
                    row_tags = ("encrypted_action",)
                elif action == "same_encrypted":
                    checked = False
                    action_text = "Encrypted (skip, leave as-is)"
                    row_tags = ("encrypted",)
                else:
                    checked = False
                    action_text = "Encrypted (skip)"
                    row_tags = ("encrypted",)

                hint = self.app.crossref_hint_for_rr_row(
                    tg,
                    fallback_name=cat_name or system_name_hint,
                ) if existing is None else None
                crossref_text = hint["label"] if hint else ""
                if hint is not None:
                    kind = hint.get("kind")
                    if kind == "callsign":
                        self._crossref_counts["callsign"] += 1
                        row_tags = row_tags + ("crossref_callsign",)
                    elif kind == "fuzzy":
                        self._crossref_counts["fuzzy"] += 1
                        row_tags = row_tags + ("crossref_fuzzy",)
                iid = self.tree.insert(
                    cat_id, tk.END, text="",
                    values=(
                        self.CHECK_ON if checked else self.CHECK_OFF,
                        action_text,
                        tg["tgid"],
                        tg.get("name") or tg.get("alpha") or f"TGID {tg['tgid']}",
                        mode_text,
                        tg.get("tag", ""),
                        service_label_text,
                        crossref_text,
                    ),
                    tags=row_tags,
                )
                self._item_meta[iid] = {
                    "type": "tg",
                    "parent": cat_id,
                    "data": tg,
                    "checked": checked,
                    "action": action,
                    "changes": changes,
                    "raw_changes": raw_changes,
                    "existing": existing,
                    "crossref": hint,
                }
            self._refresh_category(cat_id)

    def _filter_changes_by_policy(
        self, raw: Dict[str, Tuple[Any, Any]]
    ) -> Dict[str, Tuple[Any, Any]]:
        result: Dict[str, Tuple[Any, Any]] = {}
        if self.update_mode_var.get() and "mode" in raw:
            result["mode"] = raw["mode"]
        if self.update_name_var.get() and "name" in raw:
            result["name"] = raw["name"]
        if self.update_service_var.get() and "service_type" in raw:
            result["service_type"] = raw["service_type"]
        return result

    def _on_policy_changed(self):
        # Rebuild the tree with the new policy applied to all rows.
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self._item_meta.clear()
        self._populate()
        self._refresh_summary()

    def _refresh_category(self, cat_id: str):
        children = self.tree.get_children(cat_id)
        if not children:
            self.tree.set(cat_id, "check", self.CHECK_OFF)
            return
        total = len(children)
        checked = sum(1 for c in children if self._item_meta[c].get("checked"))
        if checked == 0:
            mark = self.CHECK_OFF
        elif checked == total:
            mark = self.CHECK_ON
        else:
            mark = "\u25A3"
        self.tree.set(cat_id, "check", mark)

    def _refresh_summary(self):
        total = 0
        new_sel = 0
        update_sel = 0
        delete_sel = 0
        encrypted = 0
        updates_available = 0
        for meta in self._item_meta.values():
            if meta.get("type") != "tg":
                continue
            total += 1
            if meta["data"].get("encrypted"):
                encrypted += 1
            if meta.get("action") == "update":
                updates_available += 1
            if meta.get("checked"):
                action = meta.get("action")
                if action == "new":
                    new_sel += 1
                elif action == "update":
                    update_sel += 1
                elif action == "delete_encrypted":
                    delete_sel += 1
        xref = getattr(self, "_crossref_counts", {"callsign": 0, "fuzzy": 0})
        extra = ""
        if xref["callsign"] or xref["fuzzy"]:
            extra = f"   |  xref: {xref['callsign']} callsign, {xref['fuzzy']} fuzzy"
        self.summary_var.set(
            f"{total} talkgroups; {new_sel} new, {update_sel}/{updates_available} updates, "
            f"{delete_sel} delete-encrypted, "
            f"{encrypted} total encrypted"
            + extra
        )

    def _toggle_tg(self, iid: str, value: Optional[bool] = None):
        meta = self._item_meta[iid]
        if meta.get("type") != "tg":
            return
        new_val = value if value is not None else not meta.get("checked", False)
        meta["checked"] = new_val
        self.tree.set(iid, "check", self.CHECK_ON if new_val else self.CHECK_OFF)
        self._refresh_category(meta["parent"])
        self._refresh_summary()

    def _toggle_category(self, cat_id: str, value: Optional[bool] = None):
        children = self.tree.get_children(cat_id)
        if not children:
            return
        if value is None:
            current = self.tree.set(cat_id, "check")
            new_val = current != self.CHECK_ON
        else:
            new_val = value
        for c in children:
            self._toggle_tg(c, new_val)

    def _on_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        meta = self._item_meta.get(iid)
        if not meta:
            return
        if meta.get("type") == "category":
            self._toggle_category(iid)
        else:
            self._toggle_tg(iid)

    def _on_select_all(self):
        for iid, meta in self._item_meta.items():
            if meta.get("type") == "tg":
                self._toggle_tg(iid, True)

    def _on_select_unencrypted(self):
        for iid, meta in self._item_meta.items():
            if meta.get("type") != "tg":
                continue
            if meta["data"].get("encrypted", False):
                self._toggle_tg(iid, False)
            elif meta.get("action") in ("new", "update"):
                self._toggle_tg(iid, True)
            else:
                self._toggle_tg(iid, False)

    def _on_select_updates_only(self):
        for iid, meta in self._item_meta.items():
            if meta.get("type") != "tg":
                continue
            if meta.get("action") == "update" and not meta["data"].get("encrypted", False):
                self._toggle_tg(iid, True)
            else:
                self._toggle_tg(iid, False)

    def _on_clear_all(self):
        for iid, meta in self._item_meta.items():
            if meta.get("type") == "tg":
                self._toggle_tg(iid, False)

    def _on_confirm(self):
        selection: List[Tuple[str, List[Dict[str, Any]]]] = []
        new_count = 0
        update_count = 0
        delete_count = 0
        for cat_id in self.tree.get_children(""):
            cat_name = self.tree.item(cat_id, "text")
            items: List[Dict[str, Any]] = []
            for child in self.tree.get_children(cat_id):
                meta = self._item_meta[child]
                if not meta.get("checked"):
                    continue
                action = meta.get("action")
                if action not in ("new", "update", "delete_encrypted"):
                    continue
                payload = dict(meta["data"])
                payload["__action__"] = action
                payload["__changes__"] = meta.get("changes", {})
                payload["__existing__"] = meta.get("existing")
                items.append(payload)
                if action == "new":
                    new_count += 1
                elif action == "update":
                    update_count += 1
                elif action == "delete_encrypted":
                    delete_count += 1
            if items:
                selection.append((cat_name, items))
        if not selection:
            messagebox.showinfo(
                "Import", "No talkgroups selected.", parent=self.top
            )
            return
        summary_parts = []
        if new_count:
            summary_parts.append(f"{new_count} new")
        if update_count:
            summary_parts.append(f"{update_count} updates")
        if delete_count:
            summary_parts.append(f"{delete_count} DELETE encrypted")
        prompt = (
            "Proceed with:\n  " + "\n  ".join(summary_parts)
            + f"\nunder '{self.system.name}'?"
        )
        if delete_count:
            prompt += "\n\nDeletion is permanent once you Save."
        if not messagebox.askyesno(_LIT_IMPORT_SELECTED, prompt, parent=self.top):
            return
        # Persist the per-system "include encrypted" preference so the
        # next import for the same system remembers the user's choice.
        sys_key = self.system.system_id or self.system.name or ""
        if sys_key:
            include_map = self.app._app_settings.setdefault(
                "rr_import_include_encrypted", {}
            )
            include_map[sys_key] = bool(self.include_encrypted_var.get())
            try:
                self.app._save_app_settings()
            except Exception:
                pass
        self.result = selection
        self.top.destroy()


