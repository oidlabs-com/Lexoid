import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

# Load the CSV file
df = pd.read_csv("tests/outputs/document_results.csv")

# Choose the metric to plot (change this to "Time (s)" or "Cost($)" if desired)
value_col = "sequence_matcher"

# Create pivot table for grouped bar plot
pivot_df = df.pivot(index="Input File", columns="model", values=value_col)

# Generate a colormap with enough distinct colors
color_list = custom_colors = [
    "#1f77b4",
    "#2ca02c",
    "#393b79",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
    "#637939",
    "#ff7f0e",
    "#7b4173",
    "#52a395",
    "#9c9ede",
    "#cedb9c",
    "#bd9e39",
    "#926867",
    "#e7969c",
    "#6b6ecf",
    "#b5cf6b",
    "#9cc8de",
    "#8c6d31",
]

if len(pivot_df.columns) > len(color_list):
    n_new_colors = len(pivot_df.columns) - len(color_list)
    new_colors = plt.cm.tab20c(np.linspace(0, 1, n_new_colors))
    color_list.extend(new_colors)

# Create the plot with custom colors
ax = pivot_df.plot(kind="bar", figsize=(12, 6), color=color_list)

# Customize plot
plt.title(f"{value_col} by Input File and Model")
plt.xlabel("Input File")
plt.ylabel(value_col)
plt.xticks(rotation=45, ha="right")

# Move legend above the plot
plt.legend(title="Model", loc="upper center", bbox_to_anchor=(0.5, 1.5), ncol=3)

# Save the figure
plt.savefig("tests/outputs/bar_plot.png", bbox_inches="tight", dpi=300)
