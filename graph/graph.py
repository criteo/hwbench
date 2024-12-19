from typing import Optional
import matplotlib
from matplotlib.pylab import Axes
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter, AutoMinorLocator, MultipleLocator
from graph.common import fatal
from graph.trace import Bench
from hwbench.bench.monitoring_structs import Metrics, MonitorMetric

MEAN = "mean"
ERROR = "error"


def init_matplotlib(args):
    try:
        matplotlib.use(args.engine)
    except ValueError:
        fatal(f"Cannot load matplotlib backend engine {args.engine}")


GRAPH_TYPES = ["perf", "perf_watt", "watts", "cpu_clock"]


class Graph:
    def __init__(
        self,
        args,
        title: str,
        xlabel: str,
        ylabel: str,
        output_dir,
        filename,
        square=False,
        show_source_file=None,
    ) -> None:
        self.ax2: Optional[Axes] = None
        self.args = args
        self.fig, self.ax = plt.subplots()
        self.dpi = 100
        if square:
            self.fig.set_size_inches(args.width / self.dpi, args.width / self.dpi)
            self.ax.set_box_aspect(1)
        else:
            self.fig.set_size_inches(args.width / self.dpi, args.height / self.dpi)
        self.set_labels(xlabel, ylabel)
        self.set_xticks_style()
        self.set_title(title, show_source_file)
        self.output_dir = output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        self.set_filename(filename)

    def __del__(self):
        """Destruction will close all plots"""
        self.fig.clear()
        plt.close(self.fig)

    def set_filename(self, filename: str):
        self.filename = filename

    def set_labels(self, xlabel: str, ylabel: str):
        """Set the x & y labels"""
        self.ax.set_xlabel(xlabel)
        self.ax.set_ylabel(ylabel)

    def set_xticks_style(self):
        """Set the xtick style."""
        self.ax.tick_params(
            axis="x",
            which="minor",
            direction="out",
            colors="silver",
            grid_color="silver",
            grid_alpha=0.5,
            grid_linestyle="dotted",
        )

    def set_y2_axis(self, label: str, y2_max=None):
        """Add a second y axis"""
        ax2 = self.ax.twinx()  # instantiate a second axes that shares the same x-axis
        ax2.tick_params(axis="y")
        ax2.set_ylabel(label)
        self.ax2 = ax2
        self.y2_max = y2_max

    def prepare_axes(
        self,
        x_major_locator=0,
        x_minor_locator=0,
        y_locators=(None, None, None),
        legend=True,
        points_to_plot=0,
        interval=0,
    ):
        """Set the ticks and axes limits."""
        # This should be called _after_ the ax.*plot calls
        ymax, y_major, y_minor = y_locators

        if y_major:
            self.ax.yaxis.set_major_locator(
                MultipleLocator(y_major),
            )

        if y_minor:
            self.ax.yaxis.set_minor_locator(
                MultipleLocator(y_minor),
            )

        self.ax.set_ylim(None, ymin=0, ymax=ymax, emit=True, auto=True)
        # If we have a 2nd axis, let's prepare it
        if self.ax2:
            # Legend y1 at top left
            self.ax.legend(loc=2)
            # Legend y2 at top right
            self.ax2.legend(loc=1)
            self.ax2.set_ylim(None, ymin=0, ymax=self.y2_max, emit=True, auto=True)
            self.ax2.yaxis.set_major_formatter(FuncFormatter(self.human_format))
            self.fig.tight_layout()  # otherwise the right y-label is slightly clipped
            self.ax2.yaxis.set_major_locator(matplotlib.ticker.LinearLocator(len(self.ax.get_yticks()) - 2))
        else:
            # Bar graphs do not need legend, let the caller disable it
            if legend:
                plt.legend()

        # If we have less than 15 points to render, let's use the real time interval
        if points_to_plot and points_to_plot < 30:
            x_major_locator = interval
            x_minor_locator = interval / 2

        if x_major_locator:
            self.ax.set_xlim(None, xmin=0, emit=True)
            self.ax.xaxis.set_major_locator(
                MultipleLocator(x_major_locator),
            )

        if x_minor_locator:
            self.ax.xaxis.set_minor_locator(
                MultipleLocator(x_minor_locator),
            )
        else:
            self.ax.xaxis.set_minor_locator(AutoMinorLocator())

        self.ax.yaxis.set_major_formatter(FuncFormatter(self.human_format))
        self.prepare_grid()

    def human_format(self, num, pos=None):
        """Return format in human readable units."""
        # This function is compatible with FuncFormatter and fmt
        unit = ""
        if num > 1e9:
            num *= 1e-9
            unit = "G"
        elif num > 1e6:
            num *= 1e-6
            unit = "M"
        elif num > 1e3:
            num *= 1e-3
            unit = "K"
        return f"{num:.2f}{unit}"

    def prepare_grid(self):
        self.ax.grid(which="major", linewidth=1)
        self.ax.grid(which="minor", linewidth=0.2, linestyle="dashed")

    def set_title(self, title, show_source_file=None):
        """Set the graph title"""
        self.ax.set_title(title)
        if show_source_file:
            # place a text box in upper left in axes coords
            props = dict(boxstyle="round", facecolor="white", alpha=0.5)
            self.ax.text(
                0,
                -0.1,
                f"data plotted from {show_source_file.get_filename()}",
                transform=self.ax.transAxes,
                fontsize=14,
                verticalalignment="top",
                bbox=props,
            )

    def get_ax(self):
        """Return the ax object."""
        return self.ax

    def get_ax2(self):
        """Return the ax2 object (for the 2nd y axis)."""
        return self.ax2

    def render(self):
        """Render the graph to a file."""
        # Retrieve the rendering file format
        file_format = self.args.format
        plt.savefig(
            f"{self.output_dir}/{self.filename}.{file_format}",
            format=file_format,
            dpi=self.args.dpi,
        )
        self.fig.clear()
        plt.close(self.fig)


def generic_graph(
    args,
    output_dir,
    bench: Bench,
    component_type: Metrics,
    item_title: str,
    second_axis=None,
    filter=None,
) -> int:
    outfile = f"{item_title}"
    trace = bench.get_trace()

    components = bench.get_all_metrics(component_type, filter)
    if not len(components):
        title = f"{item_title}: no {str(component_type)} metric found"
        if filter:
            title += f" with filter = '{filter}'"
        return 0

    samples_count = bench.get_samples_count()
    unit = bench.get_metric_unit(component_type)
    title = f'{item_title} during "{bench.get_bench_name()}" benchmark job\n' f"{args.title}\n" f"\n Stressor: "
    title += f"{bench.workers()} x {bench.get_title_engine_name()} for {bench.duration()} seconds"
    title += f"\n{bench.get_system_title()}"
    graph = Graph(
        args,
        title,
        "Time [seconds]",
        unit,
        output_dir.joinpath(f"{trace.get_name()}/{bench.get_bench_name()}/{str(component_type)}"),
        outfile,
        show_source_file=trace,
    )

    if second_axis:
        outfile += f"_vs_{second_axis}"
        graph.set_filename(outfile)
        if second_axis == Metrics.THERMAL:
            graph.set_y2_axis("Thermal (°C)", 110)
        elif second_axis == Metrics.POWER_CONSUMPTION:
            graph.set_y2_axis("Power (Watts)")

    if args.verbose:
        print(
            f"{trace.get_name()}/{bench.get_bench_name()}: {len(components)} {str(component_type)} to graph with {samples_count} samples"
        )

    time_serie = []
    data_serie = {}  # type: dict[str, list]
    data2_serie = {}  # type: dict[str, list]
    for sample in range(0, samples_count):
        time = sample * bench.get_time_interval()
        time_serie.append(time)
        # Collect all components mean value
        for component in components:
            if component.get_full_name() not in data_serie:
                data_serie[component.get_full_name()] = []
            # If we are missing some datapoints ....
            if len(component.get_mean()) <= sample:
                # If the user didn't explictely agreed to be replaced by 0, let's be fatal
                if not args.ignore_missing_datapoint:
                    fatal(
                        f"{trace.get_name()}/{bench.get_bench_name()}: {component.get_full_name()} is missing the {sample+1}th data point.\
 Use --ignore-missing-datapoint to ignore this case. Generated graphs will be partially incorrect."
                    )
                else:
                    # User is fine with a missing data to be replaced.
                    # Let's do that so we can render things properly.

                    # Let's pick the last known value
                    if args.ignore_missing_datapoint == "last":
                        data_serie[component.get_full_name()].append(component.get_mean()[-1])
                    else:
                        # Replace it by a zero
                        data_serie[component.get_full_name()].append(0)
            else:
                data_serie[component.get_full_name()].append(component.get_mean()[sample])

        if second_axis:
            for _, entry in bench.get_monitoring_metric(second_axis).items():
                for sensor, measure in entry.items():
                    # We don't plot the Cores here
                    # We don't plot sensor on y2 if already plot on y1
                    if sensor in data_serie or sensor.startswith("Core"):
                        continue
                    if sensor not in data2_serie:
                        data2_serie[sensor] = []
                    if len(measure.get_mean()) <= sample:
                        # If the user didn't explictely agreed to be replaced by 0, let's be fatal
                        if not args.ignore_missing_datapoint:
                            fatal(
                                f"{trace.get_name()}/{bench.get_bench_name()}: second axis of {sensor}: {measure.get_full_name()} is missing the {sample+1}th data point.\
         Use --ignore-missing-datapoint to ignore this case. Generated graphs will be partially incorrect."
                            )
                        else:
                            # User is fine with a missing data to be replaced.
                            # Let's do that so we can render things properly.
                            if args.ignore_missing_datapoint == "last":
                                # Let's pick the last known value
                                data2_serie[sensor].append(measure.get_mean()[-1])
                            else:
                                # Replace it by a zero
                                data2_serie[sensor].append(0)
                    else:  # the actual data
                        data2_serie[sensor].append(measure.get_mean()[sample])
            # If we are plotting the power consumption, having the PSUs would be useful to compare with.
            if second_axis == Metrics.POWER_CONSUMPTION:
                psus = bench.get_psu_power()
                if psus:
                    if str(Metrics.POWER_SUPPLIES) not in data2_serie:
                        data2_serie[str(Metrics.POWER_SUPPLIES)] = []
                    data2_serie[str(Metrics.POWER_SUPPLIES)].append(psus[sample])

    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]

    if second_axis:
        for data2_item in data2_serie:
            y2_serie = np.array(data2_serie[data2_item])[order]
            graph.get_ax2().plot(x_serie, y2_serie, "", label=data2_item, marker="o")

    for component in components:
        y_serie = np.array(data_serie[component.get_full_name()])[order]
        graph.get_ax().plot(x_serie, y_serie, "", label=component.get_full_name())

    graph.prepare_axes(
        30,
        15,
        (bench.get_monitoring_metric_axis(unit)),
        points_to_plot=len(data_serie[next(iter(data_serie))]),
        interval=bench.get_time_interval(),
    )

    graph.render()
    return 1


def yerr_graph(
    args,
    output_dir,
    bench: Bench,
    component_type: Metrics,
    component: MonitorMetric,
    prefix="",
):
    trace = bench.get_trace()
    samples_count = bench.get_samples_count()
    unit = bench.get_metric_unit(component_type)

    time_serie = []
    data_serie = {}  # type: dict[str, list]
    data_serie[MEAN] = []
    data_serie[ERROR] = []
    for sample in range(0, samples_count):
        time = sample * bench.get_time_interval()
        time_serie.append(time)
        mean_value = component.get_mean()[sample]
        data_serie[ERROR].append(
            (
                mean_value - component.get_min()[sample],
                component.get_max()[sample] - mean_value,
            )
        )
        data_serie[MEAN].append(mean_value)

    title = f'{prefix}{component.get_name()} during "{bench.get_bench_name()}" benchmark job\n' f"\n Stressor: "
    title += f"{bench.workers()} x {bench.get_title_engine_name()} for {bench.duration()} seconds"
    title += f"\n{bench.get_system_title()}"

    graph = Graph(
        args,
        title,
        "Time [seconds]",
        unit,
        output_dir.joinpath(f"{trace.get_name()}/{bench.get_bench_name()}/{str(component_type)}"),
        f"{prefix}{component.get_name()}",
        show_source_file=trace,
    )

    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]
    y_serie = np.array(data_serie[MEAN])[order]
    yerror_serie = np.array(data_serie[ERROR]).T
    graph.get_ax().errorbar(
        x_serie,
        y_serie,
        yerr=yerror_serie,
        fmt="-b",
        ecolor="r",
        capsize=4,
        label=component.get_name(),
    )
    graph.prepare_axes(
        30,
        15,
        bench.get_monitoring_metric_axis(unit),
        points_to_plot=len(data_serie[next(iter(data_serie))]),
        interval=bench.get_time_interval(),
    )
    graph.render()
    return 1
