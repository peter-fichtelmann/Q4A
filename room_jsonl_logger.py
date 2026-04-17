from __future__ import annotations

import json
import logging
import struct
from copy import deepcopy
from dataclasses import fields, is_dataclass
from collections import deque
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

from core.entities import Ball, BallType, DodgeBall, Hoop, Player, PlayerRole, Vector2, VolleyBall
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

_PLAYER_DYNAMIC_FIELD_NAMES = [
    'position',
    'previous_position',
    'direction',
    'velocity',
    'is_knocked_out',
    'has_ball',
    'catch_cooldown',
    'dodgeball_immunity',
    'inbounding',
    'in_contact_player_ids',
    'tackling_player_ids',
    'is_receiving_turnover_ball',
]

_BALL_DYNAMIC_FIELD_NAMES = [
    'position',
    'previous_position',
    'velocity',
    'possession_team',
    'holder_id',
    'previous_thrower_id',
    'turnover_to_player',
]

_VOLLEYBALL_DYNAMIC_FIELD_NAMES = _BALL_DYNAMIC_FIELD_NAMES + [
    'crossed_hoop',
    'inbounder',
    'is_dead',
    'delay_of_game_timer',
]

_DODGEBALL_DYNAMIC_FIELD_NAMES = _BALL_DYNAMIC_FIELD_NAMES + [
    'beat_attempt_time',
]

_GAME_STATE_DYNAMIC_FIELD_NAMES = [
    'players',
    'balls',
    'volleyball',
    'dodgeballs',
    'score',
    'game_time',
    'delay_of_game_warnings',
    'third_dodgeball',
    'third_dodgeball_team',
    'potential_third_dodgeball_interference_kwargs',
    'seeker_on_pitch',
    'set_score',
]


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
        has_ball=bool(payload[9]),
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


def _update_vector2(target: Vector2 | None, payload) -> Vector2:
    updated = _decode_vector2_payload(payload)
    if target is None:
        return updated
    target.x = updated.x
    target.y = updated.y
    return target


def _update_player_dynamic_payload(player: Player, payload) -> None:
    if not isinstance(payload, list):
        return

    player.position = _update_vector2(player.position, payload[0])
    player.previous_position = _update_vector2(player.previous_position, payload[1])
    player.direction = _update_vector2(player.direction, payload[2])
    player.velocity = _update_vector2(player.velocity, payload[3])
    player.is_knocked_out = bool(payload[4])
    player.has_ball = bool(payload[5])
    player.catch_cooldown = float(payload[6]) if payload[6] is not None else 0.0
    player.dodgeball_immunity = bool(payload[7])
    player.inbounding = payload[8]
    player.in_contact_player_ids = list(payload[9]) if isinstance(payload[9], list) else []
    player.tackling_player_ids = list(payload[10]) if isinstance(payload[10], list) else []
    player.is_receiving_turnover_ball = bool(payload[11])


def _update_ball_dynamic_payload(ball: Ball, payload) -> None:
    if not isinstance(payload, list):
        return

    ball.position = _update_vector2(ball.position, payload[0])
    ball.previous_position = _update_vector2(ball.previous_position, payload[1])
    ball.velocity = _update_vector2(ball.velocity, payload[2])
    ball.possession_team = payload[3]
    ball.holder_id = payload[4]
    ball.previous_thrower_id = payload[5]
    ball.turnover_to_player = payload[6]

    if isinstance(ball, VolleyBall):
        ball.crossed_hoop = payload[7] if len(payload) > 7 else None
        ball.inbounder = payload[8] if len(payload) > 8 else None
        ball.is_dead = bool(payload[9]) if len(payload) > 9 else False
        ball.delay_of_game_timer = float(payload[10]) if len(payload) > 10 else 0.0
    elif isinstance(ball, DodgeBall):
        ball.beat_attempt_time = float(payload[7]) if len(payload) > 7 else 0.0


def _serialize_vector2_payload(value: Vector2 | None, default: bool = False):
    if default or value is None:
        return [0.0, 0.0]
    return [value.x, value.y]


def _serialize_player_dynamic_payload(player: Player, default: bool = False):
    if default:
        return [
            _serialize_vector2_payload(None, default=True),
            _serialize_vector2_payload(None, default=True),
            _serialize_vector2_payload(None, default=True),
            _serialize_vector2_payload(None, default=True),
            False,
            False,
            0.0,
            False,
            None,
            [],
            [],
            False,
        ]

    return [
        _serialize_vector2_payload(player.position),
        _serialize_vector2_payload(player.previous_position),
        _serialize_vector2_payload(player.direction),
        _serialize_vector2_payload(player.velocity),
        player.is_knocked_out,
        player.has_ball,
        player.catch_cooldown,
        player.dodgeball_immunity,
        player.inbounding,
        list(player.in_contact_player_ids),
        list(player.tackling_player_ids),
        player.is_receiving_turnover_ball,
    ]


def _serialize_ball_dynamic_payload(ball: Ball, default: bool = False):
    if default:
        base_payload = [
            _serialize_vector2_payload(None, default=True),
            _serialize_vector2_payload(None, default=True),
            _serialize_vector2_payload(None, default=True),
            None,
            None,
            None,
            None,
        ]
    else:
        base_payload = [
            _serialize_vector2_payload(ball.position),
            _serialize_vector2_payload(ball.previous_position),
            _serialize_vector2_payload(ball.velocity),
            ball.possession_team,
            ball.holder_id,
            ball.previous_thrower_id,
            ball.turnover_to_player,
        ]

    if isinstance(ball, VolleyBall):
        base_payload.extend([
            None if default else ball.crossed_hoop,
            None if default else ball.inbounder,
            False if default else ball.is_dead,
            0.0 if default else ball.delay_of_game_timer,
        ])
    elif isinstance(ball, DodgeBall):
        base_payload.append(0.0 if default else ball.beat_attempt_time)

    return base_payload


def _serialize_game_state_dynamic_payload(state: GameState, default: bool = False):
    players_payload = [
        _serialize_player_dynamic_payload(player, default=default)
        for player in state.players.values()
    ]
    balls_payload = [
        _serialize_ball_dynamic_payload(ball, default=default)
        for ball in state.balls.values()
    ]
    volleyball_payload = None if state.volleyball is None else _serialize_ball_dynamic_payload(state.volleyball, default=default)
    dodgeballs_payload = [
        _serialize_ball_dynamic_payload(dodgeball, default=default)
        for dodgeball in state.dodgeballs
    ]

    return [
        players_payload,
        balls_payload,
        volleyball_payload,
        dodgeballs_payload,
        [0, 0] if default else list(state.score),
        0.0 if default else state.game_time,
        [0, 0] if default else [state.delay_of_game_warnings.get(0, 0), state.delay_of_game_warnings.get(1, 0)],
        None,
        None,
        [None, None] if default else [
            state.potential_third_dodgeball_interference_kwargs.get('player_id') if state.potential_third_dodgeball_interference_kwargs else None,
            state.potential_third_dodgeball_interference_kwargs.get('dodgeball_id') if state.potential_third_dodgeball_interference_kwargs else None,
        ],
        False if default else state.seeker_on_pitch,
        None if default else state.set_score,
    ]


def _apply_sparse_snapshot(template, sparse):
    if sparse is _OMIT:
        return deepcopy(template)

    if isinstance(template, list):
        if _is_leaf_list_template(template):
            if isinstance(sparse, list):
                return deepcopy(sparse)
            return deepcopy(template)

        if isinstance(sparse, dict) and _SPARSE_LIST_KEY in sparse:
            result = deepcopy(template)
            for index, item in sparse[_SPARSE_LIST_KEY]:
                index = int(index)
                if 0 <= index < len(result):
                    result[index] = _apply_sparse_snapshot(result[index], item)
            return result

        if isinstance(sparse, list):
            return deepcopy(sparse)

    # Scalars (and non-list payloads) should be replaced directly when present.
    return deepcopy(sparse)

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

        if omit_defaults and self._is_default_scalar(value):
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
            'state_record_keys': ['tick', 'kind', 'game_state'],
            'state_record_kind_map': {
                'full': _STATE_RECORD_KIND_FULL,
                'dynamic_keyframe': _STATE_RECORD_KIND_KEYFRAME,
                'dynamic_delta': _STATE_RECORD_KIND_DELTA,
            },
            'dynamic_keyframe_interval_ticks': _DYNAMIC_KEYFRAME_INTERVAL_TICKS,
            'dynamic_sparse_list_key': _SPARSE_LIST_KEY,
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
            dynamic_snapshot = self._serialize_value(room.game_state, 'game_state', dynamic_only=True)
            self._previous_dynamic_snapshot = dynamic_snapshot
            self._last_dynamic_keyframe_tick = int(_serialize_for_jsonl(room.game_tick_count))
            payload = [
                _serialize_for_jsonl(room.game_tick_count),
                _STATE_RECORD_KIND_FULL,
                game_state_payload,
            ]
        else:
            tick = int(_serialize_for_jsonl(room.game_tick_count))
            dynamic_snapshot = self._serialize_value(room.game_state, 'game_state', dynamic_only=True)

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

    @classmethod
    def load_game_state_at_tick(cls, state_file_path, tick: int) -> Optional[GameState]:
        return RoomJsonlStateReader(state_file_path).get_game_state_at_tick(tick)


class RoomJsonlStateReader:
    """Read a room state.jsonl file and reconstruct GameState snapshots."""

    def __init__(self, state_file_path):
        self.state_file_path = Path(state_file_path)

    @staticmethod
    def _loads(line: str):
        if _orjson is not None:
            return _orjson.loads(line)
        return json.loads(line)

    def _decode_game_state_full_payload(self, payload) -> GameState:
        state = GameState()
        if not isinstance(payload, list):
            return state

        field_names = [field.name for field in fields(GameState)]
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
                        try:
                            dodgeball = _decode_ball_full_payload(dodgeball_payload)
                        except Exception:
                            continue
                        if isinstance(dodgeball, DodgeBall):
                            state.dodgeballs.append(dodgeball)
                continue

            if field_name == 'hoops':
                state.hoops = {}
                if isinstance(value, list):
                    for hoop_payload in value:
                        try:
                            hoop = _decode_hoop_full_payload(hoop_payload)
                        except Exception:
                            continue
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

    def _apply_dynamic_snapshot_to_state(self, state: GameState, snapshot) -> None:
        if not isinstance(snapshot, list) or len(snapshot) < len(_GAME_STATE_DYNAMIC_FIELD_NAMES):
            return

        player_payloads = snapshot[0] if len(snapshot) > 0 else []
        ball_payloads = snapshot[1] if len(snapshot) > 1 else []
        volleyball_payload = snapshot[2] if len(snapshot) > 2 else None
        dodgeball_payloads = snapshot[3] if len(snapshot) > 3 else []
        score_payload = snapshot[4] if len(snapshot) > 4 else None
        game_time_payload = snapshot[5] if len(snapshot) > 5 else None
        warnings_payload = snapshot[6] if len(snapshot) > 6 else None
        third_dodgeball_payload = snapshot[7] if len(snapshot) > 7 else None
        third_dodgeball_team_payload = snapshot[8] if len(snapshot) > 8 else None
        interference_payload = snapshot[9] if len(snapshot) > 9 else None
        seeker_on_pitch_payload = snapshot[10] if len(snapshot) > 10 else None
        set_score_payload = snapshot[11] if len(snapshot) > 11 else None

        if isinstance(player_payloads, list):
            current_player_ids = list(state.players.keys())
            for index, player_id in enumerate(current_player_ids):
                if index >= len(player_payloads):
                    break
                _update_player_dynamic_payload(state.players[player_id], player_payloads[index])

        if isinstance(ball_payloads, list):
            current_ball_ids = list(state.balls.keys())
            for index, ball_id in enumerate(current_ball_ids):
                if index >= len(ball_payloads):
                    break
                _update_ball_dynamic_payload(state.balls[ball_id], ball_payloads[index])

        if state.volleyball is not None and volleyball_payload is not None:
            _update_ball_dynamic_payload(state.volleyball, volleyball_payload)

        if isinstance(dodgeball_payloads, list):
            for index, dodgeball in enumerate(state.dodgeballs):
                if index >= len(dodgeball_payloads):
                    break
                _update_ball_dynamic_payload(dodgeball, dodgeball_payloads[index])

        if isinstance(score_payload, list):
            state.score = list(score_payload)
        if game_time_payload is not None:
            state.game_time = game_time_payload
        if isinstance(warnings_payload, list):
            warning_keys = list(state.delay_of_game_warnings.keys()) or [0, 1]
            for index, warning_key in enumerate(warning_keys):
                if index >= len(warnings_payload):
                    break
                state.delay_of_game_warnings[warning_key] = warnings_payload[index]
        if third_dodgeball_payload is not None:
            state.third_dodgeball = third_dodgeball_payload
        if third_dodgeball_team_payload is not None:
            state.third_dodgeball_team = third_dodgeball_team_payload
        if isinstance(interference_payload, list):
            state.potential_third_dodgeball_interference_kwargs = {
                'player_id': interference_payload[0] if len(interference_payload) > 0 else None,
                'dodgeball_id': interference_payload[1] if len(interference_payload) > 1 else None,
            }
        if seeker_on_pitch_payload is not None:
            state.seeker_on_pitch = bool(seeker_on_pitch_payload)
        if set_score_payload is not None:
            state.set_score = set_score_payload

    def _find_replay_start_tick(self, tick: int) -> Optional[int]:
        """Find the best replay start record at or before target tick.

        Returns the latest keyframe tick <= target tick when available,
        otherwise falls back to the initial full snapshot tick.
        """
        full_tick: Optional[int] = None
        keyframe_tick: Optional[int] = None

        try:
            with self.state_file_path.open('r', encoding='utf-8') as handle:
                for line in handle:
                    stripped_line = line.strip()
                    if not stripped_line:
                        continue

                    record = self._loads(stripped_line)
                    if isinstance(record, dict) and record.get('event') == 'room_metadata':
                        continue
                    if not isinstance(record, list) or len(record) < 3:
                        continue

                    record_tick = int(record[0])
                    record_kind = int(record[1])

                    if record_kind == _STATE_RECORD_KIND_FULL:
                        if full_tick is None:
                            full_tick = record_tick
                    elif record_kind == _STATE_RECORD_KIND_KEYFRAME and record_tick <= tick:
                        keyframe_tick = record_tick

                    if record_tick > tick:
                        break
        except Exception:
            logger.exception('Failed to scan replay start in JSONL state log from %s', self.state_file_path)
            return None

        if keyframe_tick is not None:
            return keyframe_tick
        return full_tick

    def get_game_state_at_tick(self, tick: int) -> Optional[GameState]:
        if tick < 0 or not self.state_file_path.exists():
            return None

        replay_start_tick = self._find_replay_start_tick(tick)
        current_state: Optional[GameState] = None
        current_dynamic_snapshot = None

        try:
            with self.state_file_path.open('r', encoding='utf-8') as handle:
                for line in handle:
                    stripped_line = line.strip()
                    if not stripped_line:
                        continue

                    record = self._loads(stripped_line)
                    if isinstance(record, dict) and record.get('event') == 'room_metadata':
                        continue
                    if not isinstance(record, list) or len(record) < 3:
                        continue

                    record_tick = int(record[0])
                    record_kind = int(record[1])
                    payload = record[2]

                    # Replay records only up to the requested tick and return
                    # the latest reconstructed state at-or-before that tick.
                    if record_tick > tick:
                        break

                    if record_kind == _STATE_RECORD_KIND_FULL:
                        current_state = self._decode_game_state_full_payload(payload)
                        current_dynamic_snapshot = _serialize_game_state_dynamic_payload(current_state, default=False)
                        continue

                    # Skip historical dynamic records before the best replay start.
                    if replay_start_tick is not None and record_tick < replay_start_tick:
                        continue

                    if current_state is None or current_dynamic_snapshot is None:
                        continue

                    if record_kind == _STATE_RECORD_KIND_KEYFRAME:
                        template = _serialize_game_state_dynamic_payload(current_state, default=True)
                        current_dynamic_snapshot = _apply_sparse_snapshot(template, payload)
                    elif record_kind == _STATE_RECORD_KIND_DELTA:
                        current_dynamic_snapshot = _apply_sparse_snapshot(current_dynamic_snapshot, payload)
                    else:
                        continue

                    self._apply_dynamic_snapshot_to_state(current_state, current_dynamic_snapshot)
        except Exception:
            logger.exception('Failed to read JSONL state log from %s', self.state_file_path)
            return None

        return current_state