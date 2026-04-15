from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PRINTABLE = set(range(32, 127))


@dataclass(slots=True)
class BinaryString:
    offset: int
    raw_length: int
    value: str
    encoding: str


@dataclass(slots=True)
class MidiMessage:
    offset: int
    status: int
    data_1: int
    data_2: int
    channel: int

    @property
    def is_control_change(self) -> bool:
        return (self.status & 0xF0) == 0xB0


@dataclass(slots=True)
class EncoderCandidate:
    offset: int
    label: str
    rotation: MidiMessage | None = None
    push: MidiMessage | None = None


@dataclass(slots=True)
class BackupLayout:
    preset_base: int = 0x10C
    preset_count: int = 120
    preset_stride: int = 0x51
    preset_name_size: int = 14
    song_base: int = 0x4C0C
    song_count: int = 120
    song_stride: int = 0x2C
    song_name_size: int = 16
    song_flags_size: int = 18
    song_slot_count: int = 10
    setlist_base: int = 0x60AC
    setlist_count: int = 120
    setlist_stride: int = 0x2C
    setlist_name_size: int = 16
    setlist_slots_base: int = 0x754C
    setlist_slots_per_list: int = 20
    exp_base: int = 0x763C


@dataclass(slots=True)
class PresetCommand:
    index: int
    offset: int
    raw: bytes
    midi: MidiMessage | None


@dataclass(slots=True)
class PresetRecord:
    index: int
    offset: int
    name: str
    name_offset: int
    name_size: int
    payload_offset: int
    payload_size: int
    commands: list[PresetCommand]


@dataclass(slots=True)
class SongRecord:
    index: int
    offset: int
    name: str
    name_offset: int
    name_size: int
    flags: list[int]
    preset_slot_ids: list[int]


@dataclass(slots=True)
class SetlistRecord:
    index: int
    offset: int
    name: str
    name_offset: int
    name_size: int
    song_ids: list[int]


class LuminiteBackup:
    def __init__(self, data: bytes, source_path: Path | None = None, layout: BackupLayout | None = None) -> None:
        self._data = bytearray(data)
        self.source_path = source_path
        self.layout = layout or BackupLayout()

    @classmethod
    def from_file(cls, path: str | Path) -> "LuminiteBackup":
        path = Path(path)
        return cls(path.read_bytes(), source_path=path)

    @classmethod
    def from_bytes(cls, data: bytes) -> "LuminiteBackup":
        return cls(data)

    @property
    def size(self) -> int:
        return len(self._data)

    def to_bytes(self) -> bytes:
        return bytes(self._data)

    def save(self, path: str | Path) -> None:
        Path(path).write_bytes(self.to_bytes())

    def analysis_summary(self) -> dict:
        active_setlists = max(0, (self.layout.exp_base - self.layout.setlist_slots_base) // (self.layout.setlist_slots_per_list * 4))
        return {
            "preset_table": {
                "base": self.layout.preset_base,
                "count": self.layout.preset_count,
                "stride": self.layout.preset_stride,
                "name_size": self.layout.preset_name_size,
            },
            "song_table": {
                "base": self.layout.song_base,
                "count": self.layout.song_count,
                "stride": self.layout.song_stride,
                "name_size": self.layout.song_name_size,
                "flags_size": self.layout.song_flags_size,
                "slot_count": self.layout.song_slot_count,
            },
            "setlist_table": {
                "base": self.layout.setlist_base,
                "count": self.layout.setlist_count,
                "stride": self.layout.setlist_stride,
                "name_size": self.layout.setlist_name_size,
                "slot_map_base": self.layout.setlist_slots_base,
                "slots_per_setlist": self.layout.setlist_slots_per_list,
                "active_setlists_detected": active_setlists,
            },
        }

    def to_structured_dict(self) -> dict:
        presets = self.parse_presets()
        songs = self.parse_songs()
        setlists = self.parse_setlists()
        preset_names = {item.index: item.name for item in presets}
        song_names = {item.index: item.name for item in songs}
        return {
            "summary": self.analysis_summary(),
            "presets": [
                {
                    "preset_id": item.index,
                    "offset_hex": f"0x{item.offset:08X}",
                    "name": item.name,
                    "commands": [
                        {
                            "command_index": command.index,
                            "offset_hex": f"0x{command.offset:08X}",
                            "raw_hex": command.raw.hex(" ").upper(),
                            "midi": (
                                {
                                    "status_hex": f"0x{command.midi.status:02X}",
                                    "data_1": command.midi.data_1,
                                    "data_2": command.midi.data_2,
                                    "channel": command.midi.channel,
                                }
                                if command.midi
                                else None
                            ),
                        }
                        for command in item.commands
                    ],
                }
                for item in presets
            ],
            "songs": [
                {
                    "song_id": item.index,
                    "offset_hex": f"0x{item.offset:08X}",
                    "name": item.name,
                    "flags_hex": " ".join(f"{value:02X}" for value in item.flags),
                    "preset_slot_ids": item.preset_slot_ids,
                    "preset_slot_names": [preset_names.get(slot_id, "") if slot_id else "" for slot_id in item.preset_slot_ids],
                }
                for item in songs
            ],
            "setlists": [
                {
                    "setlist_id": item.index,
                    "offset_hex": f"0x{item.offset:08X}",
                    "name": item.name,
                    "song_ids": item.song_ids,
                    "song_names": [song_names.get(song_id, "") for song_id in item.song_ids],
                }
                for item in setlists
            ],
        }

    def parse_presets(self) -> list[PresetRecord]:
        records: list[PresetRecord] = []
        for index in range(self.layout.preset_count):
            offset = self.layout.preset_base + (index * self.layout.preset_stride)
            name = self.read_fixed_string(offset, self.layout.preset_name_size)
            payload_offset = offset + self.layout.preset_name_size
            payload_size = self.layout.preset_stride - self.layout.preset_name_size
            payload = self._data[payload_offset : payload_offset + payload_size]
            commands: list[PresetCommand] = []
            for command_index, command_offset in enumerate(range(0, max(0, len(payload) - 3), 4), start=1):
                raw = bytes(payload[command_offset : command_offset + 4])
                if len(raw) < 4:
                    continue
                midi = self._decode_midi_message(payload_offset + command_offset)
                commands.append(
                    PresetCommand(
                        index=command_index,
                        offset=payload_offset + command_offset,
                        raw=raw,
                        midi=midi,
                    )
                )
            records.append(
                PresetRecord(
                    index=index + 1,
                    offset=offset,
                    name=name,
                    name_offset=offset,
                    name_size=self.layout.preset_name_size,
                    payload_offset=payload_offset,
                    payload_size=payload_size,
                    commands=commands,
                )
            )
        return records

    def parse_songs(self) -> list[SongRecord]:
        records: list[SongRecord] = []
        for index in range(self.layout.song_count):
            offset = self.layout.song_base + (index * self.layout.song_stride)
            payload_offset = offset + self.layout.song_name_size
            payload = self._data[payload_offset : payload_offset + (self.layout.song_stride - self.layout.song_name_size)]
            flags = list(payload[: self.layout.song_flags_size])
            slot_ids = list(payload[self.layout.song_flags_size : self.layout.song_flags_size + self.layout.song_slot_count])
            records.append(
                SongRecord(
                    index=index + 1,
                    offset=offset,
                    name=self.read_fixed_string(offset, self.layout.song_name_size),
                    name_offset=offset,
                    name_size=self.layout.song_name_size,
                    flags=flags,
                    preset_slot_ids=slot_ids,
                )
            )
        return records

    def parse_setlists(self) -> list[SetlistRecord]:
        records: list[SetlistRecord] = []
        slot_bytes = self.layout.setlist_slots_per_list * 4
        active_setlists = max(0, (self.layout.exp_base - self.layout.setlist_slots_base) // slot_bytes)
        for index in range(self.layout.setlist_count):
            offset = self.layout.setlist_base + (index * self.layout.setlist_stride)
            song_ids: list[int] = []
            if index < active_setlists:
                entries_offset = self.layout.setlist_slots_base + (index * slot_bytes)
                for item_index in range(self.layout.setlist_slots_per_list):
                    item_offset = entries_offset + (item_index * 4)
                    song_id = int.from_bytes(self._data[item_offset : item_offset + 4], byteorder="little", signed=False)
                    if song_id != 0:
                        song_ids.append(song_id)
            records.append(
                SetlistRecord(
                    index=index + 1,
                    offset=offset,
                    name=self.read_fixed_string(offset, self.layout.setlist_name_size),
                    name_offset=offset,
                    name_size=self.layout.setlist_name_size,
                    song_ids=song_ids,
                )
            )
        return records

    def extract_strings(self, min_length: int = 4) -> list[BinaryString]:
        strings: list[BinaryString] = []
        strings.extend(self._extract_ascii_strings(min_length=min_length))
        strings.extend(self._extract_utf16le_strings(min_length=min_length))
        strings.sort(key=lambda item: item.offset)
        return strings

    def find_text_offsets(self, text: str) -> list[BinaryString]:
        matches: list[BinaryString] = []
        for item in self.extract_strings(min_length=max(2, len(text))):
            if item.value == text:
                matches.append(item)
        return matches

    def read_fixed_string(self, offset: int, size: int, encoding: str = "ascii") -> str:
        raw = bytes(self._data[offset : offset + size])
        return raw.split(b"\x00", 1)[0].decode(encoding, errors="ignore")

    def rename_fixed_string(self, old_name: str, new_name: str, occurrence: int = 0) -> BinaryString:
        matches = self.find_text_offsets(old_name)
        if not matches:
            raise ValueError(f"String '{old_name}' not found in backup")
        if occurrence >= len(matches):
            raise IndexError(f"Occurrence {occurrence} out of range for '{old_name}'")
        target = matches[occurrence]
        self.patch_fixed_string(target.offset, target.raw_length, new_name, target.encoding)
        return BinaryString(
            offset=target.offset,
            raw_length=target.raw_length,
            value=new_name,
            encoding=target.encoding,
        )

    def rename_setlist(self, old_name: str, new_name: str, occurrence: int = 0) -> BinaryString:
        matches = [item for item in self.parse_setlists() if item.name == old_name]
        if not matches:
            raise ValueError(f"Setlist '{old_name}' not found in setlist table")
        if occurrence >= len(matches):
            raise IndexError(f"Occurrence {occurrence} out of range for setlist '{old_name}'")
        target = matches[occurrence]
        self.patch_fixed_string(target.name_offset, target.name_size, new_name, "ascii")
        return BinaryString(offset=target.name_offset, raw_length=target.name_size, value=new_name, encoding="ascii")

    def rename_song(self, old_name: str, new_name: str, occurrence: int = 0) -> BinaryString:
        matches = [item for item in self.parse_songs() if item.name == old_name]
        if not matches:
            raise ValueError(f"Song '{old_name}' not found in song table")
        if occurrence >= len(matches):
            raise IndexError(f"Occurrence {occurrence} out of range for song '{old_name}'")
        target = matches[occurrence]
        self.patch_fixed_string(target.name_offset, target.name_size, new_name, "ascii")
        return BinaryString(offset=target.name_offset, raw_length=target.name_size, value=new_name, encoding="ascii")

    def rename_preset(self, old_name: str, new_name: str, occurrence: int = 0) -> BinaryString:
        matches = [item for item in self.parse_presets() if item.name == old_name]
        if not matches:
            raise ValueError(f"Preset '{old_name}' not found in preset table")
        if occurrence >= len(matches):
            raise IndexError(f"Occurrence {occurrence} out of range for preset '{old_name}'")
        target = matches[occurrence]
        self.patch_fixed_string(target.name_offset, target.name_size, new_name, "ascii")
        return BinaryString(offset=target.name_offset, raw_length=target.name_size, value=new_name, encoding="ascii")

    def set_song_slots(self, song_index: int, preset_slot_ids: list[int]) -> SongRecord:
        if not (1 <= song_index <= self.layout.song_count):
            raise ValueError(f"Song index must be between 1 and {self.layout.song_count}")
        if len(preset_slot_ids) != self.layout.song_slot_count:
            raise ValueError(f"Expected exactly {self.layout.song_slot_count} preset slot IDs")
        for preset_id in preset_slot_ids:
            if not (0 <= preset_id <= self.layout.preset_count):
                raise ValueError(f"Preset slot ID {preset_id} is out of range")
        offset = self.layout.song_base + ((song_index - 1) * self.layout.song_stride)
        slot_offset = offset + self.layout.song_name_size + self.layout.song_flags_size
        self._data[slot_offset : slot_offset + self.layout.song_slot_count] = bytes(preset_slot_ids)
        return self.parse_songs()[song_index - 1]

    def set_song_slots_by_name(self, song_name: str, preset_slot_ids: list[int]) -> SongRecord:
        song = next((item for item in self.parse_songs() if item.name == song_name), None)
        if song is None:
            raise ValueError(f"Song '{song_name}' not found in song table")
        return self.set_song_slots(song.index, preset_slot_ids)

    def set_setlist_song_ids(self, setlist_index: int, song_ids: list[int]) -> SetlistRecord:
        if not (1 <= setlist_index <= self.layout.setlist_count):
            raise ValueError(f"Setlist index must be between 1 and {self.layout.setlist_count}")
        if len(song_ids) > self.layout.setlist_slots_per_list:
            raise ValueError(f"Setlist can contain at most {self.layout.setlist_slots_per_list} songs")
        for song_id in song_ids:
            if not (0 <= song_id <= self.layout.song_count):
                raise ValueError(f"Song ID {song_id} is out of range")

        slot_bytes = self.layout.setlist_slots_per_list * 4
        entries_offset = self.layout.setlist_slots_base + ((setlist_index - 1) * slot_bytes)
        payload = bytearray(slot_bytes)
        for item_index, song_id in enumerate(song_ids):
            start = item_index * 4
            payload[start : start + 4] = int(song_id).to_bytes(4, byteorder="little", signed=False)
        self._data[entries_offset : entries_offset + slot_bytes] = payload
        return self.parse_setlists()[setlist_index - 1]

    def set_setlist_song_ids_by_name(self, setlist_name: str, song_ids: list[int]) -> SetlistRecord:
        setlist = next((item for item in self.parse_setlists() if item.name == setlist_name), None)
        if setlist is None:
            raise ValueError(f"Setlist '{setlist_name}' not found in setlist table")
        return self.set_setlist_song_ids(setlist.index, song_ids)

    def patch_fixed_string(self, offset: int, raw_length: int, text: str, encoding: str = "ascii") -> None:
        encoded = text.encode(encoding)
        if len(encoded) > raw_length:
            raise ValueError(
                f"Replacement '{text}' is too long for region of {raw_length} bytes at 0x{offset:08X}"
            )
        padded = encoded + (b"\x00" * (raw_length - len(encoded)))
        self._data[offset : offset + raw_length] = padded

    def iter_midi_messages(self) -> Iterable[MidiMessage]:
        for offset in range(len(self._data) - 2):
            midi = self._decode_midi_message(offset)
            if midi is not None:
                yield midi

    def find_control_change_messages(self, cc_number: int | None = None) -> list[MidiMessage]:
        messages = [item for item in self.iter_midi_messages() if item.is_control_change]
        if cc_number is not None:
            messages = [item for item in messages if item.data_1 == cc_number]
        return messages

    def find_encoder_candidates(self) -> list[EncoderCandidate]:
        strings = self.extract_strings(min_length=3)
        midi_messages = list(self.iter_midi_messages())
        candidates: list[EncoderCandidate] = []

        for item in strings:
            normalized = item.value.upper()
            if "EC1" not in normalized and "EC2" not in normalized and "PUSH" not in normalized:
                continue

            nearby = [msg for msg in midi_messages if abs(msg.offset - item.offset) <= 96 and msg.is_control_change]
            if not nearby:
                continue

            rotation = next((msg for msg in nearby if "PUSH" not in normalized), nearby[0])
            push = next((msg for msg in nearby if "PUSH" in normalized), None)
            candidates.append(
                EncoderCandidate(
                    offset=item.offset,
                    label=item.value,
                    rotation=rotation,
                    push=push,
                )
            )
        return candidates

    def patch_control_change(self, offset: int, cc_number: int, cc_value: int, channel: int | None = None) -> None:
        status = self._data[offset]
        if (status & 0xF0) != 0xB0:
            raise ValueError(f"Offset 0x{offset:08X} does not point to a Control Change status byte")
        if not (0 <= cc_number <= 127 and 0 <= cc_value <= 127):
            raise ValueError("CC number and value must be in MIDI 7-bit range (0-127)")
        if channel is not None:
            if not (1 <= channel <= 16):
                raise ValueError("MIDI channel must be between 1 and 16")
            self._data[offset] = 0xB0 | (channel - 1)
        self._data[offset + 1] = cc_number
        self._data[offset + 2] = cc_value

    def patch_preset_control_change(self, preset_index: int, command_index: int, cc_number: int, cc_value: int) -> MidiMessage:
        preset = self.parse_presets()[preset_index - 1]
        if command_index < 1 or command_index > len(preset.commands):
            raise IndexError(f"Preset command index {command_index} is out of range for preset {preset.name}")
        command = preset.commands[command_index - 1]
        if command.midi is None or not command.midi.is_control_change:
            raise ValueError(
                f"Command {command_index} in preset '{preset.name}' at 0x{command.offset:08X} is not a Control Change slot"
            )
        self.patch_control_change(command.offset, cc_number=cc_number, cc_value=cc_value)
        return self._decode_midi_message(command.offset)  # type: ignore[return-value]

    def patch_song_preset_control_change(
        self,
        song_name: str,
        song_slot: int,
        command_index: int,
        cc_number: int,
        cc_value: int,
    ) -> tuple[SongRecord, PresetRecord, MidiMessage]:
        songs = self.parse_songs()
        song = next((item for item in songs if item.name == song_name), None)
        if song is None:
            raise ValueError(f"Song '{song_name}' not found in song table")
        if not (1 <= song_slot <= self.layout.song_slot_count):
            raise ValueError(f"Song slot must be between 1 and {self.layout.song_slot_count}")
        preset_index = song.preset_slot_ids[song_slot - 1]
        if preset_index == 0:
            raise ValueError(f"Song '{song_name}' slot {song_slot} is empty")
        midi = self.patch_preset_control_change(
            preset_index=preset_index,
            command_index=command_index,
            cc_number=cc_number,
            cc_value=cc_value,
        )
        preset = self.parse_presets()[preset_index - 1]
        return song, preset, midi

    def find_song_slot_blocks(self, anchor_text: str | None = None, slot_count: int = 10) -> list[dict]:
        songs = self.parse_songs()
        presets = {item.index: item.name for item in self.parse_presets()}
        blocks: list[dict] = []
        for song in songs:
            if anchor_text and anchor_text.lower() not in song.name.lower():
                continue
            blocks.append(
                {
                    "song_name": song.name,
                    "string_offset": song.name_offset,
                    "slot_ids": song.preset_slot_ids[:slot_count],
                    "slot_names": [presets.get(slot_id, "") if slot_id else "" for slot_id in song.preset_slot_ids[:slot_count]],
                }
            )
        return blocks

    def _decode_midi_message(self, offset: int) -> MidiMessage | None:
        if offset + 2 >= len(self._data):
            return None
        status = self._data[offset]
        if (status & 0xF0) not in (0xB0, 0xC0):
            return None
        channel = (status & 0x0F) + 1
        return MidiMessage(
            offset=offset,
            status=status,
            data_1=self._data[offset + 1],
            data_2=self._data[offset + 2],
            channel=channel,
        )

    def _extract_ascii_strings(self, min_length: int) -> list[BinaryString]:
        results: list[BinaryString] = []
        start: int | None = None
        buffer = bytearray()
        for index, value in enumerate(self._data):
            if value in PRINTABLE:
                if start is None:
                    start = index
                buffer.append(value)
                continue
            if start is not None and len(buffer) >= min_length:
                results.append(
                    BinaryString(
                        offset=start,
                        raw_length=len(buffer),
                        value=buffer.decode("ascii"),
                        encoding="ascii",
                    )
                )
            start = None
            buffer.clear()
        if start is not None and len(buffer) >= min_length:
            results.append(
                BinaryString(
                    offset=start,
                    raw_length=len(buffer),
                    value=buffer.decode("ascii"),
                    encoding="ascii",
                )
            )
        return results

    def _extract_utf16le_strings(self, min_length: int) -> list[BinaryString]:
        results: list[BinaryString] = []
        index = 0
        data = self._data
        size = len(data)
        while index < size - 1:
            start = index
            chars: list[int] = []
            while index < size - 1:
                low = data[index]
                high = data[index + 1]
                if high != 0x00 or low not in PRINTABLE:
                    break
                chars.append(low)
                index += 2
            if len(chars) >= min_length:
                results.append(
                    BinaryString(
                        offset=start,
                        raw_length=len(chars) * 2,
                        value=bytes(chars).decode("ascii"),
                        encoding="utf-16-le",
                    )
                )
            index = start + 1 if not chars else index + 2
        return results
