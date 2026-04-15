from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from luminite.backup import LuminiteBackup
from luminite.models import UserRigLibrary


def load_library(path: str | Path) -> UserRigLibrary:
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    library = UserRigLibrary(
        master_sounds=[],
        songs=[],
        setlists=[],
        source_path=path,
    )
    for item in payload.get("master_sounds", []):
        library.master_sounds.append(_decode_dataclass(item, "MasterSound"))
    for item in payload.get("songs", []):
        song = _decode_dataclass(item, "SongDefinition")
        song.ensure_six_slots()
        library.songs.append(song)
    for item in payload.get("setlists", []):
        library.setlists.append(_decode_dataclass(item, "SetlistDefinition"))
    return library


def save_library(path: str | Path, library: UserRigLibrary) -> None:
    path = Path(path)
    payload = asdict(library)
    if library.source_path is not None:
        payload["source_path"] = str(library.source_path)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def library_from_backup(backup: LuminiteBackup) -> UserRigLibrary:
    from luminite import models

    presets = backup.parse_presets()
    songs = backup.parse_songs()
    setlists = backup.parse_setlists()
    preset_by_id = {item.index: item for item in presets}

    master_sounds: list[models.MasterSound] = []
    for preset in presets:
        first_pc = next((command.midi for command in preset.commands if command.midi and (command.midi.status & 0xF0) == 0xC0), None)
        first_cc = next((command.midi for command in preset.commands if command.midi and command.midi.is_control_change), None)
        master_sounds.append(
            models.MasterSound(
                name=preset.name,
                mapping=models.MidiMapping(
                    program_change=first_pc.data_1 if first_pc else None,
                    control_change=first_cc.data_1 if first_cc else None,
                    control_value=first_cc.data_2 if first_cc else None,
                    channel=first_cc.channel if first_cc else (first_pc.channel if first_pc else 1),
                ),
            )
        )

    song_defs: list[models.SongDefinition] = []
    for song in songs:
        slots = []
        for slot_index, preset_id in enumerate(song.preset_slot_ids[:6], start=1):
            slots.append(
                models.SongSection(
                    name=f"Slot {slot_index}",
                    master_sound=preset_by_id[preset_id].name if preset_id in preset_by_id else None,
                )
            )
        definition = models.SongDefinition(name=song.name, slots=slots)
        definition.ensure_six_slots()
        song_defs.append(definition)

    setlist_defs = [
        models.SetlistDefinition(
            name=setlist.name,
            song_names=[songs[song_id - 1].name for song_id in setlist.song_ids if 1 <= song_id <= len(songs)],
        )
        for setlist in setlists
        if setlist.song_ids
    ]

    return models.UserRigLibrary(
        master_sounds=master_sounds,
        songs=song_defs,
        setlists=setlist_defs,
        source_path=backup.source_path,
    )


def _decode_dataclass(payload: dict, class_name: str):
    from luminite import models

    cls = getattr(models, class_name)
    field_names = {field.name for field in cls.__dataclass_fields__.values()}
    kwargs = {}
    for key, value in payload.items():
        if key not in field_names:
            continue
        if class_name == "MasterSound" and key == "mapping":
            kwargs[key] = models.MidiMapping(**value)
        elif class_name == "SongDefinition" and key == "slots":
            kwargs[key] = []
            for slot in value:
                ec1 = slot.get("encoder_ec1")
                ec2 = slot.get("encoder_ec2")
                kwargs[key].append(
                    models.SongSection(
                        name=slot["name"],
                        master_sound=slot.get("master_sound"),
                        encoder_ec1=models.EncoderAssignment(**ec1) if ec1 else None,
                        encoder_ec2=models.EncoderAssignment(**ec2) if ec2 else None,
                    )
                )
        else:
            kwargs[key] = value
    return cls(**kwargs)
