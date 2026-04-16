from __future__ import annotations

import csv
import io
import json
import streamlit as st

from luminite.backup import LuminiteBackup


# ── CSV helpers ───────────────────────────────────────────────────────────────

def parse_scaletta_csv(text: str) -> list[dict]:
    """Parsa il CSV scaletta e restituisce lista di song con sezioni."""
    reader = csv.DictReader(io.StringIO(text))
    songs = []
    for row in reader:
        name = row.get("Nome Canzone", "").strip()
        if not name:
            continue
        sections: list[dict] = []
        for i in range(1, 7):
            sec_name   = row.get(f"Sezione {i} - Nome", "").strip()
            sec_preset = row.get(f"Sezione {i} - Preset+Scena", "").strip()
            if sec_preset and sec_preset not in ("-", ""):
                sections.append({"name": sec_name, "preset_scena": sec_preset})
        songs.append({"name": name, "sections": sections})
    return songs


def resolve_luminite_preset(preset_scena: str, presets) -> tuple[int | None, str]:
    """Cerca il preset Luminite che corrisponde a 'NomePreset - Scena'.
    Restituisce (preset_index, matched_name) o (None, "")."""
    if not preset_scena or preset_scena in ("-",):
        return 0, ""
    name_map = {p.name.strip(): p.index for p in presets if p.name.strip()}

    # 1. Match esatto
    if preset_scena in name_map:
        return name_map[preset_scena], preset_scena

    # 2. Match senza suffisso scena (prima dell'ultimo " - ")
    if " - " in preset_scena:
        base = preset_scena.rsplit(" - ", 1)[0].strip()
        if base in name_map:
            return name_map[base], base

    # 3. Match case-insensitive
    lower_map = {k.lower(): (v, k) for k, v in name_map.items()}
    if preset_scena.lower() in lower_map:
        v, k = lower_map[preset_scena.lower()]
        return v, k
    if " - " in preset_scena:
        base_l = preset_scena.rsplit(" - ", 1)[0].strip().lower()
        if base_l in lower_map:
            v, k = lower_map[base_l]
            return v, k

    return None, ""


def _is_default_song_name(name: str) -> bool:
    """True se il nome è un placeholder di default ('Song 1' … 'Song 120')."""
    import re as _re_local
    return bool(_re_local.fullmatch(r'Song \d{1,3}', name.strip()))


def write_setlist(backup: LuminiteBackup, name: str, song_indices: list[int],
                  target_idx: int | None = None) -> tuple[int | None, str]:
    """Scrive una setlist nel backup.
    Se target_idx è fornito usa quello slot.
    Altrimenti cerca slot per nome o primo con song_ids vuoti.
    Verifica che lo slot rientri nell'area fisicamente allocata."""
    all_sl = backup.parse_setlists()
    lo     = backup.layout
    # Numero massimo di setlist slot-map fisicamente presenti nel file
    slot_bytes      = lo.setlist_slots_per_list * 4
    max_slot_maps   = max(0, (lo.exp_base - lo.setlist_slots_base) // slot_bytes)

    if target_idx is not None:
        sl_idx = target_idx
    else:
        by_name = {sl.name.strip(): sl.index for sl in all_sl}
        if name in by_name:
            sl_idx = by_name[name]
        else:
            free = [sl for sl in all_sl if not sl.song_ids]
            if not free:
                return None, "Nessuno slot setlist disponibile (tutti occupati)."
            sl_idx = free[0].index

    # Guardia overflow: scrivi la slot-map solo se rientra nell'area allocata
    if sl_idx > max_slot_maps:
        return None, (f"Slot setlist {sl_idx} fuori dall'area allocata "
                      f"(max {max_slot_maps}). Scegli uno slot da 1 a {max_slot_maps}.")

    off = lo.setlist_base + (sl_idx - 1) * lo.setlist_stride
    enc = name.encode("ascii", errors="ignore")[: lo.setlist_name_size - 1]
    backup._data[off: off + lo.setlist_name_size] = enc + b"\x00" * (lo.setlist_name_size - len(enc))
    backup.set_setlist_song_ids(sl_idx, song_indices[: lo.setlist_slots_per_list])
    return sl_idx, ""


def write_song_name(backup: LuminiteBackup, song_index: int, name: str) -> None:
    lo  = backup.layout
    off = lo.song_base + (song_index - 1) * lo.song_stride
    enc = name.encode("ascii", errors="ignore")[: lo.song_name_size - 1]
    backup._data[off: off + lo.song_name_size] = enc + b"\x00" * (lo.song_name_size - len(enc))

st.set_page_config(page_title="Luminite Setlist Maker", layout="wide", page_icon="🎸")

# ── Costanti ──────────────────────────────────────────────────────────────────

POSITIONS   = ["A", "B", "C", "D", "E", "F", "G", "H"]
SCENES      = ["A", "B", "C", "D", "E", "F", "G", "H"]
SLOT_LABELS = ["FS-A", "FS-B", "FS-C", "FS-D", "FS-E", "FS-F", "FS-G", "FS-H", "EC1", "EC2"]
MAX_BANKS   = 32   # 32 bank × 8 posizioni (A-H) = 256 preset per setlist

# ── Libreria comandi utility QC ───────────────────────────────────────────────
# Ogni voce: (label, cc_number, value)  — value=None → slider 0-127
# Raggruppate per categoria

QC_UTILITY: dict[str, list[tuple[str, int, int | None]]] = {
    "🦶 Footswitch": [
        ("Footswitch A – Enable",  35, 127),
        ("Footswitch A – Bypass",  35, 0),
        ("Footswitch B – Enable",  36, 127),
        ("Footswitch B – Bypass",  36, 0),
        ("Footswitch C – Enable",  37, 127),
        ("Footswitch C – Bypass",  37, 0),
        ("Footswitch D – Enable",  38, 127),
        ("Footswitch D – Bypass",  38, 0),
        ("Footswitch E – Enable",  39, 127),
        ("Footswitch E – Bypass",  39, 0),
        ("Footswitch F – Enable",  40, 127),
        ("Footswitch F – Bypass",  40, 0),
        ("Footswitch G – Enable",  41, 127),
        ("Footswitch G – Bypass",  41, 0),
        ("Footswitch H – Enable",  42, 127),
        ("Footswitch H – Bypass",  42, 0),
    ],
    "🎬 Scena / Modalità": [
        ("Scene A",          43, 0),
        ("Scene B",          43, 1),
        ("Scene C",          43, 2),
        ("Scene D",          43, 3),
        ("Scene E",          43, 4),
        ("Scene F",          43, 5),
        ("Scene G",          43, 6),
        ("Scene H",          43, 7),
        ("Mode → Preset",    47, 0),
        ("Mode → Scene",     47, 1),
        ("Mode → Stomp",     47, 2),
    ],
    "🔧 Utility": [
        ("Tuner ON",                45, 127),
        ("Tuner OFF",               45, 0),
        ("Gig View ON",             46, 127),
        ("Gig View OFF",            46, 0),
        ("Tempo BPM",               44, None),   # valore custom
        ("Bank / Setlist change",   32, None),   # valore custom
        ("Ignora PC duplicati ON",  62, 127),
        ("Ignora PC duplicati OFF", 62, 0),
        ("Expression Pedal 1",      1,  None),
        ("Expression Pedal 2",      2,  None),
    ],
    "🔁 Looper X": [
        ("Looper X – Apri",                    48, 127),
        ("Looper X – Chiudi",                  48, 0),
        ("Looper X – Duplicate / Stop",        49, 127),
        ("Looper X – One Shot ON/OFF",         50, 127),
        ("Looper X – Half Speed ON/OFF",       51, 127),
        ("Looper X – Punch In/Out",            52, 127),
        ("Looper X – Punch Out",               52, 0),
        ("Looper X – Record / Overdub / Stop", 53, 127),
        ("Looper X – Stop Recording",          53, 0),
        ("Looper X – Play / Stop",             54, 127),
        ("Looper X – Reverse ON/OFF",          55, 127),
        ("Looper X – Undo / Redo",             56, 127),
        ("Looper X – Dup.Mode Free",           57, 0),
        ("Looper X – Dup.Mode Sync",           57, 1),
        ("Looper X – Quantize OFF",            58, 0),
        ("Looper X – MIDI Clock OFF",          59, 0),
        ("Looper X – MIDI Clock ON",           59, 1),
        ("Looper X – Perform Mode",            60, 0),
        ("Looper X – Params Mode",             60, 1),
    ],
}


# ── CSV preset parser ─────────────────────────────────────────────────────────

import re as _re

def parse_preset_scena_field(field: str) -> tuple[int, str, str] | None:
    """Parsa '1C Base - B' → (bank=1, pos='C', scene='B').
    Formato: <numero><lettera_pos> <qualsiasi> - <lettera_scena>
    Restituisce None se il formato non è riconoscibile."""
    field = field.strip()
    m = _re.match(r'^(\d+)([A-Ha-h])\s+.*-\s*([A-Ha-h])\s*$', field)
    if m:
        bank  = int(m.group(1))
        pos   = m.group(2).upper()
        scene = m.group(3).upper()
        return bank, pos, scene
    # fallback: prova senza testo intermedio es. "1C - B"
    m2 = _re.match(r'^(\d+)([A-Ha-h])\s*-\s*([A-Ha-h])\s*$', field)
    if m2:
        return int(m2.group(1)), m2.group(2).upper(), m2.group(3).upper()
    return None


def parse_csv_presets(text: str) -> list[dict]:
    """Estrae preset unici dal CSV.
    Per ogni riga e ogni N (1-6) legge:
      - 'Sezione N - Nome'        → nome del preset Luminite
      - 'Sezione N - Preset+Scena' → es. '1C Base - B'
    Restituisce lista di {name, raw_field, bank, pos, scene} deduplicata per nome.
    """
    reader = csv.DictReader(io.StringIO(text))
    seen: dict[str, dict] = {}   # nome → entry
    for row in reader:
        for i in range(1, 7):
            lum_name  = row.get(f"Sezione {i} - Nome", "").strip()
            raw_field = row.get(f"Sezione {i} - Preset+Scena", "").strip()
            if not lum_name or not raw_field or raw_field in ("-", ""):
                continue
            if lum_name in seen:
                continue   # già trovato, salta duplicato
            parsed = parse_preset_scena_field(raw_field)
            if parsed is None:
                continue
            bank, pos, scene = parsed
            seen[lum_name] = {
                "name":      lum_name,
                "raw_field": raw_field,
                "bank":      bank,
                "pos":       pos,
                "scene":     scene,
            }
    return list(seen.values())


# ── Helpers MIDI ──────────────────────────────────────────────────────────────

def calc_qc_midi(setlist_idx: int, bank: int, pos: str, scene: str) -> dict:
    pc_zero = (bank - 1) * len(POSITIONS) + POSITIONS.index(pos)
    return {
        "cc0":  0 if pc_zero < 128 else 1,
        "cc32": setlist_idx,
        "pc":   pc_zero % 128,
        "cc43": SCENES.index(scene),
    }


def apply_preset_command(backup: LuminiteBackup, slot: int, midi: dict) -> None:
    """Scrive 4 comandi MIDI (preset recall) in uno slot Luminite."""
    lo  = backup.layout
    pay = lo.preset_base + (slot - 1) * lo.preset_stride + lo.preset_name_size

    def w(i: int, st_: int, d1: int, d2: int) -> None:
        b = pay + i * 4
        backup._data[b:b + 4] = bytes([st_ & 0xFF, d1 & 0x7F, d2 & 0x7F, 0x01])

    w(0, 0xB0, 0x00, midi["cc0"])
    w(1, 0xB0, 0x20, midi["cc32"])
    w(2, 0xC0, midi["pc"],  0x00)
    w(3, 0xB0, 0x2B, midi["cc43"])
    max_cmds = (lo.preset_stride - lo.preset_name_size) // 4
    for i in range(4, max_cmds):
        b = pay + i * 4
        backup._data[b:b + 4] = bytes([0xB0, 0x00, 0x00, 0x01])


def apply_cc_command(backup: LuminiteBackup, slot: int, cc: int, value: int) -> None:
    """Scrive 1 comando CC in uno slot Luminite (azzerando il resto)."""
    lo  = backup.layout
    pay = lo.preset_base + (slot - 1) * lo.preset_stride + lo.preset_name_size
    backup._data[pay:pay + 4] = bytes([0xB0, cc & 0x7F, value & 0x7F, 0x01])
    max_cmds = (lo.preset_stride - lo.preset_name_size) // 4
    for i in range(1, max_cmds):
        b = pay + i * 4
        backup._data[b:b + 4] = bytes([0xB0, 0x00, 0x00, 0x01])


def write_preset_name(backup: LuminiteBackup, slot: int, name: str) -> None:
    lo  = backup.layout
    off = lo.preset_base + (slot - 1) * lo.preset_stride
    enc = name.encode("ascii", errors="ignore")[: lo.preset_name_size - 1]
    backup._data[off: off + lo.preset_name_size] = enc + b"\x00" * (lo.preset_name_size - len(enc))


# ── Session state ─────────────────────────────────────────────────────────────

for _k, _v in {"backup": None, "last_filename": None,
               "original_bytes": None,
               "qc_setlists": [], "staged": None,
               "rename_slot": None, "lib_csv_done": None,
               "preset_v": 0, "songs_v": 0}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── Header ────────────────────────────────────────────────────────────────────

st.title("🎸 Luminite Setlist Maker")
uploaded = st.file_uploader("Carica il file .bak Luminite", type=["bak"],
                             label_visibility="collapsed")
if uploaded and uploaded.name != st.session_state.last_filename:
    raw = uploaded.getvalue()
    st.session_state.original_bytes = raw
    st.session_state.backup         = LuminiteBackup.from_bytes(raw)
    st.session_state.last_filename  = uploaded.name

if st.session_state.backup is None:
    st.info("👆 Carica un file .bak per iniziare.")
    st.stop()

backup: LuminiteBackup = st.session_state.backup
col_info, col_discard = st.columns([6, 2])
col_info.caption(f"File: **{st.session_state.last_filename}** — {backup.size:,} byte")
if col_discard.button("🔄 Scarta modifiche", use_container_width=True,
                       help="Ripristina il backup all'originale caricato",
                       key="discard_changes"):
    st.session_state.backup = LuminiteBackup.from_bytes(st.session_state.original_bytes)
    st.session_state.staged = None
    st.session_state.rename_slot = None
    st.session_state.preset_v += 1
    st.session_state.songs_v += 1
    st.rerun()
st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_lib, tab_csv, tab_songs, tab_setlists, tab_export = st.tabs([
    "🗂️  QC Library",
    "📥  Scaletta CSV",
    "🎵  Songs",
    "📋  Setlists",
    "💾  Esporta",
])

# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — QC LIBRARY
# ═════════════════════════════════════════════════════════════════════════════

with tab_lib:
    left, right = st.columns([1, 2], gap="large")

    # ─────────────────────────────────────────────────────────────────────────
    # SINISTRA — Picker comandi QC (Preset + Utility)
    # ─────────────────────────────────────────────────────────────────────────
    with left:
        st.markdown("### 🎛️ Comandi QC")
        st.caption("Scegli un comando, poi clicca **Seleziona** e assegnalo a uno slot Luminite a destra.")

        # Banner feedback generazione CSV
        if st.session_state.get("lib_csv_done") is not None:
            st.success(f"✅ {st.session_state.lib_csv_done} preset scritti nel backup. Vai su **💾 Esporta**.")
            if st.button("✖ Chiudi", key="close_csv_done"):
                st.session_state.lib_csv_done = None
                st.rerun()

        lib_tab_preset, lib_tab_utility = st.tabs(["🎸 Preset QC", "🔧 Utility / CC"])

        # ── Tab Preset QC ─────────────────────────────────────────────────────
        with lib_tab_preset:
            with st.expander("⚙️ Le mie setlist QC", expanded=not st.session_state.qc_setlists):
                with st.form("form_sl", clear_on_submit=True):
                    sl_name = st.text_input("Nome setlist", placeholder="es. Cantautorato")
                    sl_idx  = st.number_input("Indice QC", min_value=0, max_value=12, value=2, step=1,
                                              help="0=Factory · 1=My Presets · 2-12=Setlist utente")
                    if st.form_submit_button("Aggiungi setlist"):
                        if sl_name.strip():
                            if any(s["idx"] == int(sl_idx) for s in st.session_state.qc_setlists):
                                st.error(f"Indice {int(sl_idx)} già usato.")
                            elif len(st.session_state.qc_setlists) >= 10:
                                st.error("Massimo 10 setlist.")
                            else:
                                st.session_state.qc_setlists.append(
                                    {"name": sl_name.strip(), "idx": int(sl_idx)})
                                st.rerun()
                to_del = None
                for i, sl in enumerate(st.session_state.qc_setlists):
                    ca, cb = st.columns([5, 1])
                    ca.markdown(f"**{sl['name']}** · indice `{sl['idx']}`")
                    if cb.button("🗑", key=f"del_sl_{i}"):
                        to_del = i
                if to_del is not None:
                    st.session_state.qc_setlists.pop(to_del)
                    st.rerun()

            if not st.session_state.qc_setlists:
                st.info("Aggiungi almeno una setlist QC.")
            else:
                sl_map      = {s["name"]: s["idx"] for s in st.session_state.qc_setlists}
                sel_sl_name = st.selectbox("Setlist", list(sl_map.keys()), key="lib_sl")
                sel_sl_idx  = sl_map[sel_sl_name]

                c1, c2 = st.columns(2)
                sel_bank  = c1.number_input("Bank", min_value=1, max_value=MAX_BANKS,
                                             value=1, step=1, key="lib_bank")
                sel_pos   = c2.radio("Posizione", POSITIONS, horizontal=True, key="lib_pos")
                sel_scene = st.radio("Scena", SCENES, horizontal=True, key="lib_scene")

                midi = calc_qc_midi(sel_sl_idx, int(sel_bank), sel_pos, sel_scene)
                st.markdown(
                    f"**MIDI:** `CC#0={midi['cc0']}` · `CC#32={midi['cc32']}` · "
                    f"`PC={midi['pc']}` · `CC#43={midi['cc43']}`"
                )

                if st.button("☝️ Seleziona questo preset", use_container_width=True,
                              type="primary", key="sel_preset_btn"):
                    st.session_state.staged = {
                        "type":      "preset",
                        "midi":      midi,
                        "auto_name": f"{sel_sl_name} {int(sel_bank)}{sel_pos} sc.{sel_scene}",
                        "desc":      f"{sel_sl_name} · Bank {int(sel_bank)}{sel_pos} · Scena {sel_scene}",
                    }
                    st.rerun()

        # ── Tab Utility / CC ──────────────────────────────────────────────────
        with lib_tab_utility:
            cat = st.selectbox("Categoria", list(QC_UTILITY.keys()), key="util_cat")
            commands = QC_UTILITY[cat]
            cmd_labels = [c[0] for c in commands]
            sel_cmd_label = st.selectbox("Comando", cmd_labels, key="util_cmd")
            sel_cmd = next(c for c in commands if c[0] == sel_cmd_label)
            _, cc_num, fixed_val = sel_cmd

            if fixed_val is None:
                cc_val = st.slider("Valore (0–127)", 0, 127, 64, key="util_val")
            else:
                cc_val = fixed_val
                st.markdown(f"Valore fisso: **{cc_val}**")

            st.markdown(f"**MIDI:** `CC#{cc_num} = {cc_val}`")

            if st.button("☝️ Seleziona questo comando", use_container_width=True,
                          type="primary", key="sel_util_btn"):
                st.session_state.staged = {
                    "type":      "cc",
                    "cc":        cc_num,
                    "value":     cc_val,
                    "auto_name": sel_cmd_label[:13],
                    "desc":      f"CC#{cc_num} = {cc_val} · {sel_cmd_label}",
                }
                st.rerun()

        # ── Comando in mano ───────────────────────────────────────────────────
        st.divider()
        if st.session_state.staged:
            s = st.session_state.staged
            st.success(f"**In mano:** {s['desc']}")
            if st.button("✖ Deseleziona", use_container_width=True, key="desel"):
                st.session_state.staged = None
                st.rerun()
        else:
            st.info("Nessun comando selezionato.")

        # ── Importa libreria da CSV ───────────────────────────────────────────
        st.divider()
        st.markdown("#### 📥 Importa preset da CSV")
        st.caption(
            "Legge le colonne **Sezione N - Nome** (nome preset Luminite) e "
            "**Sezione N - Preset+Scena** (es. `1C Base - B`) per generare "
            "automaticamente i preset Luminite. Usa la setlist QC selezionata sopra."
        )

        lib_csv_file = st.file_uploader("CSV scaletta", type=["csv"],
                                         key="lib_csv_upload", label_visibility="collapsed")

        if lib_csv_file:
            lib_raw = lib_csv_file.read().decode("utf-8", errors="ignore")
            csv_items = parse_csv_presets(lib_raw)

            if not csv_items:
                st.warning("Nessun preset riconoscibile nel CSV (controlla il formato delle colonne).")
            else:
                st.markdown(f"**{len(csv_items)} preset** trovati nel CSV")

                # Controlla che ci sia una setlist selezionata
                if not st.session_state.qc_setlists:
                    st.error("⚠️ Aggiungi prima almeno una setlist QC (Step 1 qui sopra) — serve per calcolare CC#32.")
                else:
                    sl_map_now = {s["name"]: s["idx"] for s in st.session_state.qc_setlists}
                    sel_sl_for_csv = st.selectbox(
                        "Setlist QC per questi preset",
                        list(sl_map_now.keys()),
                        key="lib_csv_sl"
                    )
                    sl_idx_for_csv = sl_map_now[sel_sl_for_csv]

                    # ── Slot di partenza ──────────────────────────────────────
                    start_slot = st.number_input(
                        "Slot Luminite di partenza",
                        min_value=1,
                        max_value=backup.layout.preset_count,
                        value=1,
                        step=1,
                        key="lib_csv_start_slot",
                        help="I preset verranno scritti in sequenza da questo slot in poi, sovrascrivendo il contenuto esistente."
                    )
                    end_slot = start_slot + len(csv_items) - 1
                    if end_slot > backup.layout.preset_count:
                        st.warning(f"⚠️ Slot {start_slot}–{backup.layout.preset_count}: non bastano slot per tutti i {len(csv_items)} preset.")
                    else:
                        st.caption(f"Scriverà gli slot **{int(start_slot)}** → **{end_slot}**")

                    # Tabella preview
                    hdr = st.columns([3, 2, 1, 1, 1, 2])
                    hdr[0].markdown("**Nome Luminite**")
                    hdr[1].markdown("**Campo CSV**")
                    hdr[2].markdown("**Bank**")
                    hdr[3].markdown("**Pos**")
                    hdr[4].markdown("**Scena**")
                    hdr[5].markdown("**MIDI**")
                    st.divider()
                    for item in csv_items:
                        midi = calc_qc_midi(sl_idx_for_csv, item["bank"], item["pos"], item["scene"])
                        r = st.columns([3, 2, 1, 1, 1, 2])
                        r[0].markdown(f"`{item['name']}`")
                        r[1].markdown(f"*{item['raw_field']}*")
                        r[2].markdown(str(item["bank"]))
                        r[3].markdown(item["pos"])
                        r[4].markdown(item["scene"])
                        r[5].caption(
                            f"CC0={midi['cc0']} CC32={midi['cc32']} "
                            f"PC={midi['pc']} CC43={midi['cc43']}"
                        )

                    st.divider()

                    if st.button(
                        f"⚡ Genera libreria — {len(csv_items)} preset da slot {int(start_slot)}",
                        use_container_width=True, type="primary", key="gen_lib_csv"
                    ):
                        errs: list[str] = []
                        done = 0
                        for i, item in enumerate(csv_items):
                            slot_idx = int(start_slot) + i
                            if slot_idx > backup.layout.preset_count:
                                errs.append(f"Slot {slot_idx} fuori range — '{item['name']}' non scritto.")
                                continue
                            midi = calc_qc_midi(sl_idx_for_csv, item["bank"], item["pos"], item["scene"])
                            apply_preset_command(backup, slot_idx, midi)
                            write_preset_name(backup, slot_idx, item["name"])
                            done += 1
                        for e in errs:
                            st.error(e)
                        if done:
                            st.session_state.preset_v += 1
                            st.rerun()
                        else:
                            st.warning("⚠️ Nessun preset scritto.")

    # ─────────────────────────────────────────────────────────────────────────
    # DESTRA — 120 preset Luminite con nome editabile
    # ─────────────────────────────────────────────────────────────────────────
    with right:
        st.markdown("### 🎚️ Preset Luminite")
        staged = st.session_state.staged

        if staged:
            st.info(f"**Comando in mano:** {staged['desc']} — clicca **Assegna** sullo slot che vuoi.")
        else:
            st.caption("Seleziona un comando a sinistra, poi clicca **Assegna** sullo slot Luminite.")

        all_lum  = backup.parse_presets()
        show_all = st.toggle("Mostra tutti i 120 slot", value=False, key="show_all_lum")
        visible  = all_lum if show_all else [p for p in all_lum if p.name.strip()]

        if not visible:
            st.info("Nessun preset con nome trovato. Attiva il toggle per vedere tutti i 120 slot.")
        else:
            hc = st.columns([1, 4, 2])
            hc[0].markdown("**Slot**")
            hc[1].markdown("**Nome preset Luminite**")
            hc[2].markdown("")
            st.divider()

            pv = st.session_state.preset_v   # version token per forzare re-render widget

            for lp in visible:
                is_rename = (st.session_state.rename_slot == lp.index)

                # ── Modalità rinomina (dopo assegnazione preset QC) ──────────
                if is_rename:
                    c0, c1, c2 = st.columns([1, 4, 2])
                    c0.markdown(f"**{lp.index}**")
                    new_name = c1.text_input(
                        f"rename_{lp.index}",
                        value=lp.name,
                        label_visibility="collapsed",
                        key=f"renfield_{lp.index}_v{pv}",
                    )
                    if c2.button("💾 Salva nome", key=f"savename_{lp.index}_v{pv}",
                                  use_container_width=True, type="primary"):
                        write_preset_name(backup, lp.index, new_name.strip() or lp.name)
                        st.session_state.rename_slot = None
                        st.session_state.preset_v += 1
                        st.rerun()
                    c0.success("✏️")   # indicatore visivo dello slot attivo

                # ── Modalità assegnazione (comando in mano) ──────────────────
                elif staged:
                    c0, c1, c2 = st.columns([1, 4, 2])
                    c0.markdown(f"**{lp.index}**")
                    c1.markdown(lp.name if lp.name.strip() else "*vuoto*")

                    if c2.button("✅ Assegna", key=f"assign_{lp.index}_v{pv}",
                                  use_container_width=True):
                        if staged["type"] == "preset":
                            apply_preset_command(backup, lp.index, staged["midi"])
                            write_preset_name(backup, lp.index, staged["auto_name"])
                            st.session_state.staged      = None
                            st.session_state.rename_slot = lp.index
                        else:
                            apply_cc_command(backup, lp.index, staged["cc"], staged["value"])
                            write_preset_name(backup, lp.index, staged["auto_name"])
                            st.session_state.staged = None
                        st.session_state.preset_v += 1
                        st.rerun()

                # ── Modalità normale (solo rinomina manuale) ─────────────────
                else:
                    c0, c1, c2 = st.columns([1, 4, 2])
                    c0.markdown(f"**{lp.index}**")
                    new_name = c1.text_input(
                        f"n{lp.index}",
                        value=lp.name if lp.name.strip() else "",
                        placeholder="(vuoto)",
                        label_visibility="collapsed",
                        key=f"name_{lp.index}_v{pv}",
                    )
                    if c2.button("💾", key=f"ren_{lp.index}_v{pv}", use_container_width=True,
                                  help="Salva nome"):
                        if new_name.strip():
                            write_preset_name(backup, lp.index, new_name.strip())
                            st.session_state.preset_v += 1
                            st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — SCALETTA CSV
# ═════════════════════════════════════════════════════════════════════════════

with tab_csv:
    st.subheader("Importa Scaletta da CSV")
    
    csv_mode = st.radio(
        "Modalità",
        ["📋 Solo songs (preset già esistono nel backup)",
         "⚡ Songs + genera preset Luminite vuoti"],
        horizontal=False,
        key="csv_mode"
    )
    
    st.caption(
        "Carica il CSV con le song e le sezioni. Formato colonne: "
        "**Nome Canzone · Sezione N - Nome · Sezione N - Preset+Scena** (fino a 6 sezioni)."
    )
    
    if csv_mode == "📋 Solo songs (preset già esistono nel backup)":
        st.info("Importa solo i nomi delle canzoni dalla colonna Nome Canzone (salta il primo elemento). Crea le songs nel backup con slot vuoti.")
    else:
        st.info("Per ogni sezione (Sezione N - Nome), cerca un preset Luminite con lo stesso nome. Se trovato lo assegna allo slot corrispondente. Se non trovato, lo slot rimane vuoto.")

    csv_file = st.file_uploader("Carica CSV scaletta", type=["csv"], key="csv_upload")

    if csv_file:
        raw_text = csv_file.read().decode("utf-8", errors="ignore")

        # ── Modalità "Solo songs" ─────────────────────────────────────────────
        if csv_mode == "📋 Solo songs (preset già esistono nel backup)":
            # Legge solo la colonna Nome Canzone, salta il primo elemento
            reader = csv.reader(io.StringIO(raw_text))
            all_rows = list(reader)

            # Determina la colonna "Nome Canzone"
            if not all_rows:
                st.warning("CSV vuoto.")
                st.stop()

            header = all_rows[0]
            try:
                col_idx = next(i for i, h in enumerate(header) if "nome canzone" in h.strip().lower())
            except StopIteration:
                col_idx = 0   # fallback: prima colonna

            # Raccoglie i nomi saltando la riga 0 (header) e il primo dato
            song_names = []
            for row in all_rows[2:]:   # all_rows[1] = primo elemento, saltato
                if len(row) > col_idx:
                    name = row[col_idx].strip()
                    if name:
                        song_names.append(name)

            if not song_names:
                st.warning("Nessuna song trovata nel CSV (dopo aver saltato il primo elemento).")
            else:
                st.markdown(f"**{len(song_names)} song trovate**")
                for n in song_names:
                    st.markdown(f"- {n}")

                st.divider()
                create_setlist = st.checkbox("Crea anche una setlist Luminite con tutte le song", value=True, key="sl_cb_solo")
                setlist_name   = ""
                setlist_target = None
                if create_setlist:
                    setlist_name = st.text_input("Nome setlist", value=csv_file.name.replace(".csv", ""), key="sl_name_solo")
                    all_sl_opts = backup.parse_setlists()
                    _sl_bytes   = backup.layout.setlist_slots_per_list * 4
                    _max_maps   = max(0, (backup.layout.exp_base - backup.layout.setlist_slots_base) // _sl_bytes)
                    all_sl_opts = [sl for sl in all_sl_opts if sl.index <= _max_maps]
                    if not all_sl_opts:
                        st.error("Nessuna setlist slot-map disponibile nel backup.")
                    sl_options  = [f"{sl.index:03d} — {sl.name}" for sl in all_sl_opts]
                    sl_default  = next((i for i, sl in enumerate(all_sl_opts) if not sl.song_ids), 0)
                    sl_choice   = st.selectbox("Slot setlist da sovrascrivere", sl_options,
                                               index=sl_default, key="sl_target_solo",
                                               help=f"Solo le prime {_max_maps} setlist hanno slot-map allocata nel backup")
                    setlist_target = int(sl_choice.split("—")[0].strip())

                if st.button("⚡ Crea songs nel backup", use_container_width=True, type="primary", key="gen_solo"):
                    all_songs_bk = backup.parse_songs()
                    existing     = {s.name.strip(): s.index for s in all_songs_bk
                                    if s.name.strip() and not _is_default_song_name(s.name)}
                    empty_slots  = iter(s for s in all_songs_bk
                                        if not s.name.strip() or _is_default_song_name(s.name))

                    created_indices: list[int] = []
                    errors: list[str] = []

                    for sname in song_names:
                        if sname in existing:
                            created_indices.append(existing[sname])
                        else:
                            try:
                                slot = next(empty_slots)
                            except StopIteration:
                                errors.append(f"Nessuno slot libero per '{sname}'")
                                continue
                            write_song_name(backup, slot.index, sname)
                            # slot IDs tutti vuoti
                            backup.set_song_slots(slot.index, [0] * backup.layout.song_slot_count)
                            created_indices.append(slot.index)

                    if create_setlist and setlist_name.strip() and created_indices:
                        _, sl_err = write_setlist(backup, setlist_name.strip(),
                                                  created_indices[: backup.layout.setlist_slots_per_list],
                                                  target_idx=setlist_target)
                        if sl_err:
                            errors.append(sl_err)

                    for e in errors:
                        st.error(e)
                    msg = f"✅ {len(created_indices)} song create nel backup."
                    if create_setlist and setlist_name.strip():
                        msg += f" Setlist '{setlist_name.strip()}' aggiornata."
                    st.success(msg)
                    st.session_state.songs_v += 1
                    st.rerun()

        # ── Modalità "Songs + preset" ─────────────────────────────────────────
        else:
            parsed_songs = parse_scaletta_csv(raw_text)
            all_lum_p    = backup.parse_presets()

            if not parsed_songs:
                st.warning("Nessuna song trovata nel CSV.")
            else:
                st.markdown(f"**{len(parsed_songs)} song trovate nel CSV**")

                resolved_songs: list[dict] = []
                has_missing = False
                for song in parsed_songs:
                    resolved_sections = []
                    for sec in song["sections"]:
                        # Matcha Sezione N - Nome contro i nomi dei preset Luminite
                        idx, matched = resolve_luminite_preset(sec["name"], all_lum_p)
                        resolved_sections.append({
                            "sec_name":    sec["name"],
                            "lum_index":   idx,
                            "matched_name": matched,
                            "ok":          idx is not None,
                        })
                        if idx is None:
                            has_missing = True
                    resolved_songs.append({"name": song["name"], "sections": resolved_sections})

                for rs in resolved_songs:
                    with st.expander(f"🎵 {rs['name']}", expanded=has_missing):
                        for i, sec in enumerate(rs["sections"]):
                            c1, c2 = st.columns([3, 4])
                            slot_label = SLOT_LABELS[i] if i < len(SLOT_LABELS) else f"Slot {i+1}"
                            c1.markdown(f"**{slot_label}** · `{sec['sec_name']}`")
                            if sec["ok"]:
                                c2.markdown(f"✅ Preset **{sec['lum_index']}** — {sec['matched_name']}")
                            else:
                                c2.markdown("⬜ Nessun match — slot vuoto")

                st.divider()
                if has_missing:
                    st.warning("⚠️ Alcune sezioni non hanno un preset Luminite con quel nome — gli slot resteranno vuoti.")

                create_setlist = st.checkbox("Crea anche una setlist Luminite", value=True, key="sl_cb_full")
                setlist_name   = ""
                setlist_target = None
                if create_setlist:
                    setlist_name = st.text_input("Nome setlist", value=csv_file.name.replace(".csv", ""), key="sl_name_full")
                    all_sl_opts  = backup.parse_setlists()
                    _sl_bytes    = backup.layout.setlist_slots_per_list * 4
                    _max_maps    = max(0, (backup.layout.exp_base - backup.layout.setlist_slots_base) // _sl_bytes)
                    all_sl_opts  = [sl for sl in all_sl_opts if sl.index <= _max_maps]
                    if not all_sl_opts:
                        st.error("Nessuna setlist slot-map disponibile nel backup.")
                    sl_options   = [f"{sl.index:03d} — {sl.name}" for sl in all_sl_opts]
                    sl_default   = next((i for i, sl in enumerate(all_sl_opts) if not sl.song_ids), 0)
                    sl_choice    = st.selectbox("Slot setlist da sovrascrivere", sl_options,
                                                index=sl_default, key="sl_target_full",
                                                help=f"Solo le prime {_max_maps} setlist hanno slot-map allocata nel backup")
                    setlist_target = int(sl_choice.split("—")[0].strip())

                if st.button("⚡ Genera songs nel backup", use_container_width=True,
                              type="primary", key="gen_full"):
                    all_songs_bk = backup.parse_songs()
                    existing     = {s.name.strip(): s.index for s in all_songs_bk
                                    if s.name.strip() and not _is_default_song_name(s.name)}
                    empty_slots  = iter(s for s in all_songs_bk
                                        if not s.name.strip() or _is_default_song_name(s.name))

                    created_indices: list[int] = []
                    errors: list[str] = []

                    for rs in resolved_songs:
                        sname = rs["name"]
                        if sname in existing:
                            tidx = existing[sname]
                        else:
                            try:
                                tidx = next(empty_slots).index
                            except StopIteration:
                                errors.append(f"Nessuno slot libero per '{sname}'")
                                continue

                        slot_ids = [0] * backup.layout.song_slot_count
                        for i, sec in enumerate(rs["sections"]):
                            if i >= backup.layout.song_slot_count:
                                break
                            slot_ids[i] = sec["lum_index"] if sec["ok"] else 0

                        write_song_name(backup, tidx, sname)
                        backup.set_song_slots(tidx, slot_ids)
                        created_indices.append(tidx)

                    if create_setlist and setlist_name.strip() and created_indices:
                        _, sl_err = write_setlist(backup, setlist_name.strip(),
                                                  created_indices[: backup.layout.setlist_slots_per_list],
                                                  target_idx=setlist_target)
                        if sl_err:
                            errors.append(sl_err)

                    for e in errors:
                        st.error(e)
                    msg = f"✅ {len(created_indices)} song create/aggiornate nel backup."
                    if create_setlist and setlist_name.strip():
                        msg += f" Setlist '{setlist_name.strip()}' aggiornata."
                    st.success(msg)
                    st.session_state.songs_v += 1
                    st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 — SONGS
# ═════════════════════════════════════════════════════════════════════════════

with tab_songs:
    st.subheader("Songs")
    st.caption("Ogni song ha 10 slot: **FS-A · FS-B · FS-C · FS-D · FS-E · FS-F · FS-G · FS-H · EC1 · EC2**.")

    named_songs   = [s for s in backup.parse_songs()   if s.name.strip()]
    named_presets = [p for p in backup.parse_presets() if p.name.strip()]

    if not named_songs:
        st.warning("Nessuna song trovata nel backup.")
    else:
        sv = st.session_state.songs_v

        preset_map  = {"— vuoto —": 0}
        preset_map.update({f"{p.index:03d} – {p.name}": p.index for p in named_presets})
        preset_list = list(preset_map.keys())

        song_labels  = [f"{s.index:03d} – {s.name}" for s in named_songs]
        sel_song_lbl = st.selectbox("Song", song_labels, key=f"sel_song_v{sv}")
        sel_song     = named_songs[song_labels.index(sel_song_lbl)]

        st.markdown(f"**Slot Song Mode — {sel_song.name}**")
        new_slots: list[int] = []

        for row_start in range(0, len(SLOT_LABELS), 2):
            cols = st.columns(2)
            for col, slot_idx in zip(cols, range(row_start, min(row_start + 2, len(SLOT_LABELS)))):
                current_id  = sel_song.preset_slot_ids[slot_idx] if slot_idx < len(sel_song.preset_slot_ids) else 0
                current_lbl = next((l for l, pid in preset_map.items() if pid == current_id), "— vuoto —")
                chosen = col.selectbox(
                    SLOT_LABELS[slot_idx], preset_list,
                    index=preset_list.index(current_lbl) if current_lbl in preset_list else 0,
                    key=f"song_{sel_song.index}_{slot_idx}_v{sv}",
                )
                new_slots.append(preset_map[chosen])

        while len(new_slots) < backup.layout.song_slot_count:
            new_slots.append(0)

        if st.button("💾 Salva assegnazioni", use_container_width=True, key=f"save_song_v{sv}"):
            backup.set_song_slots(sel_song.index, new_slots[: backup.layout.song_slot_count])
            st.session_state.songs_v += 1
            st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 — SETLISTS
# ═════════════════════════════════════════════════════════════════════════════

with tab_setlists:
    st.subheader("Setlists")

    _sl_bytes_tab  = backup.layout.setlist_slots_per_list * 4
    _max_maps_tab  = max(0, (backup.layout.exp_base - backup.layout.setlist_slots_base) // _sl_bytes_tab)
    named_setlists = [sl for sl in backup.parse_setlists()
                      if sl.name.strip() and sl.index <= _max_maps_tab]
    song_map       = {f"{s.index:03d} – {s.name}": s.index
                      for s in backup.parse_songs()
                      if s.name.strip() and not _is_default_song_name(s.name)}

    if not named_setlists:
        st.warning("Nessuna setlist trovata nel backup.")
    else:
        slv = st.session_state.songs_v   # riusa songs_v — si incrementa quando cambiano songs/setlists

        sl_labels  = [f"{sl.index:03d} – {sl.name}" for sl in named_setlists]
        sel_sl_lbl = st.selectbox("Setlist", sl_labels, key=f"sel_setlist_v{slv}")
        sel_sl     = named_setlists[sl_labels.index(sel_sl_lbl)]

        current_song_labels = [
            lbl for lbl in (next((l for l, i in song_map.items() if i == sid), None)
                             for sid in sel_sl.song_ids) if lbl is not None
        ]

        st.markdown(f"**{sel_sl.name}** — {len(current_song_labels)} / {backup.layout.setlist_slots_per_list} canzoni")
        chosen_songs = st.multiselect(
            "Canzoni", options=list(song_map.keys()), default=current_song_labels,
            max_selections=backup.layout.setlist_slots_per_list,
            key=f"multisel_setlist_v{slv}", label_visibility="collapsed",
        )

        if st.button("💾 Salva setlist", use_container_width=True, key=f"save_setlist_v{slv}"):
            backup.set_setlist_song_ids(sel_sl.index, [song_map[l] for l in chosen_songs])
            # Scrivi anche il nome se l'utente l'ha cambiato via CSV
            st.session_state.songs_v += 1
            st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# TAB 4 — ESPORTA
# ═════════════════════════════════════════════════════════════════════════════

with tab_export:
    st.subheader("Esporta")
    out_name = (st.session_state.last_filename or "backup").replace(".bak", "_modificato.bak")
    st.download_button(
        "⬇️  Scarica backup Luminite modificato",
        data=io.BytesIO(backup.to_bytes()),
        file_name=out_name,
        mime="application/octet-stream",
        use_container_width=True,
    )
