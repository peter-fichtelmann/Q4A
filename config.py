import logging

class Config:
    JSONL_LOGGING_ENABLED = True
    GAME_LOGIC_UPDATE_LOG_LEVEL = logging.DEBUG
    GAME_LOGIC_STEP_PROFILING_ENABLED = True
    GAME_LOGIC_STEP_PROFILE_START_TICK = 0
    GAME_LOGIC_STEP_PROFILE_NUM_TICKS = 300
    GAME_LOGIC_STEP_PROFILE_TOP_N = 40
    COMPUTER_PLAYER_STEP_PROFILING_ENABLED = True
    COMPUTER_PLAYER_STEP_PROFILE_START_MOVE = 0
    COMPUTER_PLAYER_STEP_PROFILE_NUM_MOVES = 60
    COMPUTER_PLAYER_STEP_PROFILE_TOP_N = 30
    FPS = 20 # frame rate per 
    GAME_TIME_TO_REAL_TIME_RATIO = 3 # 1 second real time = 3 seconds game time
    PITCH_WIDTH = 33
    PITCH_LENGTH = 60
    HOOP_X = 13.5
    KEEPER_ZONE_X = 19
    HOOP_DISTANCES = 2.75
    HOOP_RADIUS = 0.86/2 #  The inner diameter of each hoop loop must be between 81 centimeters and 86 centimeters
    HOOP_THICKNESS = 0.1
    VOLLEYBALL_RADIUS = 1.33 *0.67 / 2 / 3.14 # larger than in rulebook for better accessibility (rulebook: 65 centimeters to 67 centimeters in circumference (approximately 0.106 m))
    DODGEBALL_RADIUS = 1.33 * 0.70 / 2 / 3.14 # larger than in rulebook for better accessibility (rulebook: 68 centimeters and 70 centimeters in circumference (approximately 0.111 m))
    PLAYER_RADIUS = 0.4

    PLAYER_MAX_SPEED_REAL = 4 # m/s per real second
    PLAYER_MIN_SPEED_REAL = 1 # m/s per real second
    PLAYER_THROW_VELOCITY_REAL = 11 # m/s per real second
    PLAYER_ACCELERATION_REAL = 3.5 # m/s2 per real second
    PLAYER_MAX_SPEED = PLAYER_MAX_SPEED_REAL / GAME_TIME_TO_REAL_TIME_RATIO
    PLAYER_MIN_SPEED = PLAYER_MIN_SPEED_REAL / GAME_TIME_TO_REAL_TIME_RATIO
    PLAYER_THROW_VELOCITY = PLAYER_THROW_VELOCITY_REAL / GAME_TIME_TO_REAL_TIME_RATIO
    PLAYER_ACCELERATION = PLAYER_ACCELERATION_REAL / GAME_TIME_TO_REAL_TIME_RATIO
    # Motion model for player physics and computer player trajectory estimation:
    # "analytic": deacceleration rate = acceleration / max speed, so max speed is the terminal velocity
    #             and the speed cap never binds; CPU estimates use the exact closed-form tick motion
    #             (computer_player_utility/kinematics.py) incl. ball decay, acceleration and current velocity.
    # "legacy":   deacceleration rate 0.5 with speed cap; CPU estimates assume constant velocities.
    MOTION_MODEL = "analytic"
    PLAYER_DEACCELERATION_RATE_LEGACY = 0.5 # ratio of speed lost per second
    PLAYER_DEACCELERATION_RATE = PLAYER_ACCELERATION / PLAYER_MAX_SPEED if MOTION_MODEL == "analytic" else PLAYER_DEACCELERATION_RATE_LEGACY
    MOTION_MODEL_MAX_TICKS = 400 # look-ahead horizon of analytic estimates in game ticks (60 game s, enough to cross the pitch)
    MOTION_MODEL_SCAN_STEP = 4 # initial tick step of the analytic root scan (refined by bisection), grows for far horizons
    THROW_CATCH_MARGIN_FACTOR = 0.9 # analytic throws: ball has to reach within this fraction of the catch distance (receiver radius + ball radius)
    PLAYER_MIN_DIR = 0.6 # of 1 

    BALL_DEACCELERATION_RATE = 0.15 # ratio of speed lost per second
    BALL_REFLECT_VELOCITY_LOSS = 0.4 # ratio of velocity lost on reflection with player

    DODGEBALL_DEAD_VELOCITY_THRESHOLD_REAL = 4 # velocity m/s real when dodgeball becomes dead
    DODGEBALL_DEAD_VELOCITY_THRESHOLD = DODGEBALL_DEAD_VELOCITY_THRESHOLD_REAL / GAME_TIME_TO_REAL_TIME_RATIO

    DELAY_OF_GAME_TIME_LIMIT = 15  # game seconds before delay of game warning/penalty
    DELAY_OF_GAME_VELOCITY_X_THRESHOLD_REAL = 1.4  # m/s in x direction the volleyball must exceed to avoid delay of game; should be slow running speed
    DELAY_OF_GAME_VELOCITY_X_THRESHOLD = DELAY_OF_GAME_VELOCITY_X_THRESHOLD_REAL / GAME_TIME_TO_REAL_TIME_RATIO
    MAX_DELAY_OF_GAME_WARNINGS = 1  # Number of warnings before penalty per team
    NO_DELAY_OF_GAME_OPPONENT_CHASER_SQUARED_DISTANCE_THRESHOLD = 2**2 # squared distance threshold to opponent chasers to prevent delay of game
    NO_DELAY_OF_GAME_OPPONENT_BEATER_SQUARED_DISTANCE_THRESHOLD = 4**2 # squared distance threshold to opponent beaters to prevent delay of game
    STALLED_VOLLEYBALL_TIME_LIMIT = 10  # game seconds a tackled volleyball carrier keeps the ball before it goes to the closest opponent chaser/keeper
    STALLED_VOLLEYBALL_COUNTDOWN = 5  # last game seconds of the stalled volleyball limit that are counted down next to the ball
    STALLED_VOLLEYBALL_TACKLE_GRACE = 2  # game seconds without a new tackle after which the carrier counts as free again (tackles are single actions)
    TURNOVER_THROW_BLOCK_TIME_REAL = 1  # real seconds a player receiving a turnover ball cannot throw (the tackle button is also the throw button)
    TURNOVER_THROW_BLOCK_TIME = TURNOVER_THROW_BLOCK_TIME_REAL * GAME_TIME_TO_REAL_TIME_RATIO
    STALLED_TURNOVER_TACKLE_IMMUNITY_TIME_REAL = 0.5  # real seconds the player receiving a stalled volleyball turnover cannot be tackled
    STALLED_TURNOVER_TACKLE_IMMUNITY_TIME = STALLED_TURNOVER_TACKLE_IMMUNITY_TIME_REAL * GAME_TIME_TO_REAL_TIME_RATIO

    # should be at least NO_DELAY_OF_GAME_OPPONENT_CHASER_SQUARED_DISTANCE_THRESHOLD
    MIN_SQUARED_DISTANCE_PLAYER_PLAYER_CALCULATION = 4 # only calculate and store distances for player pairs that are within this squared distance to save on calculations and memory, since distant players won't interact with each other

    BEAT_ATTEMPT_TIME_LIMIT = 6 # game seconds ball has time to beat player before potential third dodgeball interference
    
    VOLLEYBALL_RUNNER_STARTING_Y = 8.25
    SEEKER_FLOOR_SECONDS = 20 * 60  # 20 minutes before seeker can enter
    FLAG_RUNNER_FLOOR_SECONDS = 19 * 60  # 19 minutes before flag runner can enter
    FLAG_RUNNER_RADIUS = PLAYER_RADIUS
    FLAG_RUNNER_MAX_SPEED_REAL = 2.5  # m/s per real second
    FLAG_RUNNER_MAX_SPEED = FLAG_RUNNER_MAX_SPEED_REAL / GAME_TIME_TO_REAL_TIME_RATIO
    FLAG_RUNNER_MIN_SPEED = 0  # computer driven, so no minimum speed like for computer players
    FLAG_RUNNER_ACCELERATION_REAL = 6  # m/s2 per real second
    FLAG_RUNNER_ACCELERATION = FLAG_RUNNER_ACCELERATION_REAL / GAME_TIME_TO_REAL_TIME_RATIO
    FLAG_RUNNER_DEACCELERATION_RATE = 0.5  # ratio of speed lost per second
    FLAG_RUNNER_MIN_DIR = 0  # computer driven, so no minimum direction like for computer players
    FLAG_RUNNER_RANDOM_DIRECTION_FACTOR = 0.5  # how much randomness is added to the flag runner's direction
    FLAG_RUNNER_SEEKER_AVOIDANCE_FACTOR = 0.5  # how strongly the flag runner avoids seekers
    FLAG_RUNNER_BOUNDARY_AVOIDANCE_FACTOR = 5.0  # how strongly the flag runner avoids pitch boundaries
    FLAG_RUNNER_BOUNDARY_EPSILON = 1e-5  # prevents division by zero in boundary avoidance
    FLAG_RUNNER_INTERACTION_TIME_THRESHOLD = 2.0  # time in game time seconds that a seeker must be in contact with the flag runner to "catch" it
    FLAG_RUNNER_CATCH_PROBABILITY = 1 / 20 # probability that a seeker will catch the flag runner if they are in contact for the interaction time threshold (catch_attempt)
    FLAG_CATCH_CONTINUE_TIMER_REAL_SECONDS = 20.0  # time in real seconds to continue the flag catch after a seeker has caught the flag runner. We want to have some time to show an information message
    FLAG_CATCH_CONTINUE_TIMER = FLAG_CATCH_CONTINUE_TIMER_REAL_SECONDS * GAME_TIME_TO_REAL_TIME_RATIO
    # Tutorial only, restored when the next scenario starts. The elastic collision
    # pushes seeker and runner apart on contact, so holding the live 2 s of unbroken
    # contact is rare: a seeker chasing head-on earns a roll only every ~9 s, which
    # even at 1/3 leaves the catch demo taking half a minute or more. A shorter
    # threshold is what makes it land in ~10 s while still needing luck.
    TUTORIAL_FLAG_RUNNER_CATCH_PROBABILITY = 1 / 3
    TUTORIAL_FLAG_RUNNER_INTERACTION_TIME_THRESHOLD = 1.0


    N_CHASERS_TEAM_0 = 3
    N_CHASERS_TEAM_1 = 3
    N_KEEPERS_TEAM_0 = 1
    N_KEEPERS_TEAM_1 = 1
    N_BEATERS_TEAM_0 = 2
    N_BEATERS_TEAM_1 = 2
    N_SEEKERS_TEAM_0 = 1
    N_SEEKERS_TEAM_1 = 1


    COMPUTER_PLAYER_TICK_RATE = 5 # number of game ticks between computer player updates
    COMPUTER_PLAYER_MIN_DIR = 0
    COMPUTER_PLAYER_MIN_SPEED_REAL = 0
    COMPUTER_PLAYER_MIN_SPEED = COMPUTER_PLAYER_MIN_SPEED_REAL / GAME_TIME_TO_REAL_TIME_RATIO
    COMPUTER_PLAYER_LOG_LEVEL = logging.DEBUG
    COMPUTER_PLAYER_KWARGS = {
        # 'throwing_probability': 0.3, # for RandomComputerPlayer, probability of throwing each tick
        'move_buffer_factor_x': 1.4, # for ComputerPlayerOrchestrator move_around_hoop_blockage, how much m extra space to add when blocking the hoop with the volleyball, to ensure blockage but not cause unnecessary movement
        'move_buffer_factor_y': 1.4, # for ComputerPlayerOrchestrator move_around_hoop_blockage, how much m extra space to add when blocking the hoop with the volleyball, to ensure blockage but not cause unnecessary movement
        'scoring_kwargs': { # ScoreAttempter, shared by the base attack and the moves
            'score_squared_max_distance': 8**2, # maximum squared distance from volleyball to consider scoring
            'scoring_threshold': 0.95, # minimum interception score (chance of not being intercepted) to attempt a score ('beam' model)
            'interception_model': 'time_margin', # 'beam' (angle cone) or 'time_margin' (defender reach time vs shot arrival with ball decay)
            'shot_time_margin': -0.25, # game seconds, shoot if the fastest defender reaches the shot at most this much before it arrives ('time_margin' model)
        },
        'passing_kwargs': { # PassEvaluator, shared by the base attack and the moves
            'passing_evade_vector_position_penalty_weight': 100, # pass-to-player score = squared distance to closest attack hoop + weight * squared evade vector magnitude
            'interception_model': 'beam', # 'time_margin' rejects long slow passes and loses goals against the CPU defence at any margin
            'pass_time_margin': 0.0, # game seconds ('time_margin' model)
        },
        'diamond_attack_kwargs': {
            'chaser_keeper': {
                'chaser_evade_beater_weight': 3.5,
                'chaser_evade_chaser_keeper_weight': 1.0,
                'chaser_evade_teamate_chaser_keeper_weight': 1.5,
                'chaser_pull_teammate_chaser_keeper_distance': 20, # m, beyond this the quadratic pull to a teammate outweighs the teammate evasion (max passing distance)
                'volleyball_holder_evade_own_hoop_weight': (0.5, 1.0), # first weight x-axis, second weight y-axis. Larger y because of hoop radius
                'positioning_boundary_buffer_distance': 3, # distance from boundary at which to start evading boundary
                'passing_threshold': 0.95, # minimum interception score (chance of not being intercepted) to attempt a pass
                'passing_squared_max_distance': 20**2, # maximum squared distance from volleyball to consider passing (also used by moves)
            },
            'beater': {
                'unloaded_beater_evade_loaded_opponent_beater_weight': -20, # if opponent beater is loaded, we want to be closer to them to try to get the ball from them, so negative weight for evade vector, but if they are unloaded then we want to be farther away from them to avoid getting hit, so positive weight for evade vector
                'loaded_beater_evade_loaded_opponent_beater_weight': -15,
                'loaded_beater_evade_unloaded_opponent_beater_weight': 4.0,
            },
        },
        'hoop_defence_kwargs': {
            'chaser_keeper': {},
            'beater': {
                'beater_evade_beater_buddy_weight': 3,
                'beater_evade_volleyball_weight': -3.5, # negative for anti-evade
                'beater_evade_chaser_keeper_weight': -0.5, # negative for anti-evade
                'loaded_beater_evade_beater_weight': 2, # loaded beaters evade other beaters
                'unloaded_beater_evade_beater_weight': -2, # unloaded beaters try to make contact with other close opponent beaters
                'unloaded_beater_max_x_to_midline': 8, # 11 would be stick to keeper zone, 0 would be got up to midline
                'positioning_boundary_buffer_distance': 3, # distance from boundary at which to start evading boundary
            },
        },
        'box_defence_probability': 0.5, # chance that a team uses the box defence instead of the hoop defence for chasers/keeper, drawn each time it starts defending
        'box_defence_kwargs': {
            'chaser_keeper': {
                'marking_distance': 1.5, # m from the marked opponent towards the volleyball (passing lane)
                'marking_max_distance': 10, # m, only opponent chasers/keepers this close to the volleyball are marked
                'hoop_clearance_x': 1.0, # m, box players stay at least this far in front of the hoops
                'min_defender_distance': 3.0, # m, the marker keeps at least this distance from the defender going for the volleyball
                'max_y_offset': 7.0, # m, pressers/markers stay within this y distance of the centre hoop; opponents further to the sides are not marked
            },
        },
        'beater_throw_threshold_volleyball_holder': 5, # distance in m for beater to throw at volleyball holder
        'beater_throw_threshold_loaded_beater': 4, # distance in m for beater to throw at loaded opponent beater
        'possession_kwargs': { # VolleyballPossessionCalculator, loose volleyball
            'possession_switch_margin': 0.0, # game seconds the other team has to be faster to take over the predicted possession
            'loose_ball_contest_margin': 1.5, # game seconds; the other team's fastest player also races for the volleyball if at most this much slower (None: off)
        },
        'dodge_kwargs': { # DodgeballDodger
            'dodge_horizon': 2.0, # game seconds; CPU players sidestep an opponent dodgeball that would hit them within this time (None: off)
            'dodge_buffer': 0.3, # m added to the hit distance (player radius + ball radius)
        },
        'cherry_pick_kwargs': { # CherryPicker, close beats of unprotected opponent chasers/keepers by loaded beaters
            'cherry_pick_distance': 1.5, # m, throw when the target is this close (None: off)
            'follow_distance': 3.0, # m, follow a target this close until it is within the cherry pick distance (None: no following)
            'follow_duration': 1.5 * GAME_TIME_TO_REAL_TIME_RATIO, # game seconds, give up following after 1.5 real seconds
            'protection_radius': 4.0, # m, no loaded opponent beater this close to the target or the beater
            'recovery_margin': 1.0, # m, the beater is closer to the target (rebound) than every opponent beater by this
            'own_hoop_safe_distance': 15.0, # m, on defence only when the volleyball is at least this far from the own hoops
            'include_seekers': True, # the opponent seeker is a cherry pick target too while the seekers are on pitch
            'protect_carrier_distance': 2.0, # m, on attack an opponent chaser/keeper this close to the own carrier is followed and beaten with priority (None: off)
        },
        'beater_seeker_focus_kwargs': { # BeaterSeekerFocus, once the seekers are on pitch
            'seeker_focus_beaters': 2, # beaters per team (closest to the own seeker) that play the seeker game instead of the volleyball game; 0: off
            'guard_distance': 2.0, # m, focus beaters stand this far from the own seeker towards the closest loaded opponent beater
            'throw_distance': 5.0, # m, focus beaters only throw at targets this close
            'loaded_beater_threat_distance': 8.0, # m, loaded opponent beaters this close to the own seeker are beaten
            'opponent_seeker_threat_distance': 4.0, # m, the opponent seeker is beaten when this close to the flag runner
            'seeker_focus_probability': 2 / 3, # chance that a team plays the seeker phase with seeker focus beaters (otherwise all beaters keep the volleyball focus), drawn when the seekers enter
        },
        'moves': { # sampled by the ComputerPlayerOrchestrator; times in game seconds
            'volleyball_shift': {
                'start_probability_per_second': 0.0, # probability that the move is tried within one game second
                'cooldown': 3, # after the move ended, before the same team may start it again
                'max_duration': 12, # timeout
                'attack_line_fraction': 0.6, # participants must be past 3/5 of the pitch seen from their own end
                'min_participants': 3, # on-stick CPU chasers/keepers past the attack line, carrier included
                'pass_interception_threshold': 1.0, # >= 1: no opponent chaser/keeper in the interception cone
                'loaded_beater_radius': 7, # m, no loaded opponent beater this close to the receiver
                'max_pass_penalty_worsening': 100, # m^2, how much worse the receiver's pass-to-player score may be than the carrier's (e.g. 10 m -> 14 m from the hoops)
                'delay_of_game_fraction': 0.5, # stop once the delay of game timer reaches this fraction of the limit
            },
            'volleyball_drive': {
                'start_probability_per_second': 0.0, # probability that the move is tried within one game second
                'cooldown': 3, # after the move ended, before the same team may start it again
                'max_duration': 5 * GAME_TIME_TO_REAL_TIME_RATIO, # timeout, 5 real seconds
                'min_chaser_keepers': 3, # chasers/keepers of the team not knocked out
                'dodgeball_pass_distance': 3, # m, pass when an opponent live dodgeball is closer than this to the carrier
                'tackle_window': 1.0, # pass when the carrier was tackled within this time (tackles are one-shot actions)
                'pass_interception_threshold': 0.95, # minimum interception score of the pass
                'hoop_switch_margin': 0.2, # interception score another hoop must be better by to change the target hoop
            },
            'volleyball_shift_drive': { # volleyball_shift, then volleyball_drive for the new carrier if the second pass was caught
                'start_probability_per_second': 0.3, # probability that the move is tried within one game second
                'cooldown': 3,
                'shift': {
                    'max_duration': 12,
                    'attack_line_fraction': 0.6,
                    'min_participants': 3,
                    'pass_interception_threshold': 1.0,
                    'loaded_beater_radius': 7,
                    'max_pass_penalty_worsening': 100,
                    'delay_of_game_fraction': 0.5,
                },
                'drive': {
                    'max_duration': 5 * GAME_TIME_TO_REAL_TIME_RATIO,
                    'min_chaser_keepers': 3,
                    'dodgeball_pass_distance': 3,
                    'tackle_window': 1.0,
                    'pass_interception_threshold': 0.95,
                    'hoop_switch_margin': 0.2,
                },
            },
            'volleyball_crossing_drive': { # volleyball_crossing (scissors in front of a defender), then volleyball_drive after the exit run
                'start_probability_per_second': 0.3, # probability that the move is tried within one game second
                'cooldown': 3,
                'crossing': {
                    'max_duration': 15, # timeout of the crossing incl. exit run
                    'teammate_max_distance': 20, # m, receiver at most this far from the carrier (max passing distance)
                    'teammate_min_lateral': 2, # m, receiver at least this far to the side (y) of the carrier, so the paths cross
                    'opponent_max_distance': 10, # m, defender at most this far from the midpoint of carrier and receiver
                    'crossing_distance': 1.6, # m, crossing point in front of the defender (towards the attackers)
                    'min_approach_distance': 1.5, # m, both runners at least this far behind the crossing point at the start
                    'hoop_clearance': 2.0, # m, crossing point at least this far in front of the opponent hoop line
                    'receiver_behind_distance': 1.0, # m, the receiver crosses this far behind the carrier's crossing point (no contact)
                    'receiver_time_gap': 0.5, # game s the receiver reaches its crossing point after the carrier reaches its own
                    'min_stick_input': 0.2, # lowest stick input when slowing down to keep the timing (low, so the carrier can wait for a far receiver)
                    'loaded_beater_path_distance': 4, # m, no loaded opponent beater this close to the paths to the crossing point
                    'blocking_path_distance': 1.5, # m, no other opponent chaser/keeper this close to the paths to the crossing point
                    'exit_angle': 45, # degrees of the exit lines from the attack direction
                    'opponent_prediction_time': 1.0, # game s; pass if the defender will then be closer to the carrier than to the receiver, else dummy
                    'pass_interception_threshold': 0.95, # minimum interception score of the pass at the crossing
                    'max_pass_distance': 4, # m, carrier-receiver distance at the crossing above which the move fails (out of sync)
                    'exit_duration': 2.0, # game s the holder runs its exit line before the drive starts
                    'tackle_window': 1.0, # carrier counts as tackled this long after a tackle
                },
                'drive': {
                    'max_duration': 5 * GAME_TIME_TO_REAL_TIME_RATIO,
                    'min_chaser_keepers': 3,
                    'dodgeball_pass_distance': 3,
                    'tackle_window': 1.0,
                    'pass_interception_threshold': 0.95,
                    'hoop_switch_margin': 0.2,
                },
            },
            'volleyball_block_drive': { # volleyball_block (a teammate screens the one defender who could intercept the drive), then volleyball_drive once the defender is passed
                'start_probability_per_second': 0.3,
                'cooldown': 3,
                'block': {
                    'max_duration': 10, # timeout of the block phase
                    'blocker_max_distance': 20, # m, blocker at most this far from the carrier (max passing distance)
                    'block_offset': 0.9, # m, the screen spot is this far beside the defender, on the side the blocker comes from (about body contact)
                    'block_set_width': 0.8, # m, block counts as set once the blocker is this close to the screen spot
                    'max_lead_time': 1.5, # game s, the blocker aims at the screen spot moved by the defender's velocity times its arrival time, at most this
                    'max_setup_time': 4.0, # game s, the blocker reaches the screen spot within this time at the start
                    'unset_stick_input': 0.2, # lowest carrier stick input while waiting for the screen (the carrier is synced to reach the lane when it stands)
                    'screen_clearance': 1.5, # m, the carrier's lane is this far beyond the screen spot
                    'loaded_beater_path_distance': 4, # m, no loaded opponent beater this close to the carrier's run to the lane at the start
                    'second_interceptor_margin': 0.0, # game s, the next opponent can intercept the run at least this much later than the blocked defender (0: no condition; CPU defenders cluster, gaps are mostly < 0.5 s)
                    'min_defender_hoop_distance': 3.0, # m, the defender is at least this far from the target hoop (no hoop guard)
                    'min_defender_distance': 4.0, # m, the defender is at least this far from the carrier at the start
                    'max_defender_closing_speed': 0.5, # m/s, the defender runs at the carrier at most this fast at the start (a pressing defender cannot be screened)
                    'tackle_window': 1.0, # carrier counts as tackled this long after a tackle
                },
                'drive': {
                    'max_duration': 5 * GAME_TIME_TO_REAL_TIME_RATIO,
                    'min_chaser_keepers': 3,
                    'dodgeball_pass_distance': 3,
                    'tackle_window': 1.0,
                    'pass_interception_threshold': 0.95,
                    'hoop_switch_margin': 0.2,
                },
            },
        },
    }


  