import io

import pandas as pd
import requests

from scraper_common import print_step

DATASET_URL = "https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset/resolve/main/text_style_control/latest-00000-of-00001.parquet"

def scrape():
    print_step("Downloading LMArena text leaderboard from HuggingFace...")
    resp = requests.get(DATASET_URL, timeout=60);
    resp.raise_for_status();
    df = pd.read_parquet(io.BytesIO(resp.content));
    df = df[df["category"] == "overall"].sort_values("rank");
    if df.empty:
        raise ValueError("LMArena overall leaderboard is empty")
    print_step(f"Leaderboard published {df['leaderboard_publish_date'].iloc[0]}, {len(df)} models");
    return pd.DataFrame({
        "Rank": df["rank"].astype(int).values,
        "Model": df["model_name"].values,
        "Score": df["rating"].round().astype(int).values,
        "Votes": df["vote_count"].astype(int).values,
        "Provider": df["organization"].values,
    })
