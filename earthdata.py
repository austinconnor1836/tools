import xarray as xr
import os
import numpy as np
import matplotlib.pyplot as plt

# Directory where granules are stored
granule_dir = "./input/NLDAS_FORA0125_H_2.0-20250118_233753"

# Variable to focus on
VARIABLE = "PSurf"  # Correct variable name for surface pressure
LATITUDE_GB = slice(35, 42)  # Great Basin latitudes
LONGITUDE_GB = slice(-120, -115)  # Great Basin longitudes
LATITUDE_SC = slice(32, 35)  # Southern California latitudes
LONGITUDE_SC = slice(-120, -117)  # Southern California longitudes

# Load all granules
def load_granules(granule_dir, variable):
    """Load all granules and extract the specified variable."""
    all_files = [os.path.join(granule_dir, f) for f in os.listdir(granule_dir) if f.endswith(".nc")]
    dataset = xr.open_mfdataset(all_files, combine="by_coords")  # Efficiently load multiple files
    return dataset[variable]

# Load surface pressure data
print("Loading data...")
surface_pressure = load_granules(granule_dir, VARIABLE)

# Subset data for Great Basin and Southern California
print("Subsetting data...")
great_basin = surface_pressure.sel(lat=LATITUDE_GB, lon=LONGITUDE_GB)
southern_california = surface_pressure.sel(lat=LATITUDE_SC, lon=LONGITUDE_SC)

# Calculate mean surface pressure for each region
print("Calculating regional means...")
gb_mean = great_basin.mean(dim=["lat", "lon"])
sc_mean = southern_california.mean(dim=["lat", "lon"])

# Calculate pressure difference and gradient
print("Calculating pressure gradients...")
pressure_diff = gb_mean - sc_mean
distance = 500 * 1000  # Approximate distance in meters between the regions
pressure_gradient = pressure_diff / distance

# Check the sign of the pressure gradient
print(pressure_gradient)  # Print all pressure gradient values

# Find peak positive and negative pressure gradients
peak_positive_gradient = pressure_gradient.max()
peak_negative_gradient = pressure_gradient.min()

print(f"Peak Positive Gradient: {peak_positive_gradient.values} Pa/m")
print(f"Peak Negative Gradient: {peak_negative_gradient.values} Pa/m")

# Plot the pressure gradient with labels
print("Plotting results...")
plt.figure(figsize=(10, 6))
pressure_gradient.plot(label="Pressure Gradient (Pa/m)", color="blue")
plt.axhline(0, color="red", linestyle="--", label="Zero Gradient")
plt.title("Pressure Gradient Between Great Basin and Southern California")
plt.xlabel("Time")
plt.ylabel("Pressure Gradient (Pa/m)")
plt.legend()
plt.grid()
plt.show()
