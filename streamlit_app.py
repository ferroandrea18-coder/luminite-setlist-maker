from __future__ import annotations

import io
import json
from pathlib import Path

import streamlit as st

from analyze_backup import build_report
from luminite.backup import LuminiteBackup
from luminite.compiler import SmartCompiler
from luminite.library import library_from_backup, load_library


st.set_page_config(page_title="Luminite QC Smart Compiler", layout="wide")
st.title("Luminite QC Smart Compiler")
st.caption("Analisi e patch in-place di backup Luminite/Graviton con supporto libreria Quad Cortex.")


def _calculate_qc_midi(folder_index: int, preset_number_1_based: int) -> dict:
    preset_zero_based = preset_number_1_based - 1
    bank_cc_0 = 0 if preset_zero_based < 128 else 1
    program_change = preset_zero_based % 128
    return {
        "folder_index": folder_index,
        "preset_number_1_based": preset_number_1_based,
        "preset_zero_based": preset_zero_based,
        "bank_cc_0": bank_cc_0,
        "bank_cc_32": folder_index,
        "program_change": program_change,
    }


def _load_uploaded_backup() -> LuminiteBackup | None:
    uploaded = st.file_uploader("Carica un file .bak", type=["bak"])
    if not uploaded:
        return None
    return LuminiteBackup.from_bytes(uploaded.getvalue())


def _render_backup_inspector(backup: LuminiteBackup) -> None:
    st.subheader("Binary Inspector")
    strings = backup.extract_strings(min_length=4)
    presets = backup.parse_presets()
    songs = backup.parse_songs()
    setlists = backup.parse_setlists()
    summary = backup.analysis_summary()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Size", f"{backup.size:,} bytes")
    col2.metric("Presets", len(presets))
    col3.metric("Songs", len(songs))
    col4.metric("Setlists", len(setlists))

    with st.expander("Mappa reverse engineering", expanded=True):
        st.json(summary, expanded=True)
        st.info(
            "Nel file campione i Song record sono da 44 byte; gli ultimi 10 byte di ogni record si comportano come riferimenti al Preset Pool."
        )

    with st.expander("Preset Pool"):
        st.dataframe(
            [
                {
                    "preset_id": item.index,
                    "offset": f"0x{item.offset:08X}",
                    "name": item.name,
                    "first_midi": (
                        f"0x{item.commands[0].offset:08X} {item.commands[0].raw.hex(' ').upper()}"
                        if item.commands
                        else ""
                    ),
                }
                for item in presets
            ],
            use_container_width=True,
            height=260,
        )

    with st.expander("Songs e slot -> Preset Pool", expanded=True):
        preset_names = {item.index: item.name for item in presets}
        st.dataframe(
            [
                {
                    "song_id": item.index,
                    "offset": f"0x{item.offset:08X}",
                    "name": item.name,
                    "flags": " ".join(f"{value:02X}" for value in item.flags),
                    "slot_ids": json.dumps(item.preset_slot_ids),
                    "slot_names": json.dumps(
                        [preset_names.get(slot_id, "") if slot_id else "" for slot_id in item.preset_slot_ids],
                        ensure_ascii=True,
                    ),
                }
                for item in songs
            ],
            use_container_width=True,
            height=320,
        )

    with st.expander("Setlists"):
        song_names = {item.index: item.name for item in songs}
        st.dataframe(
            [
                {
                    "setlist_id": item.index,
                    "offset": f"0x{item.offset:08X}",
                    "name": item.name,
                    "song_ids": json.dumps(item.song_ids),
                    "song_names": json.dumps([song_names.get(song_id, "") for song_id in item.song_ids], ensure_ascii=True),
                }
                for item in setlists
                if item.song_ids
            ],
            use_container_width=True,
            height=220,
        )

    with st.expander("Stringhe trovate"):
        filter_text = st.text_input("Filtro testo")
        rows = [
            {
                "offset_hex": f"0x{item.offset:08X}",
                "length": item.raw_length,
                "encoding": item.encoding,
                "value": item.value,
            }
            for item in strings
            if not filter_text or filter_text.lower() in item.value.lower()
        ]
        st.dataframe(rows, use_container_width=True, height=220)


def _render_song_and_setlist_editor(backup: LuminiteBackup) -> bytes:
    st.subheader("Song & Setlist Editor")
    edited = LuminiteBackup.from_bytes(backup.to_bytes())
    presets = edited.parse_presets()
    songs = edited.parse_songs()
    setlists = edited.parse_setlists()
    preset_options = {f"{item.index:03d} - {item.name}": item.index for item in presets}
    song_options = {f"{item.index:03d} - {item.name}": item.index for item in songs}

    song_col, setlist_col = st.columns(2)

    with song_col:
        st.markdown("**Song Builder**")
        selected_song_label = st.selectbox("Song da modificare", options=list(song_options.keys()))
        selected_song = songs[song_options[selected_song_label] - 1]
        chosen_slots: list[int] = []
        for slot_index in range(1, edited.layout.song_slot_count + 1):
            current_id = selected_song.preset_slot_ids[slot_index - 1]
            default_label = next(
                (label for label, preset_id in preset_options.items() if preset_id == current_id),
                list(preset_options.keys())[0],
            )
            slot_label = st.selectbox(
                f"Slot {slot_index}",
                options=list(preset_options.keys()),
                index=list(preset_options.keys()).index(default_label),
                key=f"song_slot_{slot_index}",
            )
            chosen_slots.append(preset_options[slot_label])
        if st.button("Salva slot Song", use_container_width=True):
            try:
                result = edited.set_song_slots(selected_song.index, chosen_slots)
                st.success(f"Song '{result.name}' aggiornata con i nuovi riferimenti preset.")
            except Exception as exc:
                st.error(str(exc))

    with setlist_col:
        st.markdown("**Setlist Manager**")
        selected_setlist_label = st.selectbox(
            "Setlist da modificare",
            options=[f"{item.index:03d} - {item.name}" for item in setlists],
        )
        selected_setlist_index = int(selected_setlist_label.split(" - ", 1)[0])
        selected_setlist = setlists[selected_setlist_index - 1]
        current_song_labels = [
            next((label for label, song_id in song_options.items() if song_id == item), None)
            for item in selected_setlist.song_ids
        ]
        current_song_labels = [label for label in current_song_labels if label is not None]
        chosen_song_labels = st.multiselect(
            "Ordine canzoni",
            options=list(song_options.keys()),
            default=current_song_labels,
            max_selections=edited.layout.setlist_slots_per_list,
        )
        if st.button("Salva Setlist", use_container_width=True):
            try:
                result = edited.set_setlist_song_ids(
                    selected_setlist.index,
                    [song_options[label] for label in chosen_song_labels],
                )
                st.success(f"Setlist '{result.name}' aggiornata con {len(result.song_ids)} canzoni.")
            except Exception as exc:
                st.error(str(exc))

    return edited.to_bytes()


def _render_patch_tools(backup: LuminiteBackup) -> bytes:
    st.subheader("Patch Tools")
    edited = LuminiteBackup.from_bytes(backup.to_bytes())
    songs = edited.parse_songs()
    presets = edited.parse_presets()

    rename_col, patch_col = st.columns(2)

    with rename_col:
        st.markdown("**Rinomina record a lunghezza fissa**")
        record_type = st.selectbox("Tipo record", options=["Setlist", "Song", "Preset"])
        old_name = st.text_input("Nome attuale")
        new_name = st.text_input("Nuovo nome")
        occurrence = st.number_input("Occorrenza", min_value=0, step=1, value=0)
        if st.button("Applica rename", use_container_width=True):
            try:
                if record_type == "Setlist":
                    result = edited.rename_setlist(old_name=old_name, new_name=new_name, occurrence=occurrence)
                elif record_type == "Song":
                    result = edited.rename_song(old_name=old_name, new_name=new_name, occurrence=occurrence)
                else:
                    result = edited.rename_preset(old_name=old_name, new_name=new_name, occurrence=occurrence)
                st.success(
                    f"Stringa aggiornata a 0x{result.offset:08X} con lunghezza fissa di {result.raw_length} byte."
                )
            except Exception as exc:
                st.error(str(exc))

    with patch_col:
        st.markdown("**Patch CC sul preset referenziato da una Song**")
        song_name = st.selectbox("Song target", options=[item.name for item in songs])
        song = next(item for item in songs if item.name == song_name)
        slot_label_map = {
            f"Slot {index} -> Preset {song.preset_slot_ids[index - 1]}": index
            for index in range(1, len(song.preset_slot_ids) + 1)
        }
        slot_label = st.selectbox("Slot Song", options=list(slot_label_map.keys()))
        command_index = st.number_input("Indice comando nel preset", min_value=1, max_value=16, value=1, step=1)
        cc_number = st.slider("CC Number", min_value=0, max_value=127, value=7)
        cc_value = st.slider("CC Value", min_value=0, max_value=127, value=127)
        if st.button("Applica CC patch", use_container_width=True):
            try:
                song_record, preset_record, midi = edited.patch_song_preset_control_change(
                    song_name=song_name,
                    song_slot=slot_label_map[slot_label],
                    command_index=command_index,
                    cc_number=cc_number,
                    cc_value=cc_value,
                )
                st.success(
                    f"Song '{song_record.name}' slot {slot_label_map[slot_label]} -> preset '{preset_record.name}' aggiornato a 0x{midi.offset:08X}."
                )
            except Exception as exc:
                st.error(str(exc))

        st.caption("Comandi del preset selezionato")
        preset_id = song.preset_slot_ids[slot_label_map[slot_label] - 1]
        if 1 <= preset_id <= len(presets):
            preset = presets[preset_id - 1]
            st.dataframe(
                [
                    {
                        "command": item.index,
                        "offset": f"0x{item.offset:08X}",
                        "raw": item.raw.hex(" ").upper(),
                        "midi": (
                            f"{item.midi.status:02X} {item.midi.data_1:02X} {item.midi.data_2:02X}"
                            if item.midi
                            else ""
                        ),
                    }
                    for item in preset.commands
                ],
                use_container_width=True,
                height=220,
            )

    return edited.to_bytes()


def _render_export_tools(backup: LuminiteBackup) -> None:
    st.subheader("Export Tools")
    report = build_report(backup)
    report_bytes = json.dumps(report, indent=2, ensure_ascii=True).encode("utf-8")
    library = library_from_backup(backup)
    library_payload = {
        "master_sounds": [
            {
                "name": item.name,
                "mapping": {
                    "program_change": item.mapping.program_change,
                    "control_change": item.mapping.control_change,
                    "control_value": item.mapping.control_value,
                    "channel": item.mapping.channel,
                },
            }
            for item in library.master_sounds
        ],
        "songs": [
            {
                "name": item.name,
                "slots": [{"name": slot.name, "master_sound": slot.master_sound} for slot in item.slots],
            }
            for item in library.songs
        ],
        "setlists": [{"name": item.name, "song_names": item.song_names} for item in library.setlists],
        "source_path": str(library.source_path) if library.source_path else None,
    }
    library_bytes = json.dumps(library_payload, indent=2, ensure_ascii=True).encode("utf-8")

    left, right = st.columns(2)
    left.download_button(
        "Scarica report JSON",
        data=io.BytesIO(report_bytes),
        file_name="backup_analysis.json",
        mime="application/json",
        use_container_width=True,
    )
    right.download_button(
        "Scarica libreria dal backup",
        data=io.BytesIO(library_bytes),
        file_name="my_rig.from_backup.json",
        mime="application/json",
        use_container_width=True,
    )


def _render_qc_midi_calculator() -> None:
    st.subheader("Quad Cortex MIDI Calculator")
    left, right = st.columns(2)

    with left:
        folder_index = st.number_input(
            "Indice setlist/folder QC (CC#32)",
            min_value=0,
            max_value=12,
            value=2,
            step=1,
            help="0 = Factory Presets, 1 = My Presets, 2-12 = User folders.",
        )
        preset_number = st.number_input(
            "Numero preset QC (1-256)",
            min_value=1,
            max_value=256,
            value=1,
            step=1,
            help="Numero preset in notazione umana. Il tool lo converte in PC zero-based.",
        )

    result = _calculate_qc_midi(folder_index=folder_index, preset_number_1_based=preset_number)

    with right:
        st.metric("CC#32", result["bank_cc_32"])
        st.metric("CC#0", result["bank_cc_0"])
        st.metric("PC", result["program_change"])

    st.code(
        "\n".join(
            [
                f"CC#32 = {result['bank_cc_32']}",
                f"CC#0  = {result['bank_cc_0']}",
                f"PC    = {result['program_change']}",
            ]
        ),
        language="text",
    )
    st.caption(
        "Calcolo basato sulla documentazione ufficiale Quad Cortex: CC#32 seleziona il folder/setlist, "
        "CC#0 seleziona il gruppo preset 0-127 o 128-255, e PC richiama il preset dentro il gruppo."
    )


def _render_library_apply_tools(backup: LuminiteBackup) -> bytes:
    st.subheader("Apply Library To Backup")
    edited = LuminiteBackup.from_bytes(backup.to_bytes())
    compiler = SmartCompiler()
    library_path = st.text_input("Percorso libreria da applicare", value="my_rig.json")
    if not Path(library_path).exists():
        st.info("Inserisci un file libreria JSON esistente per applicarlo al backup.")
        return edited.to_bytes()

    try:
        library = load_library(library_path)
    except Exception as exc:
        st.error(f"Errore caricando la libreria: {exc}")
        return edited.to_bytes()

    if st.button("Applica libreria al backup", use_container_width=True):
        try:
            result = compiler.apply_library_to_backup(library, edited)
            st.success(
                f"Songs aggiornate: {len(result.updated_songs)}. Setlists aggiornate: {len(result.updated_setlists)}."
            )
            if result.missing_master_sounds:
                st.warning(f"Master sounds mancanti nel backup: {', '.join(result.missing_master_sounds)}")
            if result.missing_songs:
                st.warning(f"Elementi non trovati per nome: {', '.join(result.missing_songs)}")
        except Exception as exc:
            st.error(str(exc))
    return edited.to_bytes()


def _render_library_compiler() -> None:
    st.subheader("Rig Library Compiler")
    library_path = st.text_input("Percorso my_rig.json", value="my_rig.json")
    if not Path(library_path).exists():
        st.info("Inserisci un file libreria JSON per attivare la compilazione deduplicata.")
        return

    try:
        library = load_library(library_path)
        result = SmartCompiler().compile_library(library)
    except Exception as exc:
        st.error(f"Errore caricando la libreria: {exc}")
        return

    left, right = st.columns(2)
    left.metric("Master sounds deduplicati", len(result.sound_pool))
    right.metric("Songs compilate", len(result.songs))

    with st.expander("Sound pool deduplicato", expanded=True):
        st.dataframe(
            [
                {
                    "pool_id": item.pool_id,
                    "name": item.name,
                    "pc": item.source_sound.mapping.program_change,
                    "cc": item.source_sound.mapping.control_change,
                    "value": item.source_sound.mapping.control_value,
                }
                for item in result.sound_pool
            ],
            use_container_width=True,
        )

    with st.expander("Song references"):
        st.dataframe(
            [{"song": item.name, "pool_refs": json.dumps(item.sound_pool_refs)} for item in result.songs],
            use_container_width=True,
        )


backup = _load_uploaded_backup()

if backup is not None:
    _render_backup_inspector(backup)
    edited_from_song_editor = _render_song_and_setlist_editor(backup)
    edited_from_patch_tools = _render_patch_tools(LuminiteBackup.from_bytes(edited_from_song_editor))
    edited_from_library_apply = _render_library_apply_tools(LuminiteBackup.from_bytes(edited_from_patch_tools))
    st.download_button(
        "Scarica backup patchato",
        data=io.BytesIO(edited_from_library_apply),
        file_name="patched_backup.bak",
        mime="application/octet-stream",
        use_container_width=True,
    )
    _render_export_tools(LuminiteBackup.from_bytes(edited_from_library_apply))
else:
    st.info("Carica un `.bak` per ispezionare stringhe, slot MIDI ed encoder.")

_render_qc_midi_calculator()
_render_library_compiler()
