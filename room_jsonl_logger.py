from __future__ import annotations

import json
import logging
import struct
from dataclasses import fields, is_dataclass
from collections import deque
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

try:
    import orjson as _orjson  # optional fast, compact serializer
except Exception:
    _orjson = None

from config import Config

logger = logging.getLogger('quadball')


def _quantize_float16(value: float) -> float:
    """Round to IEEE-754 binary16 and return as Python float."""
    try:
        return float(struct.unpack('<e', struct.pack('<e', float(value)))[0])
    except Exception:
        return 0.0


def _quantize_int16(value: int) -> int:
    """Clamp to signed int16 range."""
    if value > 32767:
        return 32767
    if value < -32768:
        return -32768
    return int(value)

def _serialize_for_jsonl(obj, _seen: Optional[set[int]] = None):
    """Serialize recursively while compacting all numeric values to 16-bit precision."""
    if _seen is None:
        _seen = set()

    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return _quantize_float16(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return _serialize_for_jsonl(obj.value, _seen)

    obj_id = id(obj)
    if obj_id in _seen:
        return None

    if isinstance(obj, dict):
        _seen.add(obj_id)
        try:
            return {str(k): _serialize_for_jsonl(v, _seen) for k, v in obj.items()}
        finally:
            _seen.discard(obj_id)
    if isinstance(obj, (list, tuple, set, deque)):
        _seen.add(obj_id)
        try:
            return [_serialize_for_jsonl(v, _seen) for v in obj]
        finally:
            _seen.discard(obj_id)

    if hasattr(obj, '__dict__'):
        _seen.add(obj_id)
        try:
            data = {}
            for key, value in vars(obj).items():
                if callable(value) or key.startswith('_'):
                    continue
                data[str(key)] = _serialize_for_jsonl(value, _seen)
            return data
        finally:
            _seen.discard(obj_id)

    return str(obj)


class RoomJsonlLogger:
    """Handles compact JSONL logging for a single room."""

    def __init__(self, room):
        self.room_id = room.room_id
        self.enabled = bool(getattr(Config, 'JSONL_LOGGING_ENABLED', True))
        self.state_file = None
        self.cpu_file = None
        self._header_written = False
        self._initial_state_snapshot_written = False

        try:
            created_stamp = room.created_at.strftime('%Y%m%dT%H%M%S')
            logs_dir = Path('game_data') / 'logs'
            logs_dir.mkdir(parents=True, exist_ok=True)
            base_name = f"room_{room.room_id}_{created_stamp}"

            state_path = logs_dir / f"{base_name}_state.jsonl"
            cpu_path = logs_dir / f"{base_name}_cpu_moves.jsonl"

            self.state_file = state_path.open('a', encoding='utf-8', buffering=1024 * 1024)
            self.cpu_file = cpu_path.open('a', encoding='utf-8', buffering=1024 * 1024)

        except Exception:
            logger.exception('Failed to initialize JSONL room logger for room=%s', room.room_id)
            self.enabled = False
            self.close()

        if not self.enabled:
            return

    def _extract_structure(self, value, dynamic_only: bool = False, _type_registry: Optional[dict] = None) -> dict:
        """Extract the nested structure and build a type registry for all encountered classes."""
        if _type_registry is None:
            _type_registry = {}
        
        if value is None or isinstance(value, (str, bool, int, float, datetime, Enum)):
            return None

        # Use dynamic serialization to get the actual structure being logged.
        if dynamic_only and hasattr(value, 'serialize_dynamic_attributes'):
            value = value.serialize_dynamic_attributes()

        if isinstance(value, dict):
            keys = list(value.keys())
            return {'type': 'dict', 'keys': keys, 'element_structures': [self._extract_structure(value[k], dynamic_only, _type_registry) for k in keys]}
        if isinstance(value, (list, tuple, set, deque)):
            # For sequences, just capture the structure of the first element.
            if value:
                return {'type': 'sequence', 'element_structure': self._extract_structure(list(value)[0], dynamic_only, _type_registry)}
            return {'type': 'sequence'}
        if is_dataclass(value) or hasattr(value, '__dict__'):
            if is_dataclass(value):
                field_names = [field.name for field in fields(value)]
            else:
                field_names = [key for key in vars(value).keys() if not key.startswith('_') and not callable(getattr(value, key))]
            class_name = f"{value.__class__.__module__}.{value.__class__.__qualname__}"
            
            # Register this type and its fields once.
            if class_name not in _type_registry:
                _type_registry[class_name] = {
                    'fields': field_names,
                    'field_structures': {k: self._extract_structure(getattr(value, k, None), dynamic_only, _type_registry) for k in field_names}
                }
            else:
                # Ensure nested structures are also registered for already-seen types.
                for k in field_names:
                    self._extract_structure(getattr(value, k, None), dynamic_only, _type_registry)
            
            return {'type': 'object', 'class': class_name}
        return None
    
    def _build_structure_with_registry(self, value, dynamic_only: bool = False) -> Tuple[dict, dict]:
        """Build structure map and type registry, returning (structure, type_registry)."""
        type_registry = {}
        structure = self._extract_structure(value, dynamic_only, type_registry)
        return structure, type_registry

    def _collect_ordered_key_schema(self, value, path: str, dynamic_only: bool = False, _schema: Optional[list[dict]] = None, _seen: Optional[set[int]] = None) -> list[dict]:
        """Collect ordered keys/fields using the same traversal and ordering as _serialize_value."""
        if _schema is None:
            _schema = []
        if _seen is None:
            _seen = set()

        if value is None or isinstance(value, (str, bool, int, float, datetime, Enum)):
            return _schema

        if dynamic_only and hasattr(value, 'serialize_dynamic_attributes'):
            value = value.serialize_dynamic_attributes()

        obj_id = id(value)
        if obj_id in _seen:
            return _schema

        if isinstance(value, dict):
            keys = list(value.keys())
            _schema.append({'path': path, 'kind': 'dict', 'keys': [str(key) for key in keys]})
            _seen.add(obj_id)
            try:
                for index, key in enumerate(keys):
                    self._collect_ordered_key_schema(value[key], f"{path}.{index}", dynamic_only=dynamic_only, _schema=_schema, _seen=_seen)
            finally:
                _seen.discard(obj_id)
            return _schema

        if isinstance(value, (list, tuple, set, deque)):
            _schema.append({'path': path, 'kind': 'sequence'})
            _seen.add(obj_id)
            try:
                for index, item in enumerate(value):
                    self._collect_ordered_key_schema(item, f"{path}.{index}", dynamic_only=dynamic_only, _schema=_schema, _seen=_seen)
            finally:
                _seen.discard(obj_id)
            return _schema

        if is_dataclass(value) or hasattr(value, '__dict__'):
            if is_dataclass(value):
                field_names = [field.name for field in fields(value)]
            else:
                field_names = [key for key in vars(value).keys() if not key.startswith('_') and not callable(getattr(value, key))]

            _schema.append({
                'path': path,
                'kind': 'object',
                'name': f"{value.__class__.__module__}.{value.__class__.__qualname__}",
                'keys': field_names,
            })
            _seen.add(obj_id)
            try:
                for key in field_names:
                    self._collect_ordered_key_schema(getattr(value, key, None), f"{path}.{key}", dynamic_only=dynamic_only, _schema=_schema, _seen=_seen)
            finally:
                _seen.discard(obj_id)

        return _schema

    def _serialize_scalar(self, value):
        if value is None or isinstance(value, (str, bool)):
            return value
        if isinstance(value, int):
            return _quantize_int16(value)
        if isinstance(value, float):
            return _quantize_float16(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Enum):
            return self._serialize_scalar(value.value)
        return str(value)

    def _serialize_value(self, value, path: str, dynamic_only: bool = False):
        if value is None or isinstance(value, (str, bool, int, float, datetime, Enum)):
            return self._serialize_scalar(value)

        # For incremental game logs, prefer explicit dynamic serialization when available.
        if dynamic_only and hasattr(value, 'serialize_dynamic_attributes'):
            value = value.serialize_dynamic_attributes()

        if isinstance(value, dict):
            keys = list(value.keys())
            return [self._serialize_value(value[key], f"{path}.{index}", dynamic_only=dynamic_only) for index, key in enumerate(keys)]
        if isinstance(value, (list, tuple, set, deque)):
            return [self._serialize_value(item, f"{path}.{index}", dynamic_only=dynamic_only) for index, item in enumerate(value)]
        if is_dataclass(value) or hasattr(value, '__dict__'):
            if is_dataclass(value):
                field_names = [field.name for field in fields(value)]
            else:
                field_names = [key for key in vars(value).keys() if not key.startswith('_') and not callable(getattr(value, key))]
            return [self._serialize_value(getattr(value, key, None), f"{path}.{key}", dynamic_only=dynamic_only) for key in field_names]
        return self._serialize_scalar(value)

    def _ensure_header_written(self, room) -> None:
        if self._header_written or not self.enabled:
            return

        # Build snapshots and extract structures with type registry before writing metadata.
        _ = self._serialize_value(room.game_state, 'game_state', dynamic_only=False)
        _ = self._serialize_value(room.game_state, 'game_state', dynamic_only=True)
        full_structure, full_type_registry = self._build_structure_with_registry(room.game_state, dynamic_only=False)
        dynamic_structure, dynamic_type_registry = self._build_structure_with_registry(room.game_state, dynamic_only=True)
        full_ordered_key_schema = self._collect_ordered_key_schema(room.game_state, 'game_state', dynamic_only=False)
        dynamic_ordered_key_schema = self._collect_ordered_key_schema(room.game_state, 'game_state', dynamic_only=True)

        metadata = {
            'event': 'room_metadata',
            'room_id': room.room_id,
            'created_at': room.created_at,
            'creator_id': room.creator_id,
            'creator_name': room.creator_name,
            'passkey': room.passkey,
            'max_players': room.max_players,
            'cpu_player_class': getattr(room.computer_player_class, '__name__', str(room.computer_player_class)),
            'config': {
                'fps': Config.FPS,
                'game_time_to_real_time_ratio': Config.GAME_TIME_TO_REAL_TIME_RATIO,
                'pitch_length': Config.PITCH_LENGTH,
                'pitch_width': Config.PITCH_WIDTH,
            },
            'state_record_keys': ['tick', 'game_state'],
            'game_state_structure': full_structure,
            'game_state_types': full_type_registry,
            'game_state_ordered_key_schema': full_ordered_key_schema,
            'game_state_dynamic_structure': dynamic_structure,
            'game_state_dynamic_types': dynamic_type_registry,
            'game_state_dynamic_ordered_key_schema': dynamic_ordered_key_schema,
            'cpu_move_record_keys': ['cpu_move_tick', 'game_time', 'cpu_moves'],
            'cpu_move_keys': ['player_id', 'direction_x', 'direction_y'],
        }
        self._write_line(self.state_file, metadata)
        self._write_line(self.cpu_file, metadata)
        self._header_written = True

    def _write_line(self, file_obj, payload: dict) -> None:
        if not self.enabled or file_obj is None:
            return
        compact_payload = _serialize_for_jsonl(payload)
        try:
            if _orjson is not None:
                file_obj.write(_orjson.dumps(compact_payload).decode('utf-8'))
            else:
                file_obj.write(json.dumps(compact_payload, separators=(',', ':'), ensure_ascii=False))
            file_obj.write('\n')
        except Exception:
            logger.exception('Failed to write JSONL payload for room=%s', self.room_id)

    def log_game_state_snapshot(self, room) -> None:
        if not self.enabled:
            return
        self._ensure_header_written(room)
        if not self._initial_state_snapshot_written:
            game_state_payload = self._serialize_value(room.game_state, 'game_state', dynamic_only=False)
            self._initial_state_snapshot_written = True
        else:
            game_state_payload = self._serialize_value(room.game_state, 'game_state', dynamic_only=True)

        payload = [
            _serialize_for_jsonl(room.game_tick_count),
            game_state_payload,
        ]
        self._write_line(self.state_file, payload)

    def log_cpu_move_snapshot(self, room) -> None:
        if not self.enabled:
            return
        self._ensure_header_written(room)
        cpu_moves = []
        for cpu_player_id in room.cpu_player_ids:
            player = room.game_state.get_player(cpu_player_id)
            if player is None:
                continue
            cpu_moves.append([
                cpu_player_id,
                _serialize_for_jsonl(getattr(getattr(player, 'direction', None), 'x', 0.0)),
                _serialize_for_jsonl(getattr(getattr(player, 'direction', None), 'y', 0.0)),
            ])

        payload = [
            _serialize_for_jsonl(room.cpu_move_tick_count),
            _serialize_for_jsonl(room.game_state.game_time),
            cpu_moves,
        ]
        self._write_line(self.cpu_file, payload)

    def close(self) -> None:
        if self.state_file is not None:
            try:
                self.state_file.close()
            except Exception:
                pass
            self.state_file = None
        if self.cpu_file is not None:
            try:
                self.cpu_file.close()
            except Exception:
                pass
            self.cpu_file = None