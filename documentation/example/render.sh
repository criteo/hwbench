#!/bin/bash
# Renders the reference dataset with hwgraph and copies the graphs used by the
# documentation into documentation/img/. Run it from the root of the repository:
#   make doc_images        (or: bash documentation/example/render.sh)
set -euo pipefail

traces=documentation/example/traces
img=documentation/img
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
mkdir -p "$img"

# Two configurations of the same server: environment, scaling and comparison graphs.
uv run hwgraph graph --format png \
    --traces "$traces/baseline.json:baseline:BMC.Server" "$traces/hpc.json:hpc:BMC.Server" \
    --outdir "$out/compare"
# Another server, with the NUMA topology: NUMA graphs.
uv run hwgraph graph --format png \
    --traces "$traces/numa.json:numa:BMC.Server" \
    --outdir "$out/numa"

# A cooling distribution unit (CDU) reboot of 100 seconds, started 80 seconds after the
# beginning of the benchmark: --events.
uv run hwgraph graph --format png \
    --traces "$traces/cdu_reboot.json:cdu_reboot:BMC.Server" \
    --events cdu_reboot:80:100 \
    --outdir "$out/cdu"

# Four servers of a same group (same time, same benchmark): --same-group.
uv run hwgraph graph --format png --same-group --no-env --no-scaling --no-versus \
    --events cdu_reboot:80:100 \
    --traces "$traces/cdu_reboot.json:server-1:BMC.Server" "$traces/cdu_reboot_2.json:server-2:BMC.Server" \
             "$traces/cdu_reboot_3.json:server-3:BMC.Server" "$traces/cdu_reboot_4.json:server-4:BMC.Server" \
    --outdir "$out/group"

# Recorded host monitoring with synthetic CDU readings, demonstrating the common time grid.
uv run hwgraph graph --format png --no-scaling --no-versus \
    --traces "$traces/cdu_comparison.json:cooling:BMC.Server" \
    --outdir "$out/cooling"

# A rack of ten servers built from cdu_comparison.json by rack.py, with a 2U chassis of 4 nodes, a 2U
# server and servers with GPUs: the rack view of --auto-group.
uv run python documentation/example/rack.py "$out/rack-traces"
rack_traces=()
for trace in "$out"/rack-traces/*.json; do
    rack_traces+=("$trace::BMC.Server")
done
uv run hwgraph graph --format png --auto-group --no-env --no-scaling --no-versus \
    --traces "${rack_traces[@]}" \
    --outdir "$out/rack"

# <directory>/<graph in the output tree> -> <image of the documentation>
copy() {
    cp "$out/$1" "$img/$2.png"
}

host=numa/environment/by_host/numa
copy "$host/NUMA distances.png"                                            hwgraph-env-numa-distances
copy "$host/cpu_17/Thermal/Thermal.png"                                    hwgraph-env-thermal
copy "$host/cpu_17/Fans/Fans speed_vs_Thermal.png"                         hwgraph-env-fans-vs-thermal
copy "$host/cpu_17/PowerConsumption/Package power consumption_vs_Thermal.png" hwgraph-env-package-power-vs-thermal
copy "$host/cpu_17/Freq/all_cores/Core frequency.png"                      hwgraph-env-freq-all-cores
copy "$host/cpu_17/Freq/pinned_cores/Core frequency.png"                   hwgraph-env-freq-pinned-cores
copy "$host/cpu_17/Freq/all_cores/Core frequency - distribution.png"       hwgraph-env-freq-distribution
copy "$host/cpu_17/Freq/all_numa/Core frequency per NUMA domain.png"       hwgraph-env-freq-numa
copy "$host/cpu_17/Freq/all_numa/Core frequency per NUMA domain - heatmap.png" hwgraph-env-freq-numa-heatmap

scaling=compare/scaling
copy "$scaling/perf/scaling_bogoopss_stressng_cpu_float128_.png"           hwgraph-scaling-perf
copy "$scaling/perf_watt/scaling_watt_bogoopss_stressng_cpu_float128_.png" hwgraph-scaling-perf-watt
copy "$scaling/watts/scaling_watt_bogoopss_stressng_cpu_float128_.png"     hwgraph-scaling-watts
copy "$scaling/cpu_clock/all_cores/scaling_cpu_clock_bogoopss_stressng_cpu_float128_.png" hwgraph-scaling-cpu-clock
copy "$scaling/cpu_clock/all_cores/scaling_cpu_clock_distribution_baseline_stressng_cpu_float128_.png" hwgraph-scaling-cpu-clock-distribution
copy "$scaling/perf/linearity_deviation/scaling_linearity_deviation_bogoopss_baseline_stressng_cpu_float128_.png" hwgraph-scaling-linearity-deviation
copy "numa/scaling/cpu_clock/all_numa/scaling_cpu_clock_numa_ridgeline_numa_stressng_cpu_int128_.png" hwgraph-scaling-numa-ridgeline

versus=compare/max_versus
copy "$versus/perf/float128/max_perf_total_stressng_cpu_float128_perf_bogoopss.png"           hwgraph-versus-perf
copy "$versus/perf_watt/float128/max_perf_total_stressng_cpu_float128_perf_watt_bogoopss.png" hwgraph-versus-perf-watt
copy "$versus/performance_summary_scorecard.png"                                              hwgraph-versus-scorecard

cdu=cdu/environment/by_host/cdu_reboot/full_cpu_load_0
copy "$cdu/PowerConsumption/Package power consumption_vs_Thermal.png" hwgraph-events-package-power-vs-thermal
copy "$cdu/Fans/Fans speed_vs_Thermal.png"                            hwgraph-events-fans-vs-thermal

group=group/by_group
copy "$group/time_watt_full_cpu_load_0 320xstressng_cpu_matrixprod_by_servers.png"         hwgraph-group-by-servers
copy "$group/time_watt_full_cpu_load_0 320xstressng_cpu_matrixprod_by_group.png"           hwgraph-group-by-group
copy "$group/time_watt_percent_full_cpu_load_0 320xstressng_cpu_matrixprod_by_group.png"   hwgraph-group-percent

copy "cooling/environment/by_host/cooling/cpu_17/CDU/0-CDU_example/CDU and host temperatures_vs_PowerConsumption.png" hwgraph-env-cdu-comparison

rack=rack/by_group/Country_FR/Datacenter_PA99/Datahall_2/Room_1/Rack_A12
copy "$rack/rack_elevation_cpu_17_Rack_A12.png"        hwgraph-rack-elevation
copy "$rack/rack_elevation_trends_cpu_17_Rack_A12.png" hwgraph-rack-elevation-trends
copy "$rack/rack_profile_cpu_17_Rack_A12.png"          hwgraph-rack-profile
copy "$rack/rack_profile_GPU_cpu_17_Rack_A12.png"      hwgraph-rack-profile-gpu
