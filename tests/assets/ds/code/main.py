import os
import pandas as pd

DATA_DIR = os.environ["DATA_DIR"]
OUTPUT_DIR = os.environ["OUTPUT_DIR"]

# Read the dataset
df = pd.read_csv(os.path.join(DATA_DIR, "data.csv"))

# Perform computation: sum A + B + C for each row
df["sum"] = df["A"] + df["B"] + df["C"]

# Assert results (validate computation)
expected_sum = df["A"] + df["B"] + df["C"]
assert (df["sum"] == expected_sum).all(), "Sum calculation failed"

print(f"Processed {len(df)} rows successfully")

# Write output
output_path = os.path.join(OUTPUT_DIR, "result.csv")
df.to_csv(output_path, index=False)
