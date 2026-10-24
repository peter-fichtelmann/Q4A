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

from core.entities import Ball, BallType, DodgeBall, FlagRunner, Hoop, Player, PlayerRole, Vector2, VolleyBall
from core.game_state import GameState

try:
    import orjson as _orjson  # optional fast, compact serializer
except Exception:
    _orjson = None

from config import Config

logger = logging.getLogger('quadball')

_STATE_RECORD_KIND_FULL = 0
_STATE_RECORD_KIND_KEYFRAME = 1
_STATE_RECORD_KIND_DELTA = 2
_DYNAMIC_KEYFRAME_INTERVAL_TICKS = 200
_SPARSE_LIST_KEY = '_'
_OMIT = object()

def _object_field_names(value) -> list[str]:
    """Ordered attribute names used to encode an object positionally.

    Dataclass fields come first, followed by any extra instance attributes assigned
    outside the dataclass machinery. VolleyBall, DodgeBall and FlagRunner all subclass
    a dataclass with a hand written __init__, so without the second part their own
    attributes would never reach the log.
    """
    if is_dataclass(value):
        field_names = [field.name for field in fields(value)]
        known_field_names = set(field_names)
        field_names.extend(
            key for key in vars(value)
            if key not in known_field_names and not key.startswith('_') and not callable(getattr(value, key, None))
        )
        return field_names
    return [key for key in vars(value).keys() if not key.startswith('_') and not callable(getattr(value, key))]


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


def _is_leaf_list_template(value) -> bool:
    if not isinstance(value, list):
        return False
    return all(not isinstance(item, list) for item in value)


def _decode_vector2_payload(payload) -> Vector2:
    if isinstance(payload, Vector2):
        return payload.copy()
    if isinstance(payload, dict):
        return Vector2(float(payload.get('x', 0.0)), float(payload.get('y', 0.0)))
    if isinstance(payload, list) and len(payload) >= 2:
        return Vector2(float(payload[0]), float(payload[1]))
    return Vector2(0.0, 0.0)


def _decode_player_full_payload(payload) -> Player:
    if isinstance(payload, Player):
        return payload.copy()

    if not isinstance(payload, list):
        raise ValueError('Invalid player payload')

    return Player(
        id=str(payload[0]),
        team=int(payload[1]),
        role=PlayerRole(payload[2]),
        position=_decode_vector2_payload(payload[3]),
        previous_position=_decode_vector2_payload(payload[4]),
        direction=_decode_vector2_payload(payload[5]),
        velocity=_decode_vector2_payload(payload[6]),
        radius=float(payload[7]),
        is_knocked_out=bool(payload[8]),
        has_ball=payload[9], # id of the held ball, or False/None
        max_speed=float(payload[10]),
        min_speed=float(payload[11]),
        acceleration=float(payload[12]),
        deacceleration_rate=float(payload[13]),
        min_dir=float(payload[14]),
        throw_velocity=float(payload[15]),
        catch_cooldown=float(payload[16]),
        dodgeball_immunity=bool(payload[17]),
        inbounding=payload[18],
        in_contact_player_ids=list(payload[19]) if isinstance(payload[19], list) else [],
        tackling_player_ids=list(payload[20]) if isinstance(payload[20], list) else [],
        is_receiving_turnover_ball=bool(payload[21]),
        flag_runner_interaction_time=float(payload[22]) if len(payload) > 22 and payload[22] is not None else 0.0,
        is_claiming=bool(payload[23]) if len(payload) > 23 else False,
    )


def _decode_flag_runner_full_payload(payload) -> FlagRunner:
    if isinstance(payload, FlagRunner):
        return payload.copy()

    if not isinstance(payload, list):
        raise ValueError('Invalid flag runner payload')

    # Indices 0-9 are the inherited Referee dataclass fields, 10-14 the FlagRunner
    # attributes set in its __init__ (same order the serializer walks them in).
    return FlagRunner(
        id=str(payload[0]),
        position=_decode_vector2_payload(payload[1]),
        direction=_decode_vector2_payload(payload[2]),
        velocity=_decode_vector2_payload(payload[3]),
        max_speed=float(payload[4]),
        min_speed=float(payload[5]),
        radius=float(payload[6]),
        acceleration=float(payload[7]),
        deacceleration_rate=float(payload[8]),
        min_dir=float(payload[9]),
        seeker_avoidance_factor=float(payload[10]) if len(payload) > 10 else 1.0,
        boundary_avoidance_factor=float(payload[11]) if len(payload) > 11 else 1.0,
        boundary_epsilon=float(payload[12]) if len(payload) > 12 else 1e-5,
        interaction_time_threshold=float(payload[13]) if len(payload) > 13 else 1.0,
        catch_probability=float(payload[14]) if len(payload) > 14 else 0.05,
    )


def _decode_ball_full_payload(payload) -> Ball:
    if isinstance(payload, Ball):
        return payload.copy()

    if not isinstance(payload, list):
        raise ValueError('Invalid ball payload')

    ball_type = BallType(payload[1]) if not isinstance(payload[1], BallType) else payload[1]
    base_kwargs = dict(
        id=str(payload[0]),
        radius=float(payload[2]),
        position=_decode_vector2_payload(payload[3]),
        previous_position=_decode_vector2_payload(payload[4]),
        velocity=_decode_vector2_payload(payload[5]),
        deacceleration_rate=float(payload[6]),
        possession_team=payload[7],
        holder_id=payload[8],
        previous_thrower_id=payload[9],
        reflect_velocity_loss=float(payload[10]),
        turnover_to_player=payload[11],
    )

    if ball_type == BallType.VOLLEYBALL:
        return VolleyBall(
            id=base_kwargs['id'],
            radius=base_kwargs['radius'],
            position=base_kwargs['position'],
            crossed_hoop=payload[12] if len(payload) > 12 else None,
            inbounder=payload[13] if len(payload) > 13 else None,
            is_dead=bool(payload[14]) if len(payload) > 14 else False,
            delay_of_game_timer=float(payload[15]) if len(payload) > 15 else 0.0,
            stalled_timer=float(payload[16]) if len(payload) > 16 and payload[16] is not None else 0.0,
            # infinity (never tackled) reaches the log as null with orjson
            time_since_carrier_tackled=float(payload[17]) if len(payload) > 17 and payload[17] is not None else float('inf'),
            previous_position=base_kwargs['previous_position'],
            velocity=base_kwargs['velocity'],
            deacceleration_rate=base_kwargs['deacceleration_rate'],
            possession_team=base_kwargs['possession_team'],
            holder_id=base_kwargs['holder_id'],
            previous_thrower_id=base_kwargs['previous_thrower_id'],
            reflect_velocity_loss=base_kwargs['reflect_velocity_loss'],
            turnover_to_player=base_kwargs['turnover_to_player'],
        )

    if ball_type == BallType.DODGEBALL:
        return DodgeBall(
            id=base_kwargs['id'],
            radius=base_kwargs['radius'],
            position=base_kwargs['position'],
            beat_attempt_time=float(payload[12]) if len(payload) > 12 else 0.0,
            dead_velocity_threshold=float(payload[13]) if len(payload) > 13 else 0.0,
            previous_position=base_kwargs['previous_position'],
            velocity=base_kwargs['velocity'],
            deacceleration_rate=base_kwargs['deacceleration_rate'],
            possession_team=base_kwargs['possession_team'],
            holder_id=base_kwargs['holder_id'],
            previous_thrower_id=base_kwargs['previous_thrower_id'],
            reflect_velocity_loss=base_kwargs['reflect_velocity_loss'],
            turnover_to_player=base_kwargs['turnover_to_player'],
        )

    return Ball(ball_type=ball_type, **base_kwargs)


def _decode_hoop_full_payload(payload) -> Hoop:
    if isinstance(payload, Hoop):
        return payload.copy()

    if not isinstance(payload, list):
        raise ValueError('Invalid hoop payload')

    return Hoop(
        id=str(payload[0]),
        team=int(payload[1]),
        position=_decode_vector2_payload(payload[2]),
        radius=float(payload[3]),
        thickness=float(payload[4]),
    )


def _serialize_scalar(value):
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return _quantize_int16(value)
    if isinstance(value, float):
        return _quantize_float16(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return _serialize_scalar(value.value)
    return str(value)


def _serialize_value(value, dynamic_only: bool = False):
    """Positional encoding of every state record; the reader uses it too, to rebuild its snapshots."""
    if value is None or isinstance(value, (str, bool, int, float, datetime, Enum)):
        return _serialize_scalar(value)

    # For incremental game logs, prefer explicit dynamic serialization when available.
    if dynamic_only and hasattr(value, 'serialize_dynamic_attributes'):
        value = value.serialize_dynamic_attributes()

    if isinstance(value, dict):
        return [_serialize_value(item, dynamic_only=dynamic_only) for item in value.values()]
    if isinstance(value, (list, tuple, set, deque)):
        return [_serialize_value(item, dynamic_only=dynamic_only) for item in value]
    if is_dataclass(value) or hasattr(value, '__dict__'):
        return [_serialize_value(getattr(value, key, None), dynamic_only=dynamic_only) for key in _object_field_names(value)]
    return _serialize_scalar(value)


def _keyframe_template(snapshot, legacy: bool = False):
    """
    Values a keyframe leaves out, shaped like `snapshot` (the previous dynamic snapshot).

    Keyframes omit None scalars and all-default leaf lists (empty id lists, zero vectors, unset id pairs).
    `legacy` logs (header without 'dynamic_keyframe_omits') also omitted False and 0 scalars: those come
    back as False/0.0 for bool and float fields, but a nullable int (e.g. possession_team 0) reads as None.
    """
    if isinstance(snapshot, list):
        if _is_leaf_list_template(snapshot):
            if any(isinstance(item, str) for item in snapshot):
                return [] # id list
            if snapshot and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in snapshot):
                return [0.0 if isinstance(item, float) else 0 for item in snapshot]
            return [None] * len(snapshot)
        return [_keyframe_template(item, legacy) for item in snapshot]
    if legacy and isinstance(snapshot, bool):
        return False
    if legacy and isinstance(snapshot, float):
        return 0.0
    return None


def _apply_dynamic_value(current, payload):
    """
    Write a dynamic payload back into `current` and return the updated value.

    Mirrors _serialize_value(dynamic_only=True): objects follow the key order of their
    serialize_dynamic_attributes(), dicts their key order. Shorter payloads written before
    a key was appended leave the remaining attributes untouched.
    """
    if hasattr(current, 'serialize_dynamic_attributes'):
        if isinstance(payload, list):
            for key, item in zip(current.serialize_dynamic_attributes().keys(), payload):
                setattr(current, key, _apply_dynamic_value(getattr(current, key, None), item))
        return current
    if isinstance(current, Vector2):
        if isinstance(payload, list) and len(payload) >= 2:
            current.x = float(payload[0])
            current.y = float(payload[1])
        return current
    if isinstance(current, dict):
        if not isinstance(payload, list):
            return payload
        for index, key in enumerate(list(current.keys())):
            # a keyframe template cannot tell an unset id pair from an empty id list, so missing values are None
            current[key] = _apply_dynamic_value(current[key], payload[index] if index < len(payload) else None)
        return current
    if isinstance(current, list):
        if not isinstance(payload, list):
            return payload
        if current and all(hasattr(item, 'serialize_dynamic_attributes') for item in current):
            for item, item_payload in zip(current, payload):
                _apply_dynamic_value(item, item_payload)
            return current
        return list(payload)
    return payload


def _apply_sparse_snapshot(template, sparse):
    """
    Apply a sparse record to `template` and return the new snapshot.

    Only the lists along changed paths are copied; unchanged branches are shared with `template`,
    so snapshots must be treated as immutable. Any value that is not a sparse list replaces the
    old one, e.g. None replacing a former leaf list.
    """
    if sparse is _OMIT:
        return template

    if isinstance(sparse, dict) and _SPARSE_LIST_KEY in sparse:
        result = list(template) if isinstance(template, list) else []
        for index, item in sparse[_SPARSE_LIST_KEY]:
            index = int(index)
            while len(result) <= index: # the list grew (e.g. a player joined)
                result.append(None)
            result[index] = _apply_sparse_snapshot(result[index], item)
        return result

    return sparse

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
        self._previous_dynamic_snapshot = None
        self._last_dynamic_keyframe_tick = None

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

    @staticmethod
    def _is_default_scalar(value) -> bool:
        if value is None or value is False:
            return True
        if isinstance(value, (int, float)):
            return value == 0
        return False

    @staticmethod
    def _is_leaf_list(value) -> bool:
        if not isinstance(value, list):
            return False
        for item in value:
            if isinstance(item, list):
                return False
        return True

    def _is_default_leaf_list(self, value: list) -> bool:
        if len(value) == 0:
            return True
        return all(self._is_default_scalar(item) for item in value)

    def _sparsify_snapshot(self, value, omit_defaults: bool):
        if isinstance(value, list):
            if self._is_leaf_list(value):
                if omit_defaults and self._is_default_leaf_list(value):
                    return _OMIT
                return value

            entries = []
            for index, item in enumerate(value):
                sparse_item = self._sparsify_snapshot(item, omit_defaults=omit_defaults)
                if sparse_item is _OMIT:
                    continue
                entries.append([index, sparse_item])

            if not entries:
                return _OMIT if omit_defaults else {_SPARSE_LIST_KEY: []}
            return {_SPARSE_LIST_KEY: entries}

        # only None: a left out False or 0 could not be told apart from None (e.g. possession_team 0) when reading
        if omit_defaults and value is None:
            return _OMIT
        return value

    def _build_sparse_delta(self, previous, current):
        if isinstance(current, list):
            if self._is_leaf_list(current):
                if previous == current:
                    return _OMIT
                return current

            if not isinstance(previous, list) or len(previous) != len(current):
                return self._sparsify_snapshot(current, omit_defaults=False)

            entries = []
            for index, current_item in enumerate(current):
                delta_item = self._build_sparse_delta(previous[index], current_item)
                if delta_item is _OMIT:
                    continue
                entries.append([index, delta_item])

            if not entries:
                return _OMIT
            return {_SPARSE_LIST_KEY: entries}

        if previous == current:
            return _OMIT
        return current

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
            field_names = _object_field_names(value)
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
            field_names = _object_field_names(value)

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

    def _ensure_header_written(self, room) -> None:
        if self._header_written or not self.enabled:
            return

        # Build snapshots and extract structures with type registry before writing metadata.
        _ = _serialize_value(room.game_state, dynamic_only=False)
        _ = _serialize_value(room.game_state, dynamic_only=True)
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
            'state_record_keys': ['tick', 'kind', 'game_state'],
            'state_record_kind_map': {
                'full': _STATE_RECORD_KIND_FULL,
                'dynamic_keyframe': _STATE_RECORD_KIND_KEYFRAME,
                'dynamic_delta': _STATE_RECORD_KIND_DELTA,
            },
            'dynamic_keyframe_interval_ticks': _DYNAMIC_KEYFRAME_INTERVAL_TICKS,
            'dynamic_sparse_list_key': _SPARSE_LIST_KEY,
            'dynamic_keyframe_omits': 'null', # older logs also omitted false and 0
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
            game_state_payload = _serialize_value(room.game_state, dynamic_only=False)
            self._initial_state_snapshot_written = True
            dynamic_snapshot = _serialize_value(room.game_state, dynamic_only=True)
            self._previous_dynamic_snapshot = dynamic_snapshot
            self._last_dynamic_keyframe_tick = int(_serialize_for_jsonl(room.game_tick_count))
            payload = [
                _serialize_for_jsonl(room.game_tick_count),
                _STATE_RECORD_KIND_FULL,
                game_state_payload,
            ]
        else:
            tick = int(_serialize_for_jsonl(room.game_tick_count))
            dynamic_snapshot = _serialize_value(room.game_state, dynamic_only=True)

            # Prefer stable interval boundaries (e.g. 200, 400, 600, ...) and
            # fall back to elapsed-distance emission if boundaries are skipped.
            is_interval_boundary = (tick > 0 and tick % _DYNAMIC_KEYFRAME_INTERVAL_TICKS == 0)
            should_emit_keyframe = (
                self._last_dynamic_keyframe_tick is None
                or (
                    is_interval_boundary
                    and tick != self._last_dynamic_keyframe_tick
                )
                or tick - self._last_dynamic_keyframe_tick >= _DYNAMIC_KEYFRAME_INTERVAL_TICKS
            )

            if should_emit_keyframe:
                sparse_payload = self._sparsify_snapshot(dynamic_snapshot, omit_defaults=True)
                if sparse_payload is _OMIT:
                    sparse_payload = {_SPARSE_LIST_KEY: []}
                payload = [
                    tick,
                    _STATE_RECORD_KIND_KEYFRAME,
                    sparse_payload,
                ]
                self._last_dynamic_keyframe_tick = tick
            else:
                delta_payload = self._build_sparse_delta(self._previous_dynamic_snapshot, dynamic_snapshot)
                if delta_payload is _OMIT:
                    delta_payload = {_SPARSE_LIST_KEY: []}
                payload = [
                    tick,
                    _STATE_RECORD_KIND_DELTA,
                    delta_payload,
                ]

            self._previous_dynamic_snapshot = dynamic_snapshot

        self._write_line(self.state_file, payload)

    def log_cpu_move_snapshot(self, room) -> None:
        if not self.enabled:
            return
        self._ensure_header_written(room)
        cpu_moves = []
        # The players the AI actually drove on the last move — this follows player
        # switches, unlike `cpu_player_ids` (the fixed set spawned at game start).
        driven_ids = getattr(room, 'last_cpu_driven_ids', None) or room.cpu_player_ids
        for cpu_player_id in driven_ids:
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

    @classmethod
    def load_game_state_at_tick(cls, state_file_path, tick: int) -> Optional[GameState]:
        return RoomJsonlStateReader(state_file_path).get_game_state_at_tick(tick)


class RoomJsonlStateReader:
    """Read a room state.jsonl file and reconstruct GameState snapshots."""

    def __init__(self, state_file_path):
        self.state_file_path = Path(state_file_path)
        self.metadata: Optional[dict] = None

    @staticmethod
    def _loads(line: str):
        if _orjson is not None:
            return _orjson.loads(line)
        return json.loads(line)

    def _iter_records(self):
        """Yield (tick, kind, payload) of the state records; the room metadata goes to self.metadata."""
        with self.state_file_path.open('r', encoding='utf-8') as handle:
            for line in handle:
                stripped_line = line.strip()
                if not stripped_line:
                    continue
                record = self._loads(stripped_line)
                if isinstance(record, dict) and record.get('event') == 'room_metadata':
                    self.metadata = record
                    continue
                if not isinstance(record, list) or len(record) < 3:
                    continue
                yield int(record[0]), int(record[1]), record[2]

    def _game_state_field_names(self) -> list[str]:
        """GameState field order of the full record: the one in the header, else the current dataclass."""
        try:
            return list(self.metadata['game_state_types']['core.game_state.GameState']['fields'])
        except (TypeError, KeyError):
            return [field.name for field in fields(GameState)]

    def _decode_game_state_full_payload(self, payload) -> GameState:
        state = GameState()
        if not isinstance(payload, list):
            return state

        field_names = self._game_state_field_names()
        for index, field_name in enumerate(field_names):
            if index >= len(payload):
                break
            value = payload[index]

            if field_name == 'players':
                state.players = {}
                if isinstance(value, list):
                    for player_payload in value:
                        try:
                            player = _decode_player_full_payload(player_payload)
                        except Exception:
                            continue
                        state.players[player.id] = player
                continue

            if field_name == 'keeper_team_0':
                try:
                    state.keeper_team_0 = _decode_player_full_payload(value) if value is not None else None
                except Exception:
                    state.keeper_team_0 = None
                continue

            if field_name == 'keeper_team_1':
                try:
                    state.keeper_team_1 = _decode_player_full_payload(value) if value is not None else None
                except Exception:
                    state.keeper_team_1 = None
                continue

            if field_name == 'balls':
                state.balls = {}
                if isinstance(value, list):
                    for ball_payload in value:
                        try:
                            ball = _decode_ball_full_payload(ball_payload)
                        except Exception:
                            continue
                        state.balls[ball.id] = ball
                continue

            if field_name == 'volleyball':
                try:
                    state.volleyball = _decode_ball_full_payload(value) if value is not None else None
                except Exception:
                    state.volleyball = None
                continue

            if field_name == 'dodgeballs':
                state.dodgeballs = []
                if isinstance(value, list):
                    for dodgeball_payload in value:
                        dodgeball = _decode_ball_full_payload(dodgeball_payload)
                        if isinstance(dodgeball, DodgeBall):
                            state.dodgeballs.append(dodgeball)
                continue

            if field_name == 'flag_runner':
                try:
                    state.flag_runner = _decode_flag_runner_full_payload(value) if value is not None else None
                except Exception:
                    state.flag_runner = None
                continue

            if field_name == 'hoops':
                state.hoops = {}
                if isinstance(value, list):
                    for hoop_payload in value:
                        hoop = _decode_hoop_full_payload(hoop_payload)
                        state.hoops[hoop.id] = hoop
                continue

            if field_name == 'delay_of_game_warnings':
                if isinstance(value, list):
                    state.delay_of_game_warnings = {
                        0: value[0] if len(value) > 0 else 0,
                        1: value[1] if len(value) > 1 else 0,
                    }
                continue

            if field_name == 'potential_third_dodgeball_interference_kwargs':
                if isinstance(value, list):
                    state.potential_third_dodgeball_interference_kwargs = {
                        'player_id': value[0] if len(value) > 0 else None,
                        'dodgeball_id': value[1] if len(value) > 1 else None,
                    }
                continue

            if field_name.startswith('squared_distances_'):
                continue

            setattr(state, field_name, value)

        if state.keeper_team_0 is not None:
            state.keeper_team_0 = state.players.get(state.keeper_team_0.id, state.keeper_team_0)
        if state.keeper_team_1 is not None:
            state.keeper_team_1 = state.players.get(state.keeper_team_1.id, state.keeper_team_1)
        if state.volleyball is not None and state.volleyball.id in state.balls:
            state.volleyball = state.balls[state.volleyball.id]
        if state.dodgeballs:
            normalized_dodgeballs = []
            for dodgeball in state.dodgeballs:
                normalized_dodgeballs.append(state.balls.get(dodgeball.id, dodgeball))
            state.dodgeballs = normalized_dodgeballs

        return state

    def _replay(self, start_tick: int = 0):
        """
        Yield (tick, state, dynamic_snapshot) per record, starting at the latest keyframe at or before
        `start_tick`. `state` is the decoded full record and is not updated here: apply the snapshot with
        _apply_dynamic_value(state, dynamic_snapshot) when a state is needed.
        """
        replay_start_tick = None
        for record_tick, record_kind, _ in self._iter_records():
            if record_tick > start_tick:
                break
            if record_kind == _STATE_RECORD_KIND_KEYFRAME:
                replay_start_tick = record_tick

        state: Optional[GameState] = None
        snapshot = None
        for record_tick, record_kind, payload in self._iter_records():
            if record_kind == _STATE_RECORD_KIND_FULL:
                state = self._decode_game_state_full_payload(payload)
                snapshot = _serialize_value(state, dynamic_only=True)
            elif state is None or (replay_start_tick is not None and record_tick < replay_start_tick):
                continue
            elif record_kind == _STATE_RECORD_KIND_KEYFRAME:
                legacy = (self.metadata or {}).get('dynamic_keyframe_omits') != 'null'
                snapshot = _apply_sparse_snapshot(_keyframe_template(snapshot, legacy), payload)
            elif record_kind == _STATE_RECORD_KIND_DELTA:
                snapshot = _apply_sparse_snapshot(snapshot, payload)
            else:
                continue
            yield record_tick, state, snapshot

    def get_game_state_at_tick(self, tick: int) -> Optional[GameState]:
        """State of the latest record at or before `tick`, or None."""
        if tick < 0 or not self.state_file_path.exists():
            return None

        state = None
        snapshot = None
        try:
            for record_tick, record_state, record_snapshot in self._replay(tick):
                if record_tick > tick:
                    break
                state, snapshot = record_state, record_snapshot
            if state is not None:
                _apply_dynamic_value(state, snapshot)
        except Exception:
            logger.exception('Failed to read JSONL state log from %s', self.state_file_path)
            return None
        return state

    def iter_game_states(self, start_tick: int = 0, end_tick: Optional[int] = None, every: int = 1):
        """
        Yield (tick, state) for the records from `start_tick` to `end_tick` (inclusive), keeping every
        `every`-th tick. A single GameState is updated in place, so copy whatever must outlive a step.
        """
        for record_tick, state, snapshot in self._replay(start_tick):
            if end_tick is not None and record_tick > end_tick:
                break
            if record_tick < start_tick or (record_tick - start_tick) % every:
                continue
            yield record_tick, _apply_dynamic_value(state, snapshot)
