import streamlit as st
import random
import math
import re
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Optional

# --- Data Structures ---

@dataclass
class Match:
    pit: int
    team1: List[str]
    team2: List[str]

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
    if b not in pair_map:
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

        score += pit_count.get(p1, {}).get(pit, 0)
        score += pit_count.get(p2, {}).get(pit, 0)
        score += pit_count.get(p3, {}).get(pit, 0)
        score += pit_count.get(p4, {}).get(pit, 0)

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
        # Determine who plays: prioritise players with fewest games relative to target,
        # shuffling within tied groups so the order is random each time.
        prioritized = shuffle(players)
        # Sort key: (games_played_diff_from_target, actual_games_played, random)
        # This ensures players furthest below target are prioritized, then by fewest actual games, then random for ties
        prioritized.sort(
            key=lambda p: (games_played[p] - target_games_per_player, games_played[p], random.random())
        )

        active = prioritized[:active_slots_per_round]
        byes = prioritized[active_slots_per_round:]

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
                pit_count[p][pit_num] = (pit_count[p].get(pit_num, 0) + 1)

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
    for p in players:
        player_final_stats[p] = {
            'games': games_played[p],
            'byes': byes_count[p]
        }
        if games_played[p] > target_games_per_player:
            num_extra_games_players += 1

    return MixerState(
        config=config,
        result=MixerResult(
            rounds=rounds,
            games_per_player=min_games_played,
            num_rounds=num_rounds,
            player_stats=player_final_stats,
            opponent_matrix=opponent_count,
            partner_matrix=partner_count,
            num_players_with_extra_games=num_extra_games_players # Storing the count
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
            output_lines.append(f"{player}: Games Played = {stats['games']}, Byes = {stats['byes']}")

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
                    output_lines.append(f"    Pit {match.pit}: {', '.join(match.team1)} vs {', '.join(match.team2)}")
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
            data.append({
                'Round': round_data.round_number,
                'Pit': match.pit,
                'Team1 Player1': match.team1[0],
                'Team1 Player2': match.team1[1],
                'Team2 Player1': match.team2[0],
                'Team2 Player2': match.team2[1],
                'Status': 'Playing'
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
                'Status': 'Bye'
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

# Input widgets
st.sidebar.header("Configuration")
players_text = st.sidebar.text_area(
    "Players (comma, newline, or space separated)",
    value=DEFAULT_PLAYERS,
    height=150
)

# Live player count in sidebar
current_players = [p.strip() for p in re.split(r'[\n,]+', players_text) if p.strip()]
st.sidebar.write(f"Total Players: **{len(current_players)}**")

num_pits = st.sidebar.slider(
    "Number of Pits",
    min_value=1, max_value=10, value=3, step=1
)
target_games_per_player = st.sidebar.slider(
    "Target Games per Player",
    min_value=1, max_value=50, value=6, step=1
)

# Generate schedule button
if st.sidebar.button("Generate Schedule"):
    config = MixerConfig(
        players_text=players_text,
        target_games_per_player=target_games_per_player,
        num_pits=num_pits
    )
    # arrangement_attempts is now defaulted to 5000 inside generate_schedule
    mixer_state = generate_schedule(config)
    st.session_state["mixer_state"] = mixer_state

# Display results
if "mixer_state" in st.session_state:
    mixer_state = st.session_state["mixer_state"]

    if mixer_state.error:
        st.error(f"Error: {mixer_state.error}")
    elif mixer_state.result:
        st.subheader("Generated Schedule")
        st.info(f"Minimum games played per player: {mixer_state.result.games_per_player}")
        st.info(f"Players with games > target: {mixer_state.result.num_players_with_extra_games}")

        st.markdown("### Player Statistics")
        player_stats_df = pd.DataFrame.from_dict(mixer_state.result.player_stats, orient='index')
        player_stats_df.index.name = 'Player'
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

            if round_data.matches:
                st.markdown("**Matches:**")
                for match in round_data.matches:
                    st.write(f"  Pit {match.pit}: {', '.join(match.team1)} vs {', '.join(match.team2)}")
            else:
                st.write("No matches in this round.")

            if round_data.byes:
                st.markdown("**Byes:**")
                st.write(f"{', '.join(round_data.byes)}")

            if not round_data.matches and not round_data.byes:
                st.write("No activity in this round.")
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