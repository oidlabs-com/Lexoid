import pandas as pd
import matplotlib.pyplot as plt

# Load the CSV file
df = pd.read_csv("outputs/document_results.csv")

# Choose the metric to plot (change this to "Time (s)" or "Cost($)" if desired)
value_col = "sequence_matcher"

# Create pivot table for grouped bar plot
pivot_df = df.pivot(index="Input File", columns="model", values=value_col)

# Set up the bar plot
ax = pivot_df.plot(kind="bar", figsize=(12, 6))

# Customize plot
plt.title(f"{value_col} by Input File and Model")
plt.xlabel("Input File")
plt.ylabel(value_col)
plt.xticks(rotation=45, ha="right")

# Move legend to be above the plot
plt.legend(title="Model", loc="upper center", bbox_to_anchor=(0.5, 1.5), ncol=3)
# plt.tight_layout()
plt.savefig("outputs/bar_plot.png", bbox_inches="tight", dpi=300)
