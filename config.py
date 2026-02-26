import logging

class Config:
    GAME_LOGIC_UPDATE_LOG_LEVEL = logging.DEBUG
    FPS = 20 # frame rate per 
    GAME_TIME_TO_REAL_TIME_RATIO = 3 # 1 second real time = 3 seconds game time
    PITCH_WIDTH = 33
    PITCH_LENGTH = 60
    HOOP_X = 13.5
    KEEPER_ZONE_X = 19
    HOOP_DISTANCES = 2.75
    HOOP_RADIUS = 0.86/2 #  The inner diameter of each hoop loop must be between 81 centimeters and 86 centimeters
    HOOP_THICKNESS = 0.1
    VOLLEYBALL_RADIUS = 0.67 / 2 / 3.14 # 65 centimeters to 67 centimeters in circumference (approximately 0.106 m)
    DODGEBALL_RADIUS = 0.70 / 2 / 3.14 # 68 centimeters and 70 centimeters in circumference (approximately 0.111 m)
    PLAYER_RADIUS = 0.3

    PLAYER_MAX_SPEED_REAL = 3 # m/s per real second
    PLAYER_MIN_SPEED_REAL = 1 # m/s per real second
    PLAYER_THROW_VELOCITY_REAL = 12 # m/s per real second
    PLAYER_ACCELERATION_REAL = 3 # m/s2 per real second
    PLAYER_DEACCELERATION_RATE = 0.5 # ratio of speed lost per second
    PLAYER_MAX_SPEED = PLAYER_MAX_SPEED_REAL / GAME_TIME_TO_REAL_TIME_RATIO
    PLAYER_MIN_SPEED = PLAYER_MIN_SPEED_REAL / GAME_TIME_TO_REAL_TIME_RATIO
    PLAYER_THROW_VELOCITY = PLAYER_THROW_VELOCITY_REAL / GAME_TIME_TO_REAL_TIME_RATIO
    PLAYER_ACCELERATION = PLAYER_ACCELERATION_REAL / GAME_TIME_TO_REAL_TIME_RATIO
    PLAYER_MIN_DIR = 0.6 # of 1 

    BALL_DEACCELERATION_RATE = 0.15 # ratio of speed lost per second
    BALL_REFLECT_VELOCITY_LOSS = 0.4 # ratio of velocity lost on reflection with player

    DODGEBALL_DEAD_VELOCITY_THRESHOLD_REAL = 4 # velocity m/s real when dodgeball becomes dead
    DODGEBALL_DEAD_VELOCITY_THRESHOLD = DODGEBALL_DEAD_VELOCITY_THRESHOLD_REAL / GAME_TIME_TO_REAL_TIME_RATIO

    DELAY_OF_GAME_TIME_LIMIT = 7.0  # game seconds before delay of game warning/penalty
    DELAY_OF_GAME_VELOCITY_X_THRESHOLD_REAL = 1.4  # m/s in x direction the volleyball must exceed to avoid delay of game; should be slow running speed
    DELAY_OF_GAME_VELOCITY_X_THRESHOLD = DELAY_OF_GAME_VELOCITY_X_THRESHOLD_REAL / GAME_TIME_TO_REAL_TIME_RATIO
    MAX_DELAY_OF_GAME_WARNINGS = 1  # Number of warnings before penalty per team

    BEAT_ATTEMPT_TIME_LIMIT = 5 # game seconds ball has time to beat player before potential third dodgeball interference
    
    VOLLEYBALL_RUNNER_STARTING_Y = 8.25
    SEEKER_FLOOR_REAL_SECONDS = 20 * 60  # 20 minutes before seeker can enter

    N_CHASERS_TEAM_0 = 3
    N_CHASERS_TEAM_1 = 3
    N_KEEPERS_TEAM_0 = 1
    N_KEEPERS_TEAM_1 = 1
    N_BEATERS_TEAM_0 = 2
    N_BEATERS_TEAM_1 = 2


    COMPUTER_PLAYER_TICK_RATE = 5 # number of game ticks between computer player updates
    COMPUTER_PLAYER_MIN_DIR = 0
    COMPUTER_PLAYER_MIN_SPEED_REAL = 0
    COMPUTER_PLAYER_MIN_SPEED = COMPUTER_PLAYER_MIN_SPEED_REAL / GAME_TIME_TO_REAL_TIME_RATIO
    COMPUTER_PLAYER_LOG_LEVEL = logging.DEBUG
    COMPUTER_PLAYER_KWARGS = {
        # 'throwing_probability': 0.3, # for RandomComputerPlayer, probability of throwing each tick
        'move_buffer_factor': 1.2, # for RuleBasedComputerPlayer, how much m extra space to add when blocking the hoop with the volleyball, to ensure blockage but not cause unnecessary movement
        'determine_attacking_team_max_dt_steps': 10, # for RuleBasedComputerPlayer, how many dt steps to look ahead when determining attacking team based on interception ratio
        'determine_attacking_team_max_distance_per_step': 2 * PLAYER_RADIUS, # for RuleBasedComputerPlayer, max distance to move per step when determining attacking team based on interception ratio
        'determine_attacking_team_max_dt_per_step': 0.3 * GAME_TIME_TO_REAL_TIME_RATIO, # for RuleBasedComputerPlayer, max dt per step when determining attacking team based on interception ratio in s GAME_TIME
        'score_interception_max_dt_steps': 20, # for RuleBasedComputerPlayer, how many dt steps to look ahead when scoring
        'score_interception_max_distance_per_step': 2 * PLAYER_RADIUS, # for RuleBasedComputerPlayer, max distance to move per step when scoring
        'score_interception_max_dt_per_step': 0.3 * GAME_TIME_TO_REAL_TIME_RATIO, # for RuleBasedComputerPlayer, max dt per step when scoring in s GAME_TIME
        'scoring_threshold': 0.95, # for RuleBasedComputerPlayer, minimum interception score (chance of not being intercepted) to attempt a score
        'evade_beater_distance': 4, # for RuleBasedComputerPlayer, distance at which to attempt to evade beaters (in m)
        'evade_chaser_keeper_distance': 2, # for RuleBasedComputerPlayer, distance at which to attempt to evade chasers/keepers (in m)
        'simulation_game_logic_log_level': logging.ERROR # for RuleBasedComputerPlayer, log level to use for the simulated game logic when determining attacking team (set higher than logging.INFO to reduce output)
    }


  