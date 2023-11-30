import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter, AutoMinorLocator, MultipleLocator
from common import fatal
from trace import Bench

MEAN = "mean"
ERROR = "error"
THERMAL = "thermal"
POWER = "power"


def init_matplotlib(args):
    try:
        matplotlib.use(args.engine)
    except ValueError:
        fatal(f"Cannot load matplotlib backend engine {args.engine}")


GRAPH_TYPES = ["perf", "perf_watt", "watts"]


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
        self.ax2 = None
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
        else:
            # Bar graphs do not need legend, let the caller disable it
            if legend:
                plt.legend()

        if x_major_locator:
            self.ax.set_xlim(None, xmin=0, emit=True)
            self.ax.xaxis.set_major_locator(
                MultipleLocator(x_major_locator),
            )

        if x_minor_locator:
            self.ax.xaxis.set_minor_locator(
                MultipleLocator(x_minor_locator),
            )

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
        self.ax.xaxis.set_minor_locator(AutoMinorLocator())
        plt.minorticks_on()

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
    component_name: str,
    item_title: str,
    second_axis=None,
) -> int:
    outfile = f"{component_name}"
    trace = bench.get_trace()

    if component_name == "temp":
        components = bench.get_components_by_unit("celsius")
    else:
        components = bench.get_components(component_name)
    if not components:
        print(f"{bench.get_bench_name()}: no {component_name}")
        return 0

    thermal_components = bench.get_components_by_unit("celsius")
    samples_count = bench.get_samples_count(components[0])

    title = (
        f'{item_title} during "{bench.get_bench_name()}" benchmark job\n'
        f"\n Stressor: "
    )
    title += f"{bench.workers()} x {bench.get_title_engine_name()} for {bench.duration()} seconds"
    title += f"\n{bench.get_system_title()}"
    graph = Graph(
        args,
        title,
        "Time [seconds]",
        bench.get_monitoring_metric_unit(components[0]),
        output_dir.joinpath(
            f"{trace.get_name()}/{bench.get_bench_name()}/{component_name}"
        ),
        outfile,
        show_source_file=trace,
    )

    if second_axis:
        outfile += f"_vs_{second_axis}"
        graph.set_filename(outfile)
        if second_axis == THERMAL:
            graph.set_y2_axis("Thermal (°C)", 110)
        elif second_axis == POWER:
            graph.set_y2_axis("Power (Watts)")
            power_metrics = ["chassis"]
            for additional_metric in ["enclosure", "infrastructure"]:
                if additional_metric in bench.get_monitoring():
                    power_metrics.append(additional_metric)

    if args.verbose:
        print(
            f"{trace.get_name()}/{bench.get_bench_name()}: {len(components)} {component_name} to graph with {samples_count} samples"
        )

    time_interval = 10  # Hardcoded for now in benchmark.py
    time_serie = []
    data_serie = {}  # type: dict[str, list]
    data2_serie = {}  # type: dict[str, list]
    for sample in range(0, samples_count):
        time = sample * time_interval
        time_serie.append(time)
        # Collect all components mean value
        for component in components:
            if component not in data_serie:
                data_serie[component] = []
            data_serie[component].append(bench.get_mean_events(component)[sample])

        if second_axis:
            if second_axis == THERMAL:
                for thermal_component in thermal_components:
                    if thermal_component not in data2_serie:
                        data2_serie[thermal_component] = []
                    data2_serie[thermal_component].append(
                        bench.get_mean_events(thermal_component)[sample]
                    )
            elif second_axis == POWER:
                for power_metric in power_metrics:
                    if power_metric not in data2_serie:
                        data2_serie[power_metric] = []
                    data2_serie[power_metric].append(
                        bench.get_mean_events(power_metric)[sample]
                    )

    order = np.argsort(time_serie)
    x_serie = np.array(time_serie)[order]

    if second_axis:
        for data2_item in data2_serie:
            y2_serie = np.array(data2_serie[data2_item])[order]
            graph.get_ax2().plot(x_serie, y2_serie, "", label=data2_item, marker="o")

    for component in components:
        y_serie = np.array(data_serie[component])[order]
        graph.get_ax().plot(x_serie, y_serie, "", label=component)

    graph.prepare_axes(30, 15, (bench.get_monitoring_metric_axis(components[0])))

    graph.render()
    return 1


def yerr_graph(args, output_dir, bench: Bench, component_type: str, component: str):
    trace = bench.get_trace()
    samples_count = bench.get_samples_count(component)
    time_interval = 10

    time_serie = []
    data_serie = {}  # type: dict[str, list]
    data_serie[MEAN] = []
    data_serie[ERROR] = []
    for sample in range(0, samples_count):
        time = sample * time_interval
        time_serie.append(time)
        mean_value = bench.get_mean_events(component)[sample]
        data_serie[ERROR].append(
            (
                mean_value - bench.get_min_events(component)[sample],
                bench.get_max_events(component)[sample] - mean_value,
            )
        )
        data_serie[MEAN].append(mean_value)

    title = (
        f'{component} during "{bench.get_bench_name()}" benchmark job\n'
        f"\n Stressor: "
    )
    title += f"{bench.workers()} x {bench.get_title_engine_name()} for {bench.duration()} seconds"
    title += f"\n{bench.get_system_title()}"

    graph = Graph(
        args,
        title,
        "Time [seconds]",
        bench.get_monitoring_metric_unit(component),
        output_dir.joinpath(
            f"{trace.get_name()}/{bench.get_bench_name()}/{component_type}"
        ),
        component,
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
        label=component,
    )
    graph.prepare_axes(30, 15, bench.get_monitoring_metric_axis(component))
    graph.render()
    return 1
