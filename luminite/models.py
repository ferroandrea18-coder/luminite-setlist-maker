from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class MidiMapping:
    program_change: int | None = None
    bank_cc_0: int | None = None
    bank_cc_32: int | None = None
    control_change: int | None = None
    control_value: int | None = None
    channel: int = 1


@dataclass(slots=True)
class EncoderAssignment:
    cc_number: int
    cc_value: int
    push_cc_number: int | None = None
    push_cc_value: int | None = None


@dataclass(slots=True)
class MasterSound:
    name: str
    mapping: MidiMapping


@dataclass(slots=True)
class SongSection:
    name: str
    master_sound: str | None = None
    encoder_ec1: EncoderAssignment | None = None
    encoder_ec2: EncoderAssignment | None = None


@dataclass(slots=True)
class SongDefinition:
    name: str
    slots: list[SongSection] = field(default_factory=list)

    def ensure_six_slots(self) -> None:
        while len(self.slots) < 6:
            self.slots.append(SongSection(name=f"Slot {len(self.slots) + 1}"))
        self.slots[:] = self.slots[:6]


@dataclass(slots=True)
class SetlistDefinition:
    name: str
    song_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class UserRigLibrary:
    master_sounds: list[MasterSound] = field(default_factory=list)
    songs: list[SongDefinition] = field(default_factory=list)
    setlists: list[SetlistDefinition] = field(default_factory=list)
    source_path: Path | None = None
