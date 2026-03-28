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
class MixerConfig:
    players_text: str
    target_games_per_player: int
    num_pits: int

@dataclass
class MixerResult:
    rounds: List[Round]
    games_per_player: int
    num_rounds: int

@dataclass
class MixerState:
    config: MixerConfig
    result: Optional[MixerResult] = None
    error: Optional[str] = None

# --- Helper Functions ---

DEFAULT_PLAYERS = "Ekim, dave, scott, derek, sean, erik, merri, doug, ryan"

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

def generate_schedule(config: MixerConfig) -> MixerState:
    players_text = config.players_text
    target_games_per_player = config.target_games_per_player
    num_pits = config.num_pits

    players = [p.strip() for p in re.split(r'[\n,]+', players_text)]
    players = [p for p in players if p] # Filter out empty strings

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
    partner_count: Dict[str, Dict[str, int]] = {}
    opponent_count: Dict[str, Dict[str, int]] = {}
    pit_count: Dict[str, Dict[int, int]] = {p: {} for p in players}

    rounds: List[Round] = []

    for r in range(num_rounds):
        prioritized = shuffle(players)
        prioritized.sort(key=lambda p: games_played[p])

        active = prioritized[:active_slots_per_round]
        byes = prioritized[active_slots_per_round:]

        best_arrangement = shuffle(active)
        best_score = score_arrangement(best_arrangement, partner_count, opponent_count, pit_count)

        for attempt in range(300):
            candidate = shuffle(active)
            s = score_arrangement(candidate, partner_count, opponent_count, pit_count)
            if s < best_score:
                best_score = s
                best_arrangement = candidate
                if s == 0:
                    break

        matches: List[Match] = []
        for i in range(0, len(best_arrangement), 4):
            if i + 3 >= len(best_arrangement):
                break
            p1, p2, p3, p4 = best_arrangement[i : i + 4]
            pit_num = (i // 4) + 1
            matches.append(
                Match(pit=pit_num, team1=[p1, p2], team2=[p3, p4])
            )

            inc(partner_count, p1, p2)
            inc(partner_count, p3, p4)
            inc(opponent_count, p1, p3)
            inc(opponent_count, p1, p4)
            inc(opponent_count, p2, p3)
            inc(opponent_count, p2, p4)

            for p in [p1, p2, p3, p4]:
                pit_count[p][pit_num] = pit_count[p].get(pit_num, 0) + 1

        for p in active:
            games_played[p] += 1

        rounds.append(
            Round(round_number=r + 1, matches=matches, byes=sorted(byes))
        )

    min_games_played = min(games_played.values()) if games_played else 0

    return MixerState(
        config=config,
        result=MixerResult(
            rounds=rounds,
            games_per_player=min_games_played,
            num_rounds=num_rounds,
        ),
        error=None,
    )

# --- Export Functions (NEW) ---

def format_schedule_to_text(mixer_state: MixerState) -> str:
    output_lines = []

    if mixer_state.error:
        output_lines.append(f"Error: {mixer_state.error}")
    elif mixer_state.result:
        num_players = len(mixer_state.config.players_text.split(',')) # Assuming players_text is comma-separated
        output_lines.append(f"Schedule generated successfully for {num_players} players over {mixer_state.result.num_rounds} rounds.")
        output_lines.append(f"Minimum games played per player: {mixer_state.result.games_per_player}")

        for round_data in mixer_state.result.rounds:
            output_lines.append(f"\nRound {round_data.round_number}:")
            for match in round_data.matches:
                output_lines.append(f"  Pit {match.pit}: {', '.join(match.team1)} vs {', '.join(match.team2)}")
            if round_data.byes:
                output_lines.append(f"  Byes: {', '.join(round_data.byes)}")
    else:
        output_lines.append("No result or error found.")

    return "\n".join(output_lines)

def format_schedule_to_dataframe(mixer_state: MixerState) -> pd.DataFrame:
    data = []

    if mixer_state.error:
        # print(f"Error in MixerState: {mixer_state.error}") # Avoid printing in Streamlit function
        return pd.DataFrame() # Return empty DataFrame on error

    if not mixer_state.result:
        # print("No MixerResult found in MixerState.") # Avoid printing in Streamlit function
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

# --- Streamlit App Layout ---
st.set_page_config(layout="wide", page_title="Scheduling Mixer App")
st.title("Scheduling Mixer")

# Input widgets
st.sidebar.header("Configuration")
players_text = st.sidebar.text_area(
    "Players (comma, newline, or space separated)",
    value=DEFAULT_PLAYERS = "Ekim, dave, scott, derek, sean, erik, merri, doug, ryan"
    height=150
)
num_pits = st.sidebar.slider(
    "Number of Pits",
    min_value=1, max_value=10, value=3, step=1
)
target_games_per_player = st.sidebar.slider(
    "Target Games per Player",
    min_value=1, max_value=50, value=6, step=1
)

# Generate schedule button (optional, can also run on input change)
if st.sidebar.button("Generate Schedule"): # Moved the button here to prevent auto-regeneration
    config = MixerConfig(
        players_text=players_text,
        target_games_per_player=target_games_per_player,
        num_pits=num_pits
    )
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

        # Display rounds using expanders
        for round_data in mixer_state.result.rounds:
            with st.expander(f"Round {round_data.round_number}"):
                if round_data.matches:
                    st.markdown("**Matches:**")
                    for match in round_data.matches:
                        st.write(f"Pit {match.pit}: {', '.join(match.team1)} vs {', '.join(match.team2)}")
                else:
                    st.write("No matches in this round.")

                if round_data.byes:
                    st.markdown("**Byes:**")
                    st.write(f"{', '.join(round_data.byes)}")

                if not round_data.matches and not round_data.byes:
                    st.write("No activity in this round.")

        st.subheader("Export Options")
        # Text Export
        st.download_button(
            label="Download Schedule as Text",
            data=format_schedule_to_text(mixer_state),
            file_name="schedule.txt",
            mime="text/plain"
        )

        # CSV Export
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