import streamlit as st
import random
import math
import re
import pandas as pd
from dataclasses import dataclass, field, asdict # Import asdict for potential JSON if needed
from typing import List, Dict, Optional, Tuple

# import pickle # Added for state persistence
import cloudpickle as pickle # Using cloudpickle instead of pickle for Streamlit compatibility
import os # Added for file operations

# --- Data Structures ---

@dataclass
class Match:
    pit: int
    team1: List[str]
    team2: List[str]
    score_team1: Optional[int] = None
    score_team2: Optional[int] = None

@dataclass
class Round:
    round_number: int
    matches: List[Match]
    byes: List[str]

@dataclass
class MixerResult:
    rounds: List[Round]
    games_per_player: int
    num_rounds: int
    player_stats: Dict[str, Dict[str, int]] = field(default_factory=dict)
    opponent_matrix: Dict[str, Dict[str, int]] = field(default_factory=dict)
    partner_matrix: Dict[str, Dict[str, int]] = field(default_factory=dict)
    num_players_with_extra_games: int = 0 # Added to track players exceeding target
    players_to_asterisk: Dict[str, Tuple[int, int]] = field(default_factory=dict) # New: Stores (round, pit) for last extra game

@dataclass
class MixerConfig:
    players_text: str
    target_games_per_player: int
    num_pits: int

@dataclass
class MixerState:
    config: MixerConfig
    result: Optional[MixerResult] = None
    error: Optional[str] = None

# --- Helper Functions ---

DEFAULT_PLAYERS = ""

def shuffle(arr):
    a = list(arr)
    random.shuffle(a)
    return a

def inc(pair_map, a, b):
    if a not in pair_map:
        pair_map[a] = {}
    if b not in pair_map: # Ensure b is in the top-level map
        pair_map[b] = {}
    pair_map[a][b] = pair_map[a].get(b, 0) + 1
    pair_map[b][a] = pair_map[b].get(a, 0) + 1

def get(pair_map, a, b):
    return pair_map.get(a, {}).get(b, 0)

def score_arrangement(
    active,
    partner_count,
    opponent_count,
    pit_count
):
    score = 0
    for i in range(0, len(active), 4):
        if i + 3 >= len(active):
            break
        p1, p2, p3, p4 = active[i : i + 4]
        pit = (i // 4) + 1

        score += get(partner_count, p1, p2) * 2
        score += get(partner_count, p3, p4) * 2

        score += get(opponent_count, p1, p3)
        score += get(opponent_count, p1, p4)
        score += get(opponent_count, p2, p3)
        score += get(opponent_count, p2, p4)

        score += get(pit_count, p1, pit)
        score += get(pit_count, p2, pit)
        score += get(pit_count, p3, pit)
        score += get(pit_count, p4, pit)

    return score

# --- generate_schedule function ---

def generate_schedule(config: MixerConfig, arrangement_attempts: int = 5000) -> MixerState:
    players_text = config.players_text
    target_games_per_player = config.target_games_per_player
    num_pits = config.num_pits

    # Make sure players are unique
    raw_players = [p.strip() for p in re.split(r'[\n,]+', players_text) if p.strip()]
    players = list(dict.fromkeys(raw_players))

    if len(players) < 4:
        return MixerState(
            config=config,
            error="At least 4 players are required to generate a schedule.",
        )
    if not (1 <= num_pits <= 10):
        return MixerState(
            config=config,
            error="Number of pits must be between 1 and 10.",
        )
    if not (1 <= target_games_per_player <= 50):
        return MixerState(
            config=config,
            error="Target games per player must be between 1 and 50.",
        )

    slots_per_round = num_pits * 4
    active_slots_per_round = (min(len(players), slots_per_round) // 4) * 4

    if active_slots_per_round == 0:
        return MixerState(
            config=config,
            error="Not enough active slots for any matches. Check number of players and pits."
        )

    num_rounds = math.ceil((target_games_per_player * len(players)) / active_slots_per_round)

    games_played: Dict[str, int] = {p: 0 for p in players}
    byes_count: Dict[str, int] = {p: 0 for p in players}
    partner_count: Dict[str, Dict[str, int]] = {}
    opponent_count: Dict[str, Dict[str, int]] = {}
    pit_count: Dict[str, Dict[int, int]] = {p: {} for p in players}

    rounds: List[Round] = []

    for r in range(num_rounds):
        # Separate players into categories
        players_needing_games = [p for p in players if games_played[p] < target_games_per_player]
        players_at_target = [p for p in players if games_played[p] == target_games_per_player]
        players_above_target = [p for p in players if games_played[p] > target_games_per_player]

        # Shuffle each category for randomness among players of equal priority
        random.shuffle(players_needing_games)
        random.shuffle(players_at_target)
        random.shuffle(players_above_target)

        # Sort within categories:
        # Players needing games: those with fewer games get higher priority to reach target
        players_needing_games.sort(key=lambda p: games_played[p])
        # Players above target: those with fewer 'extra' games are preferred if they must play (minimizing overshoot)
        players_above_target.sort(key=lambda p: games_played[p])

        active_this_round_candidates = []

        # 1. Prioritize players who still need games
        active_this_round_candidates.extend(players_needing_games)

        # 2. Add players who are at target (if slots remain)
        active_this_round_candidates.extend(players_at_target)

        # 3. Add players who are above target (if slots still remain and they are needed to fill matches)
        active_this_round_candidates.extend(players_above_target)

        # Now, select the actual 'active' players up to active_slots_per_round
        # The active_slots_per_round calculation already ensures it's a multiple of 4.
        active = active_this_round_candidates[:active_slots_per_round]

        # All players not in the 'active' list for this round are byes.
        byes = sorted(list(set(players) - set(active)))

        # Determine the arrangement of active players into pits
        if r == num_rounds - 1: # Special logic for the last round
            final_last_round_arrangement = []

            # Separate active players based on game count relative to target
            players_below_or_at_target_active = [p for p in active if games_played[p] <= target_games_per_player]
            players_above_target_active = [p for p in active if games_played[p] > target_games_per_player]

            # Randomize within these groups to maintain some fairness for internal pairing choices
            random.shuffle(players_below_or_at_target_active)
            random.shuffle(players_above_target_active)

            temp_available_players_for_pit_selection = { # Use a mutable copy for pop()
                'below_or_at': list(players_below_or_at_target_active),
                'above': list(players_above_target_active)
            }

            # Fill pits according to priority
            for _ in range(active_slots_per_round // 4): # Iterate for each pit that needs to be filled
                pit_group = []

                # First, try to fill with players below or at target
                while len(pit_group) < 4 and temp_available_players_for_pit_selection['below_or_at']:
                    pit_group.append(temp_available_players_for_pit_selection['below_or_at'].pop(0))

                # If pit still not full, use players above target
                while len(pit_group) < 4 and temp_available_players_for_pit_selection['above']:
                    pit_group.append(temp_available_players_for_pit_selection['above'].pop(0))

                if len(pit_group) == 4: # Only add if a full pit can be formed
                    # Now, arrange these 4 players within the pit to minimize previous pairings
                    best_pit_sub_arrangement = shuffle(pit_group) # Initial random arrangement
                    best_pit_sub_score = float('inf')

                    # Perform a small number of attempts to find the best internal arrangement for this pit
                    for _attempt_sub in range(50):
                        current_sub_arrangement = shuffle(pit_group)
                        # Score based on internal pairings (partner/opponent counts)
                        p1, p2, p3, p4 = current_sub_arrangement[0:4]
                        sub_score = (get(partner_count, p1, p2) + get(partner_count, p3, p4)) * 2 + \
                                    get(opponent_count, p1, p3) + get(opponent_count, p1, p4) + \
                                    get(opponent_count, p2, p3) + get(opponent_count, p2, p4)

                        if sub_score < best_pit_sub_score:
                            best_pit_sub_score = sub_score
                            best_pit_sub_arrangement = current_sub_arrangement
                    final_last_round_arrangement.extend(best_pit_sub_arrangement)
                # If len(pit_group) < 4, it means we couldn't form a full pit for some reason,
                # which should ideally not happen given active_slots_per_round is a multiple of 4
                # and active has that many players.

            best_arrangement = final_last_round_arrangement

        else: # Original logic for non-last rounds
            # Try many random arrangements of the active players and keep the best
            best_arrangement = shuffle(active)
            best_score = score_arrangement(best_arrangement, partner_count, opponent_count, pit_count)

            for attempt in range(arrangement_attempts):
                candidate = shuffle(active)
                s = score_arrangement(candidate, partner_count, opponent_count, pit_count)
                if s < best_score:
                    best_score = s
                    best_arrangement = candidate
                    if s == 0:
                        break

        # Build matches from the best arrangement
        matches: List[Match] = []
        for i in range(0, len(best_arrangement), 4):
            if i + 3 >= len(best_arrangement):
                break
            p1, p2, p3, p4 = best_arrangement[i : i + 4]
            pit_num = (i // 4) + 1
            matches.append(
                Match(pit=pit_num, team1=[p1, p2], team2=[p3, p4])
            )

            # Record partnerships, opposition, and pit usage for future rounds
            inc(partner_count, p1, p2)
            inc(partner_count, p3, p4)
            inc(opponent_count, p1, p3)
            inc(opponent_count, p1, p4)
            inc(opponent_count, p2, p3)
            inc(opponent_count, p2, p4)

            for p in [p1, p2, p3, p4]:
                if pit_num not in pit_count[p]:
                    pit_count[p][pit_num] = 0
                pit_count[p][pit_num] += 1

        # Update games played and byes count for this round
        for p in active:
            games_played[p] += 1
        for p in byes:
            byes_count[p] += 1

        rounds.append(
            Round(round_number=r + 1, matches=matches, byes=sorted(byes))
        )

    # Calculate games per player based on the minimum played
    min_games_played = min(games_played.values()) if games_played else 0

    # Consolidate player statistics and count players with extra games
    player_final_stats = {}
    num_extra_games_players = 0
    players_to_asterisk: Dict[str, Tuple[int, int]] = {}

    for p in players:
        player_final_stats[p] = {
            'games': games_played[p],
            'byes': byes_count[p]
        }
        if games_played[p] > target_games_per_player:
            num_extra_games_players += 1

    # Determine the *last* game for players who exceeded the target
    for p in players:
        if player_final_stats[p]['games'] > target_games_per_player:
            # Iterate rounds in reverse to find the last game they played
            for r_idx in range(len(rounds) - 1, -1, -1):
                round_data = rounds[r_idx]
                for match in round_data.matches:
                    if p in match.team1 or p in match.team2:
                        players_to_asterisk[p] = (round_data.round_number, match.pit)
                        break # Found the last game for this player, move to next player
                if p in players_to_asterisk: # If found in this round, break from round iteration
                    break

    return MixerState(
        config=config,
        result=MixerResult(
            rounds=rounds,
            games_per_player=min_games_played,
            num_rounds=num_rounds,
            player_stats=player_final_stats,
            opponent_matrix=opponent_count,
            partner_matrix=partner_count,
            num_players_with_extra_games=num_extra_games_players,
            players_to_asterisk=players_to_asterisk
        ),
        error=None,
    )

# --- Export Functions ---

def format_schedule_to_text(mixer_state: MixerState) -> str:
    output_lines = []

    if mixer_state.error:
        output_lines.append(f"Error: {mixer_state.error}")
    elif mixer_state.result:
        num_players = len([p.strip() for p in re.split(r'[\n,]+', mixer_state.config.players_text) if p.strip()])
        output_lines.append(f"Schedule generated successfully for {num_players} players over {mixer_state.result.num_rounds} rounds.")
        output_lines.append(f"Minimum games played per player: {mixer_state.result.games_per_player}")
        output_lines.append(f"Players with games > target: {mixer_state.result.num_players_with_extra_games}")

        output_lines.append("\n--- Player Statistics ---")
        for player, stats in mixer_state.result.player_stats.items():
            # Asterisk in summary only if they exceeded the target, for clarity
            asterisk = '*' if stats['games'] > mixer_state.config.target_games_per_player else ''
            output_lines.append(f"{player}{asterisk}: Games Played = {stats['games']}, Byes = {stats['byes']}")

        output_lines.append("\n--- Player Opponent Matrix ---")
        opponent_df = get_opponent_matrix_dataframe(mixer_state)
        output_lines.append(opponent_df.to_string())

        output_lines.append("\n--- Player Partner Matrix ---")
        partner_df = get_partner_matrix_dataframe(mixer_state)
        output_lines.append(partner_df.to_string())

        for round_data in mixer_state.result.rounds:
            output_lines.append(f"\nRound {round_data.round_number}:")
            if round_data.matches:
                output_lines.append("  Matches:")
                for match in round_data.matches:
                    score_str = "" # Initialize an empty string for scores
                    if match.score_team1 is not None and match.score_team2 is not None:
                        score_str = f" ({match.score_team1}-{match.score_team2})"

                    team1_players = []
                    for p in match.team1:
                        if (p in mixer_state.result.players_to_asterisk and
                                mixer_state.result.players_to_asterisk[p] == (round_data.round_number, match.pit)):
                            team1_players.append(f"{p}*")
                        else:
                            team1_players.append(p)

                    team2_players = []
                    for p in match.team2:
                        if (p in mixer_state.result.players_to_asterisk and
                                mixer_state.result.players_to_asterisk[p] == (round_data.round_number, match.pit)):
                            team2_players.append(f"{p}*")
                        else:
                            team2_players.append(p)

                    output_lines.append(f"    Pit {match.pit}: {', '.join(team1_players)} vs {', '.join(team2_players)}{score_str}")
            else:
                output_lines.append("  No matches in this round.")

            if round_data.byes:
                output_lines.append("  Byes:")
                output_lines.append(f"    {', '.join(round_data.byes)}")

            if not round_data.matches and not round_data.byes:
                output_lines.append("  No activity in this round.")

    else:
        output_lines.append("No result or error found.")

    return "\n".join(output_lines)

def format_schedule_to_dataframe(mixer_state: MixerState) -> pd.DataFrame:
    data = []

    if mixer_state.error:
        return pd.DataFrame() # Return empty DataFrame on error

    if not mixer_state.result:
        return pd.DataFrame() # Return empty DataFrame if no result

    for round_data in mixer_state.result.rounds:
        # Process matches
        for match in round_data.matches:
            # Determine if asterisk should be added for team1 players
            team1_p1_name = match.team1[0]
            if (team1_p1_name in mixer_state.result.players_to_asterisk and
                    mixer_state.result.players_to_asterisk[team1_p1_name] == (round_data.round_number, match.pit)):
                team1_p1_name += '*'

            team1_p2_name = match.team1[1]
            if (team1_p2_name in mixer_state.result.players_to_asterisk and
                    mixer_state.result.players_to_asterisk[team1_p2_name] == (round_data.round_number, match.pit)):
                team1_p2_name += '*'

            # Determine if asterisk should be added for team2 players
            team2_p1_name = match.team2[0]
            if (team2_p1_name in mixer_state.result.players_to_asterisk and
                    mixer_state.result.players_to_asterisk[team2_p1_name] == (round_data.round_number, match.pit)):
                team2_p1_name += '*'

            team2_p2_name = match.team2[1]
            if (team2_p2_name in mixer_state.result.players_to_asterisk and
                    mixer_state.result.players_to_asterisk[team2_p2_name] == (round_data.round_number, match.pit)):
                team2_p2_name += '*'

            data.append({
                'Round': round_data.round_number,
                'Pit': match.pit,
                'Team1 Player1': team1_p1_name,
                'Team1 Player2': team1_p2_name,
                'Team2 Player1': team2_p1_name,
                'Team2 Player2': team2_p2_name,
                'Status': 'Playing',
                'Team1 Score': match.score_team1,
                'Team2 Score': match.score_team2
            })

        # Process byes
        for bye_player in round_data.byes:
            data.append({
                'Round': round_data.round_number,
                'Pit': None,
                'Team1 Player1': bye_player,
                'Team1 Player2': None,
                'Team2 Player1': None,
                'Team2 Player2': None,
                'Status': 'Bye',
                'Team1 Score': None,
                'Team2 Score': None
            })

    if not data:
        return pd.DataFrame() # Return empty DataFrame if no data was processed

    df = pd.DataFrame(data)
    return df

def get_opponent_matrix_dataframe(mixer_state: MixerState) -> pd.DataFrame:
    if mixer_state.error or not mixer_state.result or not mixer_state.result.opponent_matrix:
        return pd.DataFrame()

    opponent_matrix_dict = mixer_state.result.opponent_matrix
    players = sorted(list(opponent_matrix_dict.keys()))

    df = pd.DataFrame(0, index=players, columns=players)

    for p1, opponents in opponent_matrix_dict.items():
        for p2, count in opponents.items():
            df.loc[p1, p2] = count

    return df

def get_partner_matrix_dataframe(mixer_state: MixerState) -> pd.DataFrame:
    if mixer_state.error or not mixer_state.result or not mixer_state.result.partner_matrix:
        return pd.DataFrame()

    partner_matrix_dict = mixer_state.result.partner_matrix
    players = sorted(list(partner_matrix_dict.keys()))

    df = pd.DataFrame(0, index=players, columns=players)

    for p1, partners in partner_matrix_dict.items():
        for p2, count in partners.items():
            df.loc[p1, p2] = count

    return df

# --- Streamlit App Layout ---
st.set_page_config(layout="wide", page_title="Scheduling Mixer App")
st.title("Scheduling Mixer")

# Custom CSS for alternating round background colors (for readability)
st.markdown("""
<style>
    .st-emotion-cache-nahz7x div[data-testid="stVerticalBlock"] > div {
        border: 1px solid rgba(49, 51, 63, 0.2);
        border-radius: 0.25rem;
        padding: 1rem;
        margin-bottom: 1rem;
    }
    .round-odd {
        background-color: rgba(0, 100, 200, 0.05);
    }
    .round-even {
        background-color: rgba(200, 200, 200, 0.05);
    }
</style>
""", unsafe_allow_html=True)

# --- State Persistence Functions ---

STATE_FILE_PATH = "mixer_app_state.pkl"

def save_mixer_state_to_file(state: MixerState):
    try:
        with open(STATE_FILE_PATH, "wb") as f:
            pickle.dump(state, f)
        st.sidebar.success("Schedule and scores saved to disk.")
        st.sidebar.info(f"Successfully saved state to {STATE_FILE_PATH}")
    except Exception as e:
        st.sidebar.error(f"Error saving state: {e}")

def load_mixer_state_from_file():
    if os.path.exists(STATE_FILE_PATH):
        try:
            with open(STATE_FILE_PATH, "rb") as f:
                loaded_state = pickle.load(f)

            # --- Backfill players_to_asterisk for older saved states ---
            if loaded_state and loaded_state.result and not hasattr(loaded_state.result, 'players_to_asterisk'):
                st.sidebar.info("Upgrading saved state: Adding 'players_to_asterisk' attribute.")
                loaded_state.result.players_to_asterisk = {}

                # Re-calculate players_to_asterisk for the loaded state
                players = [p.strip() for p in re.split(r'[\n,]+', loaded_state.config.players_text) if p.strip()]
                target_games_per_player = loaded_state.config.target_games_per_player

                for p in players:
                    if loaded_state.result.player_stats[p]['games'] > target_games_per_player:
                        for r_idx in range(len(loaded_state.result.rounds) - 1, -1, -1):
                            round_data = loaded_state.result.rounds[r_idx]
                            for match in round_data.matches:
                                if p in match.team1 or p in match.team2:
                                    loaded_state.result.players_to_asterisk[p] = (round_data.round_number, match.pit)
                                    break # Found the last game for this player, move to next player
                            if p in loaded_state.result.players_to_asterisk: # If found in this round, break from round iteration
                                break
            # --- End backfill ---

            st.sidebar.info(f"Successfully loaded state from {STATE_FILE_PATH}")
            return loaded_state
        except Exception as e:
            st.sidebar.error(f"Error loading saved state: {e}. Starting fresh.")
            if os.path.exists(STATE_FILE_PATH): # Only remove if it exists to avoid error
                os.remove(STATE_FILE_PATH)
            return None
    else:
        st.sidebar.info(f"No saved state found at {STATE_FILE_PATH}. Starting fresh.")
    return None

# Initialize session_state for mixer_state if not present or after reset
if "mixer_state" not in st.session_state:
    st.session_state["mixer_state"] = load_mixer_state_from_file()
    st.session_state['edit_mode_rounds'] = {} # Initialize edit_mode_rounds here when state is first set up

# Set initial values for sidebar widgets based on loaded/current state
if st.session_state["mixer_state"] and st.session_state["mixer_state"].config:
    players_text_initial = st.session_state["mixer_state"].config.players_text
    num_pits_initial = st.session_state["mixer_state"].config.num_pits
    target_games_per_player_initial = st.session_state["mixer_state"].config.target_games_per_player
    if st.session_state["mixer_state"].result: # Only show info if there's an actual result
        st.sidebar.success("Loaded previous schedule and scores.")
else:
    players_text_initial = DEFAULT_PLAYERS
    num_pits_initial = 3
    target_games_per_player_initial = 6

# Determine if inputs should be disabled (i.e., if a schedule is currently active)
is_schedule_active = (st.session_state["mixer_state"] is not None and st.session_state["mixer_state"].result is not None)

has_any_score_entered = False
if is_schedule_active and st.session_state["mixer_state"].result:
    for round_data in st.session_state["mixer_state"].result.rounds:
        for match in round_data.matches:
            if match.score_team1 is not None or match.score_team2 is not None:
                has_any_score_entered = True
                break
        if has_any_score_entered:
            break

# Input widgets
st.sidebar.header("Configuration")

players_text = st.sidebar.text_area(
    "Players (comma, newline, or space separated)",
    value=players_text_initial,
    height=150,
    disabled=is_schedule_active # Disable if schedule is active
)

# Live player count in sidebar
current_players = [p.strip() for p in re.split(r'[\n,]+', players_text) if p.strip()]
st.sidebar.write(f"Total Players: **{len(current_players)}**")

num_pits = st.sidebar.slider(
    "Number of Pits",
    min_value=1, max_value=10, value=num_pits_initial, step=1,
    disabled=is_schedule_active # Disable if schedule is active
)
target_games_per_player = st.sidebar.slider(
    "Target Games per Player",
    min_value=1, max_value=50, value=target_games_per_player_initial, step=1,
    disabled=is_schedule_active # Disable if schedule is active
)

# Regenerate Schedule button with confirmation
if "confirm_regenerate_pending" not in st.session_state:
    st.session_state["confirm_regenerate_pending"] = False

button_label = "Re-Generate Schedule" if is_schedule_active else "Generate Schedule"
if st.sidebar.button(button_label, key="regenerate_button", disabled=has_any_score_entered):
    if is_schedule_active: # If a schedule is already active, ask for confirmation to re-generate
        st.session_state["confirm_regenerate_pending"] = True
    else: # If no schedule active, generate immediately
        config = MixerConfig(
            players_text=players_text,
            target_games_per_player=target_games_per_player,
            num_pits=num_pits
        )
        mixer_state = generate_schedule(config)
        st.session_state["mixer_state"] = mixer_state
        st.session_state['current_round_scores'] = {} # Reset scores input dict
        if mixer_state.result:
            save_mixer_state_to_file(mixer_state)
        st.rerun()

if st.session_state["confirm_regenerate_pending"]:
    st.sidebar.warning("Are you sure you want to re-generate the schedule? Current scores will be cleared.")
    col1_reg, col2_reg = st.sidebar.columns(2)
    with col1_reg:
        if st.button("Confirm Re-Generate", key="confirm_regenerate_button", disabled=has_any_score_entered):
            config = MixerConfig(
                players_text=players_text,
                target_games_per_player=target_games_per_player,
                num_pits=num_pits
            )
            mixer_state = generate_schedule(config)
            st.session_state["mixer_state"] = mixer_state
            st.session_state['current_round_scores'] = {} # Clear current score inputs
            st.session_state["edit_mode_rounds"] = {} # Clear edit modes
            st.session_state["confirm_regenerate_pending"] = False
            st.sidebar.success("Schedule re-generated!")
            st.rerun()
    with col2_reg:
        if st.button("Cancel Re-Generate", key="cancel_regenerate_button", disabled=has_any_score_entered):
            st.session_state["confirm_regenerate_pending"] = False
            st.sidebar.info("Re-generation cancelled.")
            st.rerun()

# Reset button with confirmation
if "confirm_reset_pending" not in st.session_state:
    st.session_state["confirm_reset_pending"] = False

if st.sidebar.button("Reset Schedule and Scores", key="reset_button"):
    st.session_state["confirm_reset_pending"] = True

if st.session_state["confirm_reset_pending"]:
    st.sidebar.warning("Are you sure you want to reset ALL schedule and scores? This action cannot be undone.")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("Confirm Reset", key="confirm_reset_button_final"):
            if os.path.exists(STATE_FILE_PATH):
                os.remove(STATE_FILE_PATH)
                st.sidebar.info(f"Removed saved state file: {STATE_FILE_PATH}")
            st.session_state["mixer_state"] = None
            st.session_state['current_round_scores'] = {} # Clear any current score inputs
            st.session_state["edit_mode_rounds"] = {} # Also clear edit modes
            st.session_state["confirm_reset_pending"] = False # Reset confirmation state
            st.sidebar.success("Schedule and scores reset.")
            st.rerun()
    with col2:
        if st.button("Cancel Reset", key="cancel_reset_button_final"):
            st.session_state["confirm_reset_pending"] = False
            st.sidebar.info("Reset cancelled.")
            st.rerun() # Rerun to remove the confirmation buttons


# Display results
if st.session_state["mixer_state"]:
    mixer_state = st.session_state["mixer_state"]

    if mixer_state.error:
        st.error(f"Error: {mixer_state.error}")
    elif mixer_state.result:
        st.subheader("Generated Schedule")
        st.info(f"Minimum games played per player: {mixer_state.result.games_per_player}")
        st.info(f"Players with games > target: {mixer_state.result.num_players_with_extra_games}")

        st.markdown("### Player Statistics")
        # Prepare data for DataFrame with asterisk
        player_stats_display_data = []
        for player, stats in mixer_state.result.player_stats.items():
            # Asterisk in summary only if they exceeded the target, for clarity
            asterisk = '*' if stats['games'] > mixer_state.config.target_games_per_player else ''
            player_stats_display_data.append({
                'Player': f"{player}{asterisk}",
                'Games Played': stats['games'],
                'Byes': stats['byes']
            })
        player_stats_df = pd.DataFrame(player_stats_display_data).set_index('Player')
        st.dataframe(player_stats_df)

        st.markdown("### Player Opponent Matrix")
        opponent_df = get_opponent_matrix_dataframe(mixer_state)
        if not opponent_df.empty:
            st.dataframe(opponent_df)
        else:
            st.write("No opponent data to display.")

        st.markdown("### Player Partner Matrix")
        partner_df = get_partner_matrix_dataframe(mixer_state)
        if not partner_df.empty:
            st.dataframe(partner_df)
        else:
            st.write("No partner data to display.")

        st.markdown("### Round Details")
        for i, round_data in enumerate(mixer_state.result.rounds):
            bg_class = "round-odd" if (i + 1) % 2 != 0 else "round-even"
            st.markdown(f"<div class='{bg_class}'>", unsafe_allow_html=True)
            st.markdown(f"#### Round {round_data.round_number}:")

            # Check if this round is in edit mode
            is_round_in_edit_mode = st.session_state.get('edit_mode_rounds', {}).get(round_data.round_number, False)

            # Calculate score status for the current round
            current_round_has_missing_scores = False
            current_round_has_entered_scores = False
            if round_data.matches:
                for match in round_data.matches:
                    if match.score_team1 is None or match.score_team2 is None:
                        current_round_has_missing_scores = True
                    if match.score_team1 is not None or match.score_team2 is not None:
                        current_round_has_entered_scores = True

            with st.form(key=f"round_form_{round_data.round_number}"):
                if round_data.matches:
                    st.markdown("**Matches:**")
                    # Ensure current_round_scores is initialized for this rerun if it somehow got cleared
                    if 'current_round_scores' not in st.session_state:
                        st.session_state['current_round_scores'] = {}

                    for match_idx, match in enumerate(round_data.matches):
                        st.markdown(f"##### Pit {match.pit}:")

                        # Determine if this match's score 1 should be disabled
                        # It's disabled if NOT in edit mode AND score is already entered
                        score_t1_disabled = (not is_round_in_edit_mode and match.score_team1 is not None)

                        # Display Team 1 and its score input vertically
                        team1_p1_display = match.team1[0]
                        if (team1_p1_display in mixer_state.result.players_to_asterisk and
                                mixer_state.result.players_to_asterisk[team1_p1_display] == (round_data.round_number, match.pit)):
                            team1_p1_display += '*'

                        team1_p2_display = match.team1[1]
                        if (team1_p2_display in mixer_state.result.players_to_asterisk and
                                mixer_state.result.players_to_asterisk[team1_p2_display] == (round_data.round_number, match.pit)):
                            team1_p2_display += '*'

                        st.write(f"**Team 1:** {team1_p1_display}, {team1_p2_display}")
                        initial_score_t1 = str(match.score_team1) if match.score_team1 is not None else ""
                        score_t1_str = st.text_input(
                            "Score Team 1", # Label is now visible
                            value=initial_score_t1,
                            key=f"round_{round_data.round_number}_pit_{match.pit}_t1_score",
                            label_visibility="visible", # Ensure label is visible
                            max_chars=2,
                            disabled=score_t1_disabled # Disable if not in edit mode AND score is already entered
                        )
                        st.session_state['current_round_scores'][(round_data.round_number, match.pit, 'team1')] = score_t1_str

                        st.markdown("vs")

                        # Determine if this match's score 2 should be disabled
                        score_t2_disabled = (not is_round_in_edit_mode and match.score_team2 is not None)

                        # Display Team 2 and its score input vertically
                        team2_p1_display = match.team2[0]
                        if (team2_p1_display in mixer_state.result.players_to_asterisk and
                                mixer_state.result.players_to_asterisk[team2_p1_display] == (round_data.round_number, match.pit)):
                            team2_p1_display += '*'

                        team2_p2_display = match.team2[1]
                        if (team2_p2_display in mixer_state.result.players_to_asterisk and
                                mixer_state.result.players_to_asterisk[team2_p2_display] == (round_data.round_number, match.pit)):
                            team2_p2_display += '*'

                        st.write(f"**Team 2:** {team2_p1_display}, {team2_p2_display}")
                        initial_score_t2 = str(match.score_team2) if match.score_team2 is not None else ""
                        score_t2_str = st.text_input(
                            "Score Team 2", # Label is now visible
                            value=initial_score_t2,
                            key=f"round_{round_data.round_number}_pit_{match.pit}_t2_score",
                            label_visibility="visible", # Ensure label is visible
                            max_chars=2,
                            disabled=score_t2_disabled # Disable if not in edit mode AND score is already entered
                        )
                        st.session_state['current_round_scores'][(round_data.round_number, match.pit, 'team2')] = score_t2_str

                        st.markdown("--- ") # Separator after each match

                else:
                    st.write("No matches in this round.")

                if round_data.byes:
                    st.markdown("**Byes:**")
                    st.write(f"    {', '.join(round_data.byes)}")

                if not round_data.matches and not round_data.byes:
                    st.write("No activity in this round.")

                # The 'Save Scores' button should be enabled if in edit mode OR if there are any scores missing for initial entry
                save_button_disabled = not (is_round_in_edit_mode or current_round_has_missing_scores)
                submitted = st.form_submit_button(f"Save Scores for Round {round_data.round_number}", disabled=save_button_disabled)
                if submitted:
                    for match in round_data.matches: # Iterating over matches directly
                        score1_key = (round_data.round_number, match.pit, 'team1')
                        score2_key = (round_data.round_number, match.pit, 'team2')

                        score_t1_str = st.session_state['current_round_scores'].get(score1_key, "")
                        score_t2_str = st.session_state['current_round_scores'].get(score2_key, "")

                        try:
                            match.score_team1 = int(score_t1_str) if score_t1_str else None
                            match.score_team2 = int(score_t2_str) if score_t2_str else None
                        except ValueError:
                            st.warning(f"Invalid score entered for Round {round_data.round_number}, Pit {match.pit}. Scores must be numbers or left blank.")
                            match.score_team1 = None # Set to None if invalid to ensure state is clear
                            match.score_team2 = None
                            # Continue is fine here, as the loop proceeds to the next match, and we want to try to save valid scores for other matches.
                            continue

                    st.session_state['edit_mode_rounds'][round_data.round_number] = False # Exit edit mode
                    save_mixer_state_to_file(mixer_state) # Save state after scores are updated
                    st.success(f"Scores for Round {round_data.round_number} saved!")
                    st.rerun()

            # The 'Edit Scores' button should only be shown if not in edit mode AND some scores have been entered.
            if not is_round_in_edit_mode and current_round_has_entered_scores:
                if st.button(f"Edit Scores for Round {round_data.round_number}", key=f"edit_round_scores_btn_{round_data.round_number}"):
                    st.session_state['edit_mode_rounds'][round_data.round_number] = True
                    st.rerun()

            st.markdown("</div>", unsafe_allow_html=True)

        st.subheader("Export Options")
        st.download_button(
            label="Download Schedule as Text",
            data=format_schedule_to_text(mixer_state),
            file_name="schedule.txt",
            mime="text/plain"
        )

        schedule_df = format_schedule_to_dataframe(mixer_state)
        if not schedule_df.empty:
            csv = schedule_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Download Schedule as CSV",
                data=csv,
                file_name="schedule.csv",
                mime="text/csv",
            )
        else:
            st.warning("Cannot export to CSV: No valid schedule data.")

    else:
        st.write("Adjust configuration and click 'Generate Schedule'.")
else:
    st.write("Adjust configuration and click 'Generate Schedule' to see the schedule.")