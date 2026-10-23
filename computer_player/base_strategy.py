from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import logging
from typing import Dict, List, Optional, Set

from core.entities import Hoop, PlayerRole
from core.game_logic.game_logic import GameLogic
from computer_player.volleyball_possession_calculator import VolleyballPossession


@dataclass
class TeamRoster:
    """Static per-team lookups. Players and hoops are fixed once the game has started."""
    team: int
    own_hoops: List[Hoop]
    opponent_hoops: List[Hoop]
    chaser_keeper_ids: List[str]
    beater_ids: List[str]
    opponent_chaser_keeper_ids: List[str]
    opponent_beater_ids: List[str]

    @classmethod
    def build(cls, state, team: int) -> 'TeamRoster':
        """Collect hoops and player ids of `team` and its opponent in game-state order."""
        roster = cls(team, [], [], [], [], [], [])
        for hoop in state.hoops.values():
            if hoop.team == team:
                roster.own_hoops.append(hoop)
            else:
                roster.opponent_hoops.append(hoop)
        for player in state.players.values():
            own = player.team == team
            if player.role in (PlayerRole.CHASER, PlayerRole.KEEPER):
                (roster.chaser_keeper_ids if own else roster.opponent_chaser_keeper_ids).append(player.id)
            elif player.role == PlayerRole.BEATER:
                (roster.beater_ids if own else roster.opponent_beater_ids).append(player.id)
        return roster


@dataclass
class PossessionEvents:
    """What changed in volleyball possession since the previous computer player step."""
    goal_scored_by: Optional[int] = None # team whose score went up
    turnover_from: Optional[int] = None # team that lost possession without scoring


@dataclass
class StepContext:
    """Everything strategies and moves share during one computer player step."""
    dt: float
    game_time: float
    possession: VolleyballPossession
    attack_team: Optional[int]
    defence_team: Optional[int]
    events: PossessionEvents
    cpu_player_id_set: Set[str]
    rosters: Dict[int, TeamRoster] = field(default_factory=dict)


class BaseStrategy(ABC):
    """
    Default behaviour of one role group (chasers+keeper or beaters) of one side (attack or defence).

    Instances are built once by the orchestrator and called every step with the
    players they may steer. Players that are steered by a move are left out.
    """
    def __init__(self, logic: GameLogic, logger: Optional[logging.Logger] = None):
        """Bind game logic."""
        self.logic = logic
        self.logger = logger or logging.getLogger("computer_player")

    @abstractmethod
    def __call__(self,
                 ctx: StepContext,
                 team: int,
                 controlled_ids: List[str],
                 assigned_beater_ids: List[str]) -> None:
        """Steer `controlled_ids` of `team` for one step. Beaters in `assigned_beater_ids` fetch dodgeballs instead."""
        pass
