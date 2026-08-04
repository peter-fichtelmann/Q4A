import logging
from typing import List, Optional

import player_switch
from config import Config
from core.entities import Player, Ball, VolleyBall, Vector2, PlayerRole

logger = logging.getLogger('quadball.tutorial')


class TutorialDirector:
    """
    Server-side scenario controller for the tutorial room.

    The client requests a scenario via a `tutorial_step` game-socket message.
    `start_scenario` stages the pitch (teleports entities, hands out balls,
    parks unused CPUs, switches the trainee's role where needed) and configures
    the ScriptedComputerPlayer mode. `tick` runs once per game tick BEFORE
    game_logic.update (so short-lived flags like tackling_player_ids are still
    visible) and returns tutorial_event messages to broadcast.
    """

    def __init__(self, room):
        self.room = room
        self.scenario: Optional[str] = None
        self._phase = 0
        self._baseline = {}
        # Zero the delay-of-game timer every tick (no penalty, no clock icon)
        # except while the delay rule itself is being demonstrated / in free play.
        self.suppress_delay_of_game = True
        # Forces flag_runner_on_pitch / seeker_on_pitch every tick:
        #   False -> keep them off (the whole tutorial)
        #   True  -> keep them on (the four-headband line-up)
        #   None  -> leave them to the game clock (free play)
        self.flag_seeker_phase_override: Optional[bool] = False

    # ---- accessors ----

    @property
    def state(self):
        return self.room.game_state

    @property
    def trainee(self) -> Optional[Player]:
        player_id = getattr(self.room, 'creator_player_id', None)
        if player_id is None:
            return None
        # Follow a player switch so scenario staging targets whoever the trainee
        # actually steers (only the switch demo leaves them on another player).
        return self.state.get_player(self.room.get_controlled_player_id(player_id))

    def _set_ai(self, mode: str, **kwargs):
        computer_player = self.room.computer_player
        if computer_player is not None and hasattr(computer_player, 'set_mode'):
            computer_player.set_mode(mode, **kwargs)

    def _human_controlled_ids(self) -> set:
        return set(self.room.controlled_player_by_player.values())

    def _cpu(self, team: int, role: PlayerRole, exclude=()) -> Optional[Player]:
        human_controlled = self._human_controlled_ids()
        for player_id in self.room.cpu_player_ids:
            if player_id in human_controlled:
                continue
            player = self.state.get_player(player_id)
            if player is not None and player.team == team and player.role == role and player.id not in exclude:
                return player
        return None

    def _seeker(self, team: int, exclude=()) -> Optional[Player]:
        """Seekers are created outside `cpu_player_ids`, so look them up by role."""
        human_controlled = self._human_controlled_ids()
        for player in self.state.players.values():
            if (player.role == PlayerRole.SEEKER and player.team == team
                    and player.id not in exclude and player.id not in human_controlled):
                return player
        return None

    def _cpu_players(self) -> List[Player]:
        human_controlled = self._human_controlled_ids()
        players = []
        for player_id in self.room.cpu_player_ids:
            if player_id in human_controlled:
                continue
            player = self.state.get_player(player_id)
            if player is not None:
                players.append(player)
        return players

    # ---- entity staging helpers ----

    def _teleport(self, entity, x: float, y: float):
        entity.position = Vector2(x, y)
        entity.previous_position = Vector2(x, y)
        entity.velocity = Vector2(0, 0)
        if isinstance(entity, Player):
            entity.direction = Vector2(0, 0)

    def _strip_ball(self, ball: Ball):
        """Release a ball from its holder and null transient possession state."""
        if ball.holder_id is not None:
            holder = self.state.get_player(ball.holder_id)
            if holder is not None and holder.has_ball == ball.id:
                holder.has_ball = False
        if ball.turnover_to_player is not None:
            receiver = self.state.get_player(ball.turnover_to_player)
            if receiver is not None:
                receiver.is_receiving_turnover_ball = False
        # An in-flight inbounding procedure keeps auto-steering the inbounder;
        # cancel it on the player side too.
        for player in self.state.players.values():
            if player.inbounding == ball.id:
                player.inbounding = None
                player.dodgeball_immunity = False
        ball.holder_id = None
        ball.velocity = Vector2(0, 0)
        ball.previous_thrower_id = None
        ball.turnover_to_player = None
        if isinstance(ball, VolleyBall):
            ball.crossed_hoop = None
            ball.inbounder = None
            ball.delay_of_game_timer = 0.0

    def _free_ball(self, ball: Ball, x: float, y: float):
        self._strip_ball(ball)
        self._teleport(ball, x, y)
        ball.possession_team = None
        if isinstance(ball, VolleyBall):
            ball.is_dead = False

    def _give_ball(self, player: Player, ball: Ball, alive: bool = True):
        """Hand a ball to a player, mirroring the possession invariants of game logic."""
        self._strip_ball(ball)
        if player.has_ball:
            other_ball = self.state.get_ball(player.has_ball)
            if other_ball is not None:
                self._strip_ball(other_ball)
        ball.holder_id = player.id
        ball.possession_team = player.team
        player.has_ball = ball.id
        player.catch_cooldown = 0.0
        self._teleport(ball, player.position.x, player.position.y)
        if isinstance(ball, VolleyBall):
            ball.is_dead = not alive

    def _strip_all_balls(self):
        for ball in self.state.balls.values():
            self._strip_ball(ball)

    def _reset_balls_default(self):
        pitch_length = self.state.boundaries_x[1]
        pitch_width = self.state.boundaries_y[1]
        self._free_ball(self.state.volleyball, pitch_length / 2, pitch_width / 2)
        dodgeball_spots = [
            (pitch_length / 2, pitch_width / 4),
            (self.state.keeper_zone_x_0, pitch_width / 2),
            (self.state.keeper_zone_x_1, pitch_width / 2),
        ]
        for dodgeball, spot in zip(self.state.dodgeballs, dodgeball_spots):
            self._free_ball(dodgeball, spot[0], spot[1])

    def _clear_knockouts(self):
        for player in self.state.players.values():
            player.is_knocked_out = False
            player.catch_cooldown = 0.0
            player.tackling_player_ids = []
            player.flag_runner_interaction_time = 0.0

    def _reset_match_end_state(self):
        """Undo the match-ending side effects of a flag catch.

        `FlagRunnerLogic.resolve_catch` ends the match (`is_game_active = False`,
        which stops `GameLogic.update` entirely) or opens overtime. The tutorial is
        not a real match and has to keep ticking afterwards.
        """
        self.state.is_game_active = True
        self.state.is_overtime = False
        self.state.set_score = None

    def _restore_flag_runner_tuning(self):
        """Put the live catch odds back after the catch demo eased them."""
        flag_runner = self.state.flag_runner
        if flag_runner is not None:
            flag_runner.catch_probability = Config.FLAG_RUNNER_CATCH_PROBABILITY
            flag_runner.interaction_time_threshold = Config.FLAG_RUNNER_INTERACTION_TIME_THRESHOLD

    def _reset_flag_seeker_positions(self):
        """Send the flag runner and every seeker back to their kick-off spots.

        Mirrors `GameRoom._initialize_flag_seeker_entities`: seekers line up on the
        far touchline, spreading outwards from the midline, the runner waits on it.
        """
        center_y = self.state.boundaries_y[1] / 2
        flag_runner = self.state.flag_runner
        if flag_runner is not None:
            flag_runner.position = Vector2(self.state.midline_x, center_y)
            flag_runner.velocity = Vector2(0, 0)
            flag_runner.direction = Vector2(0, 0)
        seeker_y = self.state.boundaries_y[1] - Config.PLAYER_RADIUS
        next_index = {self.state.team_0: 1, self.state.team_1: 1}
        for player in self.state.players.values():
            if player.role != PlayerRole.SEEKER:
                continue
            index = next_index.get(player.team, 1)
            next_index[player.team] = index + 1
            sign = -1 if player.team == self.state.team_0 else 1
            self._teleport(player, self.state.midline_x + sign * 2 * index * Config.PLAYER_RADIUS, seeker_y)

    def _park_others(self, active_ids=()):
        """Bench every CPU not needed by the current scenario at the pitch edges."""
        pitch_length = self.state.boundaries_x[1]
        pitch_width = self.state.boundaries_y[1]
        bench_index = {0: 0, 1: 0}
        for player in self._cpu_players():
            if player.id in active_ids:
                continue
            index = bench_index[player.team]
            bench_index[player.team] += 1
            if player.team == 0:
                self._teleport(player, 3 + index * 2.5, 2)
            else:
                self._teleport(player, pitch_length - 3 - index * 2.5, pitch_width - 2)

    # ---- role switching ----

    def _role_change_event(self, player: Player) -> dict:
        return {
            "type": "tutorial_event",
            "event": "role_change",
            "player_id": player.id,
            "role": player.role.value,
        }

    def _set_role(self, player: Player, role: PlayerRole):
        old_role = player.role
        if old_role == role:
            return
        if old_role == PlayerRole.KEEPER:
            if player.team == self.state.team_0 and self.state.keeper_team_0 is player:
                self.state.keeper_team_0 = None
            elif player.team == self.state.team_1 and self.state.keeper_team_1 is player:
                self.state.keeper_team_1 = None
        player.role = role
        if role == PlayerRole.KEEPER:
            if player.team == self.state.team_0:
                self.state.keeper_team_0 = player
            else:
                self.state.keeper_team_1 = player
        room_entry = self.room.players.get(player.id)
        if room_entry is not None:
            room_entry["role"] = role.value

    def _swap_trainee_role(self, target_role: PlayerRole) -> List[dict]:
        """Swap roles between the trainee and a same-team CPU so team composition stays valid."""
        trainee = self.trainee
        if trainee is None or trainee.role == target_role:
            return []
        cpu = self._cpu(trainee.team, target_role)
        if cpu is None:
            return []
        old_trainee_role = trainee.role
        self._set_role(trainee, target_role)
        self._set_role(cpu, old_trainee_role)
        logger.info("Tutorial role swap: trainee -> %s, cpu %s -> %s",
                    target_role.value, cpu.id, old_trainee_role.value)
        return [self._role_change_event(trainee), self._role_change_event(cpu)]

    # ---- scenario lifecycle ----

    def _restore_trainee_control(self):
        """Put the trainee back on their own player before staging a scenario.

        Only the switch demo leaves them on a teammate; every other scenario stages
        entities around `creator_player_id`, so control is reset first.
        """
        creator_player_id = getattr(self.room, 'creator_player_id', None)
        if creator_player_id is None:
            return
        current_id = self.room.get_controlled_player_id(creator_player_id)
        if current_id != creator_player_id:
            player_switch.apply_switch(self.room, creator_player_id, current_id, creator_player_id)
            logger.info("Tutorial restored trainee control: %s -> %s", current_id, creator_player_id)

    def start_scenario(self, name: str) -> List[dict]:
        """Stage a named scenario. Returns tutorial_event messages to broadcast."""
        if name != 'player_switch_demo':
            self._restore_trainee_control()
        if not self.room.game_started or self.trainee is None:
            return []
        setup = getattr(self, f'_setup_{name}', None)
        if setup is None:
            logger.warning("Unknown tutorial scenario requested: %s", name)
            return []
        self.scenario = name
        self._phase = 0
        self._baseline = {}
        self.suppress_delay_of_game = name not in ('delay_demo', 'free_play')
        # Switching is only for the step that teaches it and for free play; every
        # other step needs the trainee to stay on the player it staged.
        self.room.player_switch_enabled = name in ('player_switch_demo', 'free_play')
        if name in ('lineup_all_positions', 'flag_catch_practice'):
            self.flag_seeker_phase_override = True
        elif name == 'free_play':
            self.flag_seeker_phase_override = None
        else:
            self.flag_seeker_phase_override = False
        self._apply_flag_seeker_phase()
        self._common_reset()
        events = setup() or []
        logger.info("Tutorial scenario started: %s (room=%s)", name, self.room.room_id)
        return events

    def _retry(self, detail: str = 'retry') -> List[dict]:
        """Re-stage the active scenario (e.g. after the practice ball went out of bounds)."""
        name = self.scenario
        setup = getattr(self, f'_setup_{name}')
        self._phase = 0
        self._baseline = {}
        self._common_reset()
        events = setup() or []
        logger.info("Tutorial scenario retried: %s (room=%s)", name, self.room.room_id)
        return events + [{"type": "tutorial_event", "event": "progress", "step": name, "detail": detail}]

    def _volleyball_out_of_play(self) -> bool:
        """True when the volleyball left the practice flow (inbounding or turnover started)."""
        volleyball = self.state.volleyball
        if volleyball is None:
            return False
        return volleyball.inbounder is not None or volleyball.turnover_to_player is not None

    def _ball_resting_at_boundary(self, ball: Ball, eps: float = 0.05) -> bool:
        if ball.holder_id is not None:
            return False
        min_x, max_x = self.state.boundaries_x
        min_y, max_y = self.state.boundaries_y
        r = ball.radius
        return (ball.position.x <= min_x + r + eps or ball.position.x >= max_x - r - eps
                or ball.position.y <= min_y + r + eps or ball.position.y >= max_y - r - eps)

    def _apply_flag_seeker_phase(self):
        """Hold the flag seeker phase off (or on) regardless of the game clock.

        The floor seconds have to move with the flags: the director runs *before*
        `game_logic.update`, and `update_game_time` re-raises both flags on every
        tick once the clock is past the thresholds, which would undo the override.
        """
        if self.flag_seeker_phase_override is None:
            # Free play: hand the phase back to the game clock.
            self.state.flag_runner_floor_seconds = (
                Config.FLAG_RUNNER_FLOOR_REAL_SECONDS / Config.GAME_TIME_TO_REAL_TIME_RATIO)
            self.state.seeker_floor_seconds = (
                Config.SEEKER_FLOOR_REAL_SECONDS / Config.GAME_TIME_TO_REAL_TIME_RATIO)
            return

        on_pitch = self.flag_seeker_phase_override
        floor_seconds = 0.0 if on_pitch else float('inf')
        self.state.flag_runner_floor_seconds = floor_seconds
        self.state.seeker_floor_seconds = floor_seconds
        self.state.flag_runner_on_pitch = on_pitch
        self.state.seeker_on_pitch = on_pitch

    def _common_reset(self):
        self._clear_knockouts()
        if self.state.volleyball is not None:
            self.state.volleyball.delay_of_game_timer = 0.0
        self.state.delay_of_game_warnings = {0: 0, 1: 0}
        self._reset_match_end_state()
        self._restore_flag_runner_tuning()

    def tick(self) -> List[dict]:
        """Evaluate the active scenario's success predicate. Runs before game_logic.update."""
        if self.suppress_delay_of_game and self.state.volleyball is not None:
            self.state.volleyball.delay_of_game_timer = 0.0
        # Reapplied every tick: `update_game_time` would otherwise flip the phase on
        # once the tutorial room's clock passes the flag runner / seeker thresholds.
        self._apply_flag_seeker_phase()
        if self.scenario is None:
            return []
        checker = getattr(self, f'_check_{self.scenario}', None)
        if checker is None:
            return []
        try:
            return checker() or []
        except Exception:
            logger.exception("Tutorial scenario check failed: %s", self.scenario)
            return []

    def _success(self, outcome: str = 'default') -> List[dict]:
        """Complete the active scenario. `outcome` lets the client pick an alternative message."""
        step = self.scenario
        self.scenario = None
        self._set_ai('idle')
        return [{"type": "tutorial_event", "event": "success", "step": step, "outcome": outcome}]

    def _progress(self, detail: str) -> dict:
        return {"type": "tutorial_event", "event": "progress", "step": self.scenario, "detail": detail}

    # ---- scenarios ----

    def _setup_idle_all(self):
        events = self._swap_trainee_role(PlayerRole.CHASER)
        self._set_ai('idle')
        return events

    def _setup_player_switch_demo(self):
        """Teach the two switch buttons by gathering the trainee's own line-up around them.

        `start_scenario` enables switching for this scenario (and for free play) and
        disables it again for every other one, where it also calls
        `_restore_trainee_control` so the trainee is back on their own player.
        """
        events = self._swap_trainee_role(PlayerRole.CHASER)
        self._strip_all_balls()
        self._reset_balls_default()
        trainee = self.trainee
        # Own half: team 0 defends the low-x hoops, team 1 the high-x ones.
        side = -1 if trainee.team == 0 else 1
        center_y = self.state.boundaries_y[1] / 2
        self._teleport(trainee, self.state.midline_x + side * 3.0, center_y)

        # One of every position within sight, so both Q and E have a visible target.
        layout = [
            (PlayerRole.CHASER, 6.0, -4.0),
            (PlayerRole.CHASER, 6.0, 4.0),
            (PlayerRole.KEEPER, 9.0, 0.0),
            (PlayerRole.BEATER, 3.0, -7.0),
            (PlayerRole.BEATER, 3.0, 7.0),
        ]
        targets = {}
        used = set()
        for role, offset_x, offset_y in layout:
            cpu = self._cpu(trainee.team, role, exclude=used)
            if cpu is None:
                continue
            used.add(cpu.id)
            x = self.state.midline_x + side * offset_x
            y = center_y + offset_y
            self._teleport(cpu, x, y)
            targets[cpu.id] = (x, y)

        self._park_others(active_ids=used)
        self._set_ai('hold_positions', targets=targets)
        return events

    def _own_hoops(self, team: int) -> List:
        return [hoop for hoop in self.state.hoops.values() if hoop.team == team]

    def _setup_hoop_blockage_demo(self):
        events = self._swap_trainee_role(PlayerRole.CHASER)
        trainee = self.trainee
        self._strip_all_balls()
        self._park_others()
        hoops = self._own_hoops(trainee.team)
        if hoops:
            hoop_x = hoops[0].position.x  # all own hoops share the same x
            # Face the hoops from the pitch side, clear of the blockage band.
            approach = 1 if hoop_x < self.state.midline_x else -1
            self._teleport(trainee, hoop_x + approach * 6.0, self.state.boundaries_y[1] / 2)
        self._set_ai('idle')
        return events

    def _check_hoop_blockage_demo(self):
        """Succeed once _enforce_hoop_blockage is pinning the trainee at the band edge."""
        trainee = self.trainee
        volleyball = self.state.volleyball
        if trainee is None or volleyball is None:
            return []
        # Same geometry as BoundaryLogic._enforce_hoop_blockage, which resets the
        # chaser's x to exactly hoop.x +/- margin while they push against it.
        margin = trainee.radius + volleyball.radius
        for hoop in self._own_hoops(trainee.team):
            if (abs(trainee.position.x - hoop.position.x) <= margin + 0.1
                    and abs(trainee.position.y - hoop.position.y) < hoop.radius + trainee.radius):
                return self._success()
        return []

    def _setup_pass_practice(self):
        trainee = self.trainee
        events = self._swap_trainee_role(PlayerRole.CHASER)
        self._strip_all_balls()
        receiver = self._cpu(trainee.team, PlayerRole.CHASER)
        self._park_others({receiver.id} if receiver else ())
        self._teleport(trainee, 24, 16.5)
        self._free_ball(self.state.volleyball, 27, 16.5)
        if receiver is not None:
            self._teleport(receiver, 34, 16.5)
            self._baseline['receiver_id'] = receiver.id
            self._set_ai('pass_receiver', receiver_id=receiver.id, trainee_id=trainee.id, home=(34, 16.5))
        self._baseline['score'] = list(self.state.score)
        return events

    def _check_pass_practice(self):
        receiver_id = self._baseline.get('receiver_id')
        volleyball = self.state.volleyball
        if receiver_id is not None and volleyball is not None and volleyball.holder_id == receiver_id:
            return self._success()
        trainee = self.trainee
        baseline_score = self._baseline.get('score')
        if trainee is not None and baseline_score is not None:
            # Scoring either way leaves the volleyball dead with a keeper, not
            # merely out of bounds — each direction needs its own retry detail.
            if self.state.score[trainee.team] > baseline_score[trainee.team]:
                return self._retry('scored')
            if self.state.score[1 - trainee.team] > baseline_score[1 - trainee.team]:
                return self._retry('own_goal')
        if self._volleyball_out_of_play():
            return self._retry()
        return []

    def _setup_scoring_practice(self):
        return self._stage_scoring(behind=False)

    def _setup_scoring_behind_practice(self):
        """Same drill, but the trainee starts on the far side of the hoops."""
        return self._stage_scoring(behind=True)

    def _stage_scoring(self, behind: bool):
        trainee = self.trainee
        events = self._swap_trainee_role(PlayerRole.CHASER)
        self._strip_all_balls()
        self._park_others()
        hoop = self.state.hoops.get(f'hoop_{1 - trainee.team}_center')
        if hoop is None:
            self._teleport(trainee, 40, 16.5)
        elif behind:
            # Deep behind the hoop line, between the hoops and the end boundary.
            pitch_length = self.state.boundaries_x[1]
            x = 55.0 if hoop.position.x > self.state.midline_x else pitch_length - 55.0
            self._teleport(trainee, x, self.state.boundaries_y[1] / 2)
        else:
            # The normal attacking side faces the midline.
            toward_midline = -1 if hoop.position.x > self.state.midline_x else 1
            self._teleport(trainee, hoop.position.x + 6.5 * toward_midline, hoop.position.y)
        self._give_ball(trainee, self.state.volleyball)
        self._baseline['score'] = self.state.score[trainee.team]
        self._set_ai('idle')
        return events

    def _check_scoring_practice(self):
        trainee = self.trainee
        if trainee is not None and self.state.score[trainee.team] > self._baseline.get('score', 0):
            return self._success()
        if self._volleyball_out_of_play():
            return self._retry()
        return []

    def _check_scoring_behind_practice(self):
        return self._check_scoring_practice()

    def _setup_tackle_practice(self):
        trainee = self.trainee
        events = self._swap_trainee_role(PlayerRole.CHASER)
        self._strip_all_balls()
        carrier = self._cpu(1 - trainee.team, PlayerRole.CHASER)
        self._park_others({carrier.id} if carrier else ())
        self._teleport(trainee, 30, 16.5)
        if carrier is not None:
            self._teleport(carrier, 34, 12)
            self._give_ball(carrier, self.state.volleyball)
            self._baseline['carrier_id'] = carrier.id
            self._set_ai('walk_waypoints', walker_id=carrier.id, waypoints=[(34, 21), (34, 12)])
        return events

    def _check_tackle_practice(self):
        trainee = self.trainee
        carrier_id = self._baseline.get('carrier_id')
        if trainee is None or carrier_id is None:
            return []
        # tackling_player_ids is set by the tackle action and cleared inside the
        # next game_logic.update; this tick runs before the update so it is visible.
        if carrier_id in trainee.tackling_player_ids:
            return self._success()
        return []

    def _setup_lineup(self, include_seekers: bool = False):
        events = self._swap_trainee_role(PlayerRole.CHASER)
        self._strip_all_balls()
        self._reset_balls_default()
        trainee = self.trainee
        self._teleport(trainee, 30, 27)
        role_order = [PlayerRole.KEEPER, PlayerRole.CHASER, PlayerRole.CHASER,
                      PlayerRole.CHASER, PlayerRole.BEATER, PlayerRole.BEATER]
        if include_seekers:
            role_order = role_order + [PlayerRole.SEEKER]
        targets = {}
        used = set()
        for team, line_x in ((trainee.team, 27.0), (1 - trainee.team, 33.0)):
            y = 5.0
            for role in role_order:
                cpu = self._seeker(team, exclude=used) if role == PlayerRole.SEEKER \
                    else self._cpu(team, role, exclude=used)
                if cpu is None:
                    continue
                used.add(cpu.id)
                if role == PlayerRole.SEEKER:
                    # The scripted AI only steers `cpu_players`, which excludes seekers,
                    # so they have to be placed directly instead of walked into the row.
                    self._teleport(cpu, line_x, y)
                else:
                    targets[cpu.id] = (line_x, y)
                y += 3.0
        self._set_ai('hold_positions', targets=targets)
        return events

    def _setup_lineup_all_positions(self):
        """The line-up used to explain all four headbands, seekers included."""
        return self._setup_lineup(include_seekers=True)

    def _setup_beat_practice(self):
        events = self._swap_trainee_role(PlayerRole.BEATER)
        trainee = self.trainee
        self._strip_all_balls()
        target = self._cpu(1 - trainee.team, PlayerRole.CHASER)
        self._park_others({target.id} if target else ())
        self._teleport(trainee, 30, 16.5)
        if self.state.dodgeballs:
            self._give_ball(trainee, self.state.dodgeballs[0])
            self._baseline['dodgeball_id'] = self.state.dodgeballs[0].id
        if target is not None:
            self._teleport(target, 35, 12)
            self._baseline['target_id'] = target.id
            self._set_ai('walk_waypoints', walker_id=target.id, waypoints=[(35, 21), (35, 12)])
        return events

    def _check_beat_practice(self):
        target = self.state.get_player(self._baseline.get('target_id'))
        if target is not None and target.is_knocked_out:
            return self._success()
        dodgeball = self.state.get_ball(self._baseline.get('dodgeball_id'))
        if dodgeball is not None and self._ball_resting_at_boundary(dodgeball):
            return self._retry()
        return []

    def _setup_get_beaten(self):
        events = self._swap_trainee_role(PlayerRole.CHASER)
        trainee = self.trainee
        self._strip_all_balls()
        beater = self._cpu(1 - trainee.team, PlayerRole.BEATER)
        self._park_others({beater.id} if beater else ())
        self._teleport(trainee, 38, 16.5)
        if beater is not None:
            self._teleport(beater, 52, 16.5)
            if self.state.dodgeballs:
                self._give_ball(beater, self.state.dodgeballs[0])
            # Hold fire until the trainee closes 1 m nearer than the default range.
            self._set_ai('throw_at_trainee', beater_id=beater.id, trainee_id=trainee.id, throw_range=3.0)
        return events

    def _check_get_beaten(self):
        trainee = self.trainee
        if trainee is None:
            return []
        if self._phase == 0:
            if trainee.is_knocked_out:
                self._phase = 1
                self._set_ai('idle')
                return [self._progress('knocked_out')]
        elif not trainee.is_knocked_out:
            return self._success()
        return []

    def _setup_keeper_immunity_demo(self):
        events = self._swap_trainee_role(PlayerRole.KEEPER)
        trainee = self.trainee
        self._strip_all_balls()
        opponent_team = 1 - trainee.team
        beater_1 = self._cpu(opponent_team, PlayerRole.BEATER)
        beater_2 = self._cpu(opponent_team, PlayerRole.BEATER, exclude={beater_1.id} if beater_1 else set())
        beaters = [b for b in (beater_1, beater_2) if b is not None]
        self._park_others({b.id for b in beaters})
        pitch_width = self.state.boundaries_y[1]
        # Deep inside the own keeper zone, with the beaters posted just outside it.
        if trainee.team == self.state.team_0:
            zone_x, outside_x = self.state.keeper_zone_x_0, self.state.keeper_zone_x_0 + 2.5
        else:
            zone_x, outside_x = self.state.keeper_zone_x_1, self.state.keeper_zone_x_1 - 2.5
        self._teleport(trainee, (zone_x + self.state.hoops[f'hoop_{trainee.team}_center'].position.x) / 2, pitch_width / 2)
        for index, beater in enumerate(beaters):
            self._teleport(beater, outside_x, pitch_width / 2 + (2 if index else -2))
            if index < len(self.state.dodgeballs):
                self._give_ball(beater, self.state.dodgeballs[index])
        self._set_ai('barrage_trainee', beater_ids=[b.id for b in beaters], trainee_id=trainee.id)
        return events

    def _setup_goal_restart_demo(self):
        events = self._swap_trainee_role(PlayerRole.KEEPER)
        trainee = self.trainee
        self._strip_all_balls()
        scorer = self._cpu(1 - trainee.team, PlayerRole.CHASER)
        self._park_others({scorer.id} if scorer else ())
        self._teleport(trainee, 10, 11)
        if scorer is not None:
            self._teleport(scorer, 26, 16.5)
            self._give_ball(scorer, self.state.volleyball)
            self._set_ai('score_and_restart', scorer_id=scorer.id, hoop_team=trainee.team)
        self._baseline['opponent_score'] = self.state.score[1 - trainee.team]
        return events

    def _check_goal_restart_demo(self):
        trainee = self.trainee
        volleyball = self.state.volleyball
        if trainee is None or volleyball is None:
            return []
        if self._phase == 0:
            if self.state.score[1 - trainee.team] > self._baseline.get('opponent_score', 0):
                self._phase = 1
                self._set_ai('idle')
                return [self._progress('goal_scored')]
        elif volleyball.holder_id == trainee.id and not volleyball.is_dead:
            return self._success()
        return []

    def _setup_flag_catch_practice(self):
        """Hand the trainee their own seeker and let them run the flag runner down.

        Control is switched onto the seeker entity rather than swapping roles:
        seekers live outside `cpu_player_ids`, so `_swap_trainee_role` would strand
        the ex-seeker as a stray chaser that `_park_others` never benches again.

        `start_scenario` forces the flag seeker phase on for this scenario, and
        `_common_reset` has just restored the live catch odds — they are raised to
        the tutorial value below so the demo resolves in a few attempts.
        """
        trainee = self.trainee
        flag_runner = self.state.flag_runner
        if trainee is None or flag_runner is None:
            return []
        seeker = self._seeker(trainee.team)
        if seeker is None:
            return []

        self._strip_all_balls()
        self._park_others()
        pitch_length = self.state.boundaries_x[1]
        center_y = self.state.boundaries_y[1] / 2

        # Park the trainee's own player on their half: control returns to it once
        # the flag is caught, so it must be somewhere sensible to reappear.
        self._teleport(trainee, self.state.midline_x - 12.0, center_y)
        player_switch.apply_switch(self.room, self.room.creator_player_id, trainee.id, seeker.id)

        # The opposing seeker has no AI in the tutorial, but it is on pitch now and
        # would both clutter the shot and be eligible to catch the runner itself.
        other_seeker = self._seeker(1 - seeker.team)
        if other_seeker is not None:
            self._teleport(other_seeker, pitch_length - 3.0, 2.0)

        flag_runner.position = Vector2(self.state.midline_x, center_y)
        flag_runner.velocity = Vector2(0, 0)
        flag_runner.direction = Vector2(0, 0)
        flag_runner.catch_probability = Config.TUTORIAL_FLAG_RUNNER_CATCH_PROBABILITY
        flag_runner.interaction_time_threshold = Config.TUTORIAL_FLAG_RUNNER_INTERACTION_TIME_THRESHOLD
        # Far enough that the runner is not already being touched while the first
        # two bubbles are still being read.
        self._teleport(seeker, self.state.midline_x - 7.0, center_y)

        self._baseline['seeker_id'] = seeker.id
        self._baseline['score'] = self.state.score[seeker.team]
        self._set_ai('idle')
        return []

    def _check_flag_catch_practice(self):
        seeker = self.state.get_player(self._baseline.get('seeker_id'))
        if seeker is None:
            return []
        # resolve_catch is the only thing that can move the score here (all balls
        # were stripped), and it awards 3 points to the catching team.
        if self.state.score[seeker.team] <= self._baseline.get('score', 0):
            return []
        self._reset_match_end_state()
        # Take the phase back off pitch: it stops a second catch from firing
        # (and freezing the game again) while the success bubble is up.
        self.flag_seeker_phase_override = False
        # ...which would leave the trainee steering an entity that is no longer
        # drawn, so give them their own player back first.
        self._restore_trainee_control()
        return self._success()

    def _setup_delay_demo(self):
        events = self._swap_trainee_role(PlayerRole.CHASER)
        trainee = self.trainee
        self._strip_all_balls()
        # Park everyone far away so opponent-proximity exemptions cannot cancel the timer.
        self._park_others()
        # Spawn east of the own hoops (x=13.5): a chaser walking toward the midline
        # must never enter the own-hoop blockage band or they get stuck.
        self._teleport(trainee, 17, 16.5)
        self._give_ball(trainee, self.state.volleyball)
        self._set_ai('idle')
        return events

    def _check_delay_demo(self):
        trainee = self.trainee
        volleyball = self.state.volleyball
        if trainee is None or volleyball is None:
            return []
        # The trainee may dawdle long enough to actually concede the penalty:
        # the volleyball is then turned over to an opponent and cannot be
        # recovered, so end the step with the turnover message instead.
        if self._delay_turnover_conceded(trainee, volleyball):
            return self._success(outcome='turnover')
        if self._phase == 0:
            limit = self.state.delay_of_game_time_limit or 15
            if volleyball.delay_of_game_timer > limit * 0.25:
                self._phase = 1
                return [self._progress('delay_ticking')]
        elif trainee.position.x > self.state.midline_x:
            return self._success()
        return []

    def _delay_turnover_conceded(self, trainee: Player, volleyball: VolleyBall) -> bool:
        """True once a delay-of-game penalty has handed the volleyball to the opponents."""
        warnings = self.state.delay_of_game_warnings.get(trainee.team, 0)
        if warnings <= self.state.max_delay_of_game_warnings:
            return False  # no penalty issued yet, only warnings
        if volleyball.turnover_to_player is not None:
            receiver = self.state.get_player(volleyball.turnover_to_player)
            return receiver is not None and receiver.team != trainee.team
        # The designated opponent may already have collected the ball.
        holder = self.state.get_player(volleyball.holder_id) if volleyball.holder_id else None
        return holder is not None and holder.team != trainee.team

    def _setup_oob_demo(self):
        events = self._swap_trainee_role(PlayerRole.CHASER)
        trainee = self.trainee
        self._strip_all_balls()
        self._park_others()
        self._teleport(trainee, 30, 4)
        self._give_ball(trainee, self.state.volleyball)
        self._set_ai('idle')
        return events

    def _check_oob_demo(self):
        volleyball = self.state.volleyball
        if volleyball is not None and volleyball.inbounder is not None:
            return self._success()
        return []

    def _setup_third_dodgeball_demo(self):
        """Both enemy dodgeballs held, the third free and ours — then they grab for it anyway."""
        events = self._swap_trainee_role(PlayerRole.BEATER)
        trainee = self.trainee
        self._strip_all_balls()
        opponent_team = 1 - trainee.team
        cheater = self._cpu(opponent_team, PlayerRole.BEATER)
        partner = self._cpu(opponent_team, PlayerRole.BEATER, exclude={cheater.id} if cheater else set())
        active = {b.id for b in (cheater, partner) if b is not None}
        self._park_others(active)
        # The trainee watches from a distance: the free dodgeball is legally
        # theirs, and collecting it would end the situation before the foul.
        self._teleport(trainee, 4, 16.5)
        if cheater is not None:
            self._teleport(cheater, 34, 4)
            if len(self.state.dodgeballs) > 0:
                self._give_ball(cheater, self.state.dodgeballs[0])
            self._baseline['cheater_id'] = cheater.id
        if partner is not None:
            self._teleport(partner, 42, 20)
            if len(self.state.dodgeballs) > 1:
                self._give_ball(partner, self.state.dodgeballs[1])
        if len(self.state.dodgeballs) > 2:
            self._free_ball(self.state.dodgeballs[2], 35, 25)
        if cheater is not None:
            self._set_ai('third_dodgeball_cheat', cheater_id=cheater.id)
        else:
            self._set_ai('idle')
        return events

    def _check_third_dodgeball_demo(self):
        cheater = self.state.get_player(self._baseline.get('cheater_id'))
        if cheater is None:
            return []
        # The interference penalty sends the offender back to their hoops.
        if cheater.is_knocked_out:
            return self._success()
        if self._phase == 0:
            if not cheater.has_ball:
                self._phase = 1
                return [self._progress('ball_dumped')]
        elif self.state.third_dodgeball is None:
            # Somebody (most likely the trainee) collected the free dodgeball,
            # which legally ends the third-dodgeball situation — stage it again.
            return self._retry()
        return []

    def _setup_free_play(self):
        events = self._swap_trainee_role(PlayerRole.CHASER)
        trainee = self.trainee
        self._strip_all_balls()
        self._reset_balls_default()
        # Free play hands the phase back to the game clock (override None), but the
        # tutorial's clock is long past both floor times by now, so the flag runner
        # and seekers would pop in the moment free play starts. Restart the match
        # clock and send them back to their kick-off spots so they arrive on cue.
        self.state.game_time = 0.0
        self.state.flag_runner_on_pitch = False
        self.state.seeker_on_pitch = False
        self._reset_flag_seeker_positions()
        pitch_length = self.state.boundaries_x[1]
        self._teleport(trainee, 8, 16.5)
        offsets = {0: 0, 1: 0}
        for player in self._cpu_players():
            index = offsets[player.team]
            offsets[player.team] += 1
            x = 6 + index * 2.0
            if player.team != trainee.team:
                x = pitch_length - x
            self._teleport(player, x, 8 + (index % 6) * 3.5)
        self._set_ai('free_play')
        self.scenario = None
        return events
