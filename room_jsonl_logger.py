from __future__ import annotations

import json
import logging
import struct
from collections import deque
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

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

        if not self.enabled:
            return

        try:
            created_stamp = room.created_at.strftime('%Y%m%dT%H%M%S')
            logs_dir = Path('game_data') / 'logs'
            logs_dir.mkdir(parents=True, exist_ok=True)
            base_name = f"room_{room.room_id}_{created_stamp}"

            state_path = logs_dir / f"{base_name}_state.jsonl"
            cpu_path = logs_dir / f"{base_name}_cpu_moves.jsonl"

            self.state_file = state_path.open('a', encoding='utf-8', buffering=1024 * 1024)
            self.cpu_file = cpu_path.open('a', encoding='utf-8', buffering=1024 * 1024)

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
            }
            self._write_line(self.state_file, metadata)
        except Exception:
            logger.exception('Failed to initialize JSONL room logger for room=%s', room.room_id)
            self.enabled = False
            self.close()

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
        payload = {
            'event': 'game_state_tick',
            'room_id': room.room_id,
            'tick': room.game_tick_count,
            'game_time': room.game_state.game_time,
            'game_state': room.game_state,
        }
        self._write_line(self.state_file, payload)

    def log_cpu_move_snapshot(self, room) -> None:
        if not self.enabled:
            return
        cpu_moves = []
        for cpu_player_id in room.cpu_player_ids:
            player = room.game_state.get_player(cpu_player_id)
            if player is None:
                continue
            cpu_moves.append({
                'player_id': cpu_player_id,
                'direction_x': getattr(getattr(player, 'direction', None), 'x', 0.0),
                'direction_y': getattr(getattr(player, 'direction', None), 'y', 0.0),
            })

        payload = {
            'event': 'cpu_move',
            'room_id': room.room_id,
            'cpu_move_tick': room.cpu_move_tick_count,
            'game_time': room.game_state.game_time,
            'cpu_moves': cpu_moves,
        }
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