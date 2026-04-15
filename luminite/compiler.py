from __future__ import annotations

from dataclasses import dataclass

from luminite.backup import LuminiteBackup
from luminite.models import MasterSound, SongDefinition, UserRigLibrary


@dataclass(slots=True)
class CompiledSound:
    pool_id: int
    name: str
    source_sound: MasterSound


@dataclass(slots=True)
class CompiledSong:
    name: str
    sound_pool_refs: list[int]


@dataclass(slots=True)
class CompilationResult:
    sound_pool: list[CompiledSound]
    songs: list[CompiledSong]


@dataclass(slots=True)
class BackupApplyResult:
    updated_songs: list[str]
    updated_setlists: list[str]
    missing_master_sounds: list[str]
    missing_songs: list[str]


class SmartCompiler:
    def compile_library(self, library: UserRigLibrary) -> CompilationResult:
        pool: dict[str, CompiledSound] = {}
        compiled_songs: list[CompiledSong] = []

        by_name = {sound.name: sound for sound in library.master_sounds}
        for song in library.songs:
            song.ensure_six_slots()
            refs: list[int] = []
            for slot in song.slots:
                if not slot.master_sound:
                    refs.append(-1)
                    continue
                compiled = pool.get(slot.master_sound)
                if compiled is None:
                    source = by_name[slot.master_sound]
                    compiled = CompiledSound(pool_id=len(pool), name=slot.master_sound, source_sound=source)
                    pool[slot.master_sound] = compiled
                refs.append(compiled.pool_id)
            compiled_songs.append(CompiledSong(name=song.name, sound_pool_refs=refs))

        return CompilationResult(sound_pool=list(pool.values()), songs=compiled_songs)

    def apply_library_to_backup(self, library: UserRigLibrary, backup: LuminiteBackup) -> BackupApplyResult:
        presets = backup.parse_presets()
        songs = backup.parse_songs()
        preset_id_by_name = {item.name: item.index for item in presets}
        song_id_by_name = {item.name: item.index for item in songs}

        missing_master_sounds: list[str] = []
        missing_songs: list[str] = []
        updated_songs: list[str] = []
        updated_setlists: list[str] = []

        for song in library.songs:
            song.ensure_six_slots()
            slot_ids = []
            for slot in song.slots:
                if not slot.master_sound:
                    slot_ids.append(0)
                    continue
                preset_id = preset_id_by_name.get(slot.master_sound)
                if preset_id is None:
                    if slot.master_sound not in missing_master_sounds:
                        missing_master_sounds.append(slot.master_sound)
                    slot_ids.append(0)
                else:
                    slot_ids.append(preset_id)
            slot_ids.extend([0] * max(0, backup.layout.song_slot_count - len(slot_ids)))
            try:
                backup.set_song_slots_by_name(song.name, slot_ids[: backup.layout.song_slot_count])
                updated_songs.append(song.name)
            except ValueError:
                missing_songs.append(song.name)

        for setlist in library.setlists:
            song_ids = []
            for song_name in setlist.song_names:
                song_id = song_id_by_name.get(song_name)
                if song_id is None:
                    if song_name not in missing_songs:
                        missing_songs.append(song_name)
                    continue
                song_ids.append(song_id)
            try:
                backup.set_setlist_song_ids_by_name(setlist.name, song_ids)
                updated_setlists.append(setlist.name)
            except ValueError:
                if setlist.name not in missing_songs:
                    missing_songs.append(setlist.name)

        return BackupApplyResult(
            updated_songs=updated_songs,
            updated_setlists=updated_setlists,
            missing_master_sounds=missing_master_sounds,
            missing_songs=missing_songs,
        )
