#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import copy
import ctypes
import io
import itertools
import multiprocessing
import os
import pathlib
import pickle
import re
import shlex
import signal
import sys
import tarfile
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed

from graph.graph import InvalidValue
from hwbench.bench.monitoring_structs import (
    CORE_FAMILY,
    FansContextKeys,
    MonitorContextKeys,
    MonitoringContextKeys,
    PowerConsumptionContextKeys,
)
from hwbench.environment import ashrae

try:
    from graph.auto_group import (
        GROUP_DIRECTORY,
        LocationGroup,
        group_benches,
        group_problem,
        liquid_cooled,
        location_groups,
    )
    from graph.auto_traces import AUTO_TRACES_FILE, find_auto_traces, print_contexts
    from graph.cdu import graph_cdu
    from graph.chassis import graph_chassis
    from graph.common import DEFAULT_JOBS, fatal, progress
    from graph.graph import (
        TIMEOUTS,
        component_distribution_graph,
        generic_graph,
        init_matplotlib,
        numa_aggregated_components,
        numa_distance_heatmap,
        numa_distribution_graph,
        numa_performance_heatmap,
        timeouts_graph,
        write_benchmarks_summary,
        yerr_graph,
    )
    from graph.group import graph_group_env
    from graph.rack import graph_rack, graph_racks, rack_positions
    from graph.render_log import RenderLog
    from graph.scaling import performance_scaling_graph
    from graph.trace import (
        CPU_SCALING_UNIT,
        GPU_SCALING_UNIT,
        Event,
        ScalingUnit,
        Trace,
        config_differences,
        context_line,
        convert_trace,
        location_header_line,
        shared_cdu_lines,
        shared_location_line,
    )
    from graph.trace_cache import CACHE_DIRECTORY, remove_cache
    from graph.versus import (
        max_versus_graph,
        render_versus_scorecard,
        write_scaling_comparison,
        write_scaling_step_comparisons,
    )
    from hwbench.bench.monitoring_structs import (
        PowerCategories,
    )
except ImportError as exc:
    print(exc)
    print(
        'Could not start hwgraph: did you make sure to also install the "graph" optional dependencies using `uv sync --extra graph` or `pip install hwbench[graph]`?'
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Multiprocessing infrastructure
# ---------------------------------------------------------------------------

# Module-level global used by worker processes to access shared data
_pool_args = None


# prctl() option of Linux sending a signal to a process when its parent dies
PR_SET_PDEATHSIG = 1
# The workers are the children of the main process, as die_with_parent() expects. Not forkserver, the
# default since Python 3.14: its workers are the children of the fork server, which waits for them to exit.
WORKERS_START_METHOD = "spawn"


def die_with_parent(parent: int) -> None:
    """Ask the kernel to kill this worker when the main process dies, killed for lack of memory or stopping
    on an error: an orphan worker keeps waiting for a task forever, holding its memory."""
    try:
        ctypes.CDLL(None, use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGKILL)
    except (OSError, AttributeError):
        # Not Linux: the workers end with the pool only
        return
    # The main process died before the request was made
    if os.getppid() != parent:
        os._exit(1)


def _init_pool_worker(args_data, parent: int):
    """Initialize a worker process with shared data and matplotlib backend."""
    global _pool_args
    die_with_parent(parent)
    _pool_args = pickle.loads(args_data)
    init_matplotlib(_pool_args)


def _execute_pool_task(task) -> tuple[int, str, str | None]:
    """Execute a single graph generation task in a worker process: the number of graphs it rendered, what
    it printed, kept in the log of the rendering instead of mixed with the progress bar, and why the
    rendering must stop, None when it goes on."""
    func, *func_args = task
    output = io.StringIO()
    rendered = 0
    abort = None
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            rendered = func(*func_args)
    except KeyboardInterrupt:
        raise
    except SystemExit:
        # A fatal() of a graph, its reason already printed: it stops its task, not the rendering
        pass
    except OSError as e:
        # A graph that cannot be written, the disk being full for instance: the next ones would not be
        # either. Sent as text, as an exception of cairo cannot be sent back to the main process.
        abort = f"{type(e).__name__}: {e}"
        output.write(f"Error generating graph: {abort}\n{traceback.format_exc()}")
    except Exception as e:
        output.write(f"Error generating graph: {e}\n{traceback.format_exc()}")
    finally:
        # The traces of a task are read again by the next one using them: a worker keeping the ones of
        # all its tasks would end up holding all of them
        for trace in _pool_args.traces if _pool_args else []:
            trace.forget_content()
    return rendered, output.getvalue(), abort


def describe_task(args, task) -> tuple[str, str]:
    """The job of a task, empty for the tasks of all the jobs, and the graphs it renders, for its log."""
    func, *func_args = task
    if func is _task_env_bench:
        return func_args[1], f"environment of {args.traces[func_args[0]].get_name()}"
    if func is _task_numa_distance:
        return "", f"NUMA distances of {args.traces[func_args[0]].get_name()}"
    if func in (_task_group, _task_rack, _task_racks):
        kind = {_task_group: "group", _task_rack: "rack", _task_racks: "racks"}[func]
        location = func_args[3] if len(func_args) > 3 else None
        return func_args[0], f"{kind} {location_header_line(location)}" if location else kind
    names = {_task_chassis: "chassis", _task_scaling: "performance scaling", _task_versus: "max versus"}
    if func in names:
        return func_args[0], names[func]
    return "", "comparison reports"


def _task_env_bench(trace_idx, bench_name, output_dir_str):
    """Generate all environment graphs for a single (trace, bench) pair."""
    global _pool_args
    args = _pool_args
    trace = args.traces[trace_idx]
    output_dir = pathlib.Path(output_dir_str)
    count = 0
    count += graph_monitoring_metrics(args, trace, bench_name, output_dir)
    count += graph_fans(args, trace, bench_name, output_dir)
    count += graph_cpu(args, trace, bench_name, output_dir)
    count += graph_cpu_numa(args, trace, bench_name, output_dir)
    count += graph_gpu(args, trace, bench_name, output_dir)
    count += graph_pdu(args, trace, bench_name, output_dir)
    count += graph_cdu(args, trace, bench_name, output_dir)
    count += graph_thermal(args, trace, bench_name, output_dir)
    return count


def _task_numa_distance(trace_idx, output_dir_str):
    """Generate the per-host NUMA distance heatmap (once per trace)."""
    global _pool_args
    return numa_distance_heatmap(_pool_args, pathlib.Path(output_dir_str), _pool_args.traces[trace_idx])


def _task_chassis(bench_name, output_dir_str):
    """Generate chassis graphs for a single bench."""
    global _pool_args
    return graph_chassis(_pool_args, bench_name, pathlib.Path(output_dir_str))


def group_args(trace_indexes, location):
    """The arguments of the graphs of a group of --auto-group: they give the location of its place in their
    header, even when its servers are in several racks, with the number of servers it holds, and the name
    of the place in their file names."""
    args = copy.copy(_pool_args)
    args.traces = [_pool_args.traces[index] for index in trace_indexes]
    group = LocationGroup(location, args.traces)
    args.location = f"{location_header_line(location, emphasis=True)} ({len(args.traces)} servers)"
    args.cdus = shared_cdu_lines(args.traces)
    args.place_name = group.place_name()
    return args


def _task_group(bench_name, output_dir_str, trace_indexes=None, location=None):
    """Generate group graphs for a single bench, of all the traces or of a group found by --auto-group."""
    args = _pool_args if trace_indexes is None else group_args(trace_indexes, location)
    return graph_group_env(args, bench_name, pathlib.Path(output_dir_str))


def _task_rack(bench_name, output_dir_str, trace_indexes, location, positions):
    """Generate the rack graphs of a single bench, for a rack found by --auto-group."""
    return graph_rack(group_args(trace_indexes, location), bench_name, pathlib.Path(output_dir_str), positions)


def _task_racks(bench_name, output_dir_str, trace_indexes, location, racks):
    """Generate the elevation of the racks of a place holding several of them, found by --auto-group: <racks>
    gives the name, the trace indexes and the positions of each."""
    args = group_args(trace_indexes, location)
    loaded = [(name, [_pool_args.traces[index] for index in indexes], positions) for name, indexes, positions in racks]
    return graph_racks(args, bench_name, pathlib.Path(output_dir_str), loaded)


def _task_scaling(job, output_dir_str, traces_name):
    """Generate performance scaling graphs for a job."""
    global _pool_args
    return performance_scaling_graph(_pool_args, pathlib.Path(output_dir_str), job, traces_name)


def _task_scaling_comparison(output_dir_str):
    """Write the traces-comparison summaries + exec-summary scorecard (reference = first trace)."""
    global _pool_args
    output_dir = pathlib.Path(output_dir_str)
    count = write_scaling_comparison(_pool_args, output_dir)
    count += render_versus_scorecard(_pool_args, output_dir)
    # Same comparison, but one file per scaling step under scaling/.
    count += write_scaling_step_comparisons(_pool_args, output_dir)
    return count


def _task_versus(job, output_dir_str, traces_name):
    """Generate max versus graphs for a job."""
    global _pool_args
    return max_versus_graph(_pool_args, pathlib.Path(output_dir_str), job, traces_name)


# ---------------------------------------------------------------------------
# Task collection functions
# ---------------------------------------------------------------------------


def _collect_group_tasks(args, output_dir):
    """Collect group graph tasks."""
    tasks = []
    if args.auto_group:
        return _collect_auto_group_tasks(args, output_dir)
    if not args.same_group:
        return tasks
    # Graphs below are per group
    output_dir = output_dir.joinpath(GROUP_DIRECTORY)
    for trace in args.traces:
        try:
            trace.first_bench().get_single_metric(
                MonitoringContextKeys.PowerConsumption,
                PowerConsumptionContextKeys.BMC,
                PowerCategories.SERVER,
            )
        except KeyError:
            fatal(f"group: missing 'BMC/{PowerCategories.SERVER}' monitoric metric in {trace.get_filename()}")
        # The power of the components the topology says cooled by a liquid, taken from the one of the server
        _, missing = liquid_cooled(trace.first_bench(), trace.get_cooling())
        if missing:
            fatal(
                f"group: missing '{missing[0]}' monitoric metric in {trace.get_filename()}, "
                "the power of a component cooled by a liquid"
            )
    print(f"group: rendering {len(args.traces[0].bench_list())} jobs")
    for bench_name in sorted(args.traces[0].bench_list()):
        tasks.append((_task_group, bench_name, str(output_dir)))
    return tasks


def _collect_auto_group_tasks(args, output_dir):
    """Collect the group graph tasks of each place of the location of the traces, found by --auto-group."""
    groups = location_groups(args.traces)
    if not groups:
        print("auto-group: no place shared by several traces, nothing to group")
        return []
    tasks = []
    rendered = {}
    # The racks, the places right above the positions of their servers, with their positions
    racks = {}
    for group in groups:
        positions, rack_problem = rack_positions(group.location.path, group.traces)
        racks[group.name()] = (positions, rack_problem)
    for group in groups:
        group_dir = output_dir.joinpath(GROUP_DIRECTORY, *group.directories())
        trace_indexes = [args.traces.index(trace) for trace in group.traces]
        # A rack also renders its rack view
        positions, rack_problem = racks[group.name()]
        notes = [rack_problem] if rack_problem else ["rack view"] if positions else []
        if positions:
            for bench_name in group_benches(group):
                tasks.append((_task_rack, bench_name, str(group_dir), trace_indexes, group.location, positions))
        # A place holding several racks renders their elevation side by side
        inner = [
            other
            for other in groups
            if racks[other.name()][0]
            and len(other.location.path) > len(group.location.path)
            and other.location.path[: len(group.location.path)] == group.location.path
        ]
        if not positions and len(inner) > 1:
            notes.append(f"racks view of {len(inner)} racks")
            described = [
                (
                    other.location.places()[-1],
                    [args.traces.index(trace) for trace in other.traces],
                    racks[other.name()][0],
                )
                for other in inner
            ]
            for bench_name in group_benches(group):
                tasks.append((_task_racks, bench_name, str(group_dir), trace_indexes, group.location, described))
        problem = group_problem(group)
        if problem:
            notes.insert(0, f"not rendered, {problem}")
        rendered[group.name()] = ", ".join(notes)
        if problem:
            continue
        # The graphs of a group add up the samples of its servers: only the jobs they all ran
        for bench_name in group_benches(group, skipped=False):
            tasks.append((_task_group, bench_name, str(group_dir), trace_indexes, group.location))
    print(f"auto-group: {len(groups)} places shared by several traces, in {GROUP_DIRECTORY}/:")
    print("\n".join(auto_group_tree(groups, rendered, args.verbose)))
    return tasks


def auto_group_tree(groups: list[LocationGroup], rendered: dict[str, str], verbose: bool = False) -> list[str]:
    """The groups of --auto-group as a tree, each under the narrowest group holding it, with its number
    of servers and why it is not rendered; its servers too when verbose."""
    entries = []
    depths: dict[str, int] = {}
    for group in groups:
        directories = group.directories()
        holders = [
            other
            for other in groups
            if len(other.directories()) < len(directories)
            and directories[: len(other.directories())] == other.directories()
        ]
        parent = max(holders, key=lambda other: len(other.directories()), default=None)
        depth = depths[parent.name()] + 1 if parent else 0
        depths[group.name()] = depth
        label = "  " * (depth + 1) + "/".join(directories[len(parent.directories()) if parent else 0 :])
        entries.append((group, label))
    width = max(len(label) for _, label in entries)
    lines = []
    for group, label in entries:
        line = f"{label.ljust(width)}  {len(group.traces):>4} servers"
        if rendered.get(group.name()):
            line += f", {rendered[group.name()]}"
        lines.append(line)
        if verbose:
            indent = " " * (len(label) - len(label.lstrip()) + 2)
            lines.append(indent + ", ".join(trace.get_name() for trace in group.traces))
    return lines


def _collect_environment_tasks(args, output_dir):
    """Collect environment graph tasks."""
    tasks = []
    # If user disabled the environmental graphs, return immediately
    if not args.no_env:
        print("environment: disabled by user")
        return tasks

    output_dir = output_dir.joinpath("environment")

    chassis = args.traces[0].get_chassis_serial()
    if chassis:
        all_chassis = [t.get_chassis_serial() == chassis for t in args.traces]
        # if all traces are from the same chassis, let's enable the same_chassis feature
        if all_chassis.count(True) == len(args.traces) and len(args.traces) > 1:
            print(f"environment: All traces are from the same chassis ({chassis}), enabling --same-chassis feature")
            args.same_chassis = True

    if args.same_chassis:

        def valid_traces(args):
            server = [trace.get_server_serial() for trace in args.traces]
            # Let's ensure we don't have the same serial twice

            if len(server) == len(args.traces):
                # Let's ensure all traces has server and chassis metrics
                for trace in args.traces:
                    try:
                        for metric in [
                            PowerCategories.CHASSIS,
                            PowerCategories.SERVER,
                        ]:
                            trace.first_bench().get_single_metric(
                                MonitoringContextKeys.PowerConsumption,
                                PowerConsumptionContextKeys.BMC,
                                metric,
                            )
                    except KeyError:
                        return f"environment: missing '{metric}' monitoric metric in {trace.get_filename()}, disabling same-enclosure print"
            else:
                return "environment: server are not unique, disabling same-chassis print"
            return ""

        error_message = valid_traces(args)
        if not error_message:
            for bench_name in sorted(args.traces[0].bench_list()):
                tasks.append((_task_chassis, bench_name, str(output_dir.joinpath("by_chassis"))))
        else:
            print(error_message)

    # Graphs below are per host
    host_output_dir = output_dir.joinpath("by_host")
    # A job skipped by a host, like an AVX-512 one on a CPU without it, has no environment to render
    host_benches = [
        sorted(name for name, bench in trace.bench_list().items() if not bench.get("skipped")) for trace in args.traces
    ]
    if not args.verbose:
        jobs = sum(len(benches) for benches in host_benches)
        print(f"environment: rendering {jobs} jobs of {len(args.traces)} traces in {host_output_dir}")
    for trace_idx, (trace, benches) in enumerate(zip(args.traces, host_benches)):
        host_output_dir.joinpath(f"{trace.get_name()}").mkdir(parents=True, exist_ok=True)
        if args.verbose:
            print(f"environment: rendering {len(benches)} jobs from {trace.get_filename()} ({trace.get_name()})")
        for bench_name in benches:
            tasks.append((_task_env_bench, trace_idx, bench_name, str(host_output_dir)))
        # One NUMA distance heatmap per host, not tied to any benchmark.
        tasks.append((_task_numa_distance, trace_idx, str(host_output_dir)))

    return tasks


def _collect_plot_tasks(args, output_dir):
    """Collect scaling and versus graph tasks."""
    tasks = []
    jobs = []
    for bench_name in sorted(args.traces[0].bench_list()):
        job_name = args.traces[0].bench(bench_name).job_name()
        # We want to keep a single job type
        # i.e an avx test can be rampuped from 1 to 64 cores, generating tens of sub jobs
        # We just want to keep the "avx" test as a reference, not all iterations
        if job_name not in jobs:
            jobs.append(job_name)

    traces_name = [trace.get_name() for trace in args.traces]

    if not args.no_scaling:
        print("Performance scaling: disabled by user")
    else:
        # Let's generate the scaling graphs
        print(f"Performance scaling: rendering {len(jobs)} jobs")
        for job in jobs:
            tasks.append((_task_scaling, job, str(output_dir), traces_name))

    if not args.no_versus:
        print("Max versus: disabled by user")
    else:
        # Let's generate the unitary comparing graphs
        if len(traces_name) > 1:
            print(f"Max versus: rendering {len(jobs)} jobs")
            for job in jobs:
                tasks.append((_task_versus, job, str(output_dir), traces_name))
            # Text reports comparing every trace to the first (reference): one at
            # full load covering all benchmarks (max_versus/benchmarks_summary.txt)
            # plus one per scaling step under scaling/.
            tasks.append((_task_scaling_comparison, str(output_dir)))
        else:
            print("Max versus: skipped as at least 2 traces are necessary for this mode")

    return tasks


# ---------------------------------------------------------------------------
# Task execution
# ---------------------------------------------------------------------------


def _execute_tasks(args, tasks, output_dir: pathlib.Path):
    """Execute graph generation tasks, using multiprocessing when jobs > 1."""
    global _pool_args
    num_workers = max(1, min(args.jobs, len(tasks)))
    rendered_graphs = 0

    log = RenderLog()

    def done(completed: int, task, result: tuple[int, str, str | None]) -> str | None:
        """Account for a task done, and tell why the rendering must stop, if it must."""
        nonlocal rendered_graphs
        rendered_graphs += result[0]
        log.add(*describe_task(args, task), result[1])
        progress("rendering", completed, len(tasks), f"tasks, {rendered_graphs} graphs")
        return result[2]

    abort = None

    if num_workers <= 1:
        # Single-process mode: execute tasks sequentially
        _pool_args = args
        for completed, task in enumerate(tasks, 1):
            abort = done(completed, task, _execute_pool_task(task))
            if abort:
                break
    else:
        # Multi-process mode
        print(f"Rendering graphs using {num_workers} parallel workers for {len(tasks)} tasks")
        # The traces are sent without their content, see Trace.__getstate__(), and the main process
        # drops it too while the workers render: the tasks read the traces they use again, from the cache
        args_data = pickle.dumps(args, protocol=pickle.HIGHEST_PROTOCOL)
        for trace in args.traces:
            trace.forget_content()
        with ProcessPoolExecutor(
            max_workers=num_workers,
            mp_context=multiprocessing.get_context(WORKERS_START_METHOD),
            initializer=_init_pool_worker,
            initargs=(args_data, os.getpid()),
        ) as pool:
            futures = {pool.submit(_execute_pool_task, task): task for task in tasks}
            for completed, future in enumerate(as_completed(futures), 1):
                try:
                    result = future.result()
                except Exception as e:
                    # A worker dying, out of memory for instance, breaks the pool: no task can be done anymore
                    result = (0, f"Error generating graph: {e}", f"{type(e).__name__}: {e}")
                abort = done(completed, futures[future], result)
                if abort:
                    # Not waiting for the tasks left, nor for the ones running: their workers are stopped
                    # Listed before the shutdown, which forgets them
                    workers = list((getattr(pool, "_processes", None) or {}).values())
                    pool.shutdown(wait=False, cancel_futures=True)
                    for process in workers:
                        process.terminate()
                    break

    # What the graphs printed, by job, in the output directory: only its summary on the console
    log_file = log.write(output_dir)
    if abort:
        listed = f", the messages of the graphs are in {log_file}" if log_file else ""
        fatal(
            f"rendering aborted after {rendered_graphs} graphs: {abort}{listed}; the traces converted are kept "
            f"in {output_dir.joinpath(CACHE_DIRECTORY)} for the next rendering in {output_dir}"
        )
    if log.errors or log.warnings:
        print(f"rendering: {log.summary()}, listed in {log_file}")
    elif log_file:
        print(f"rendering: no warning nor error, the messages of the graphs are in {log_file}")
    else:
        print("rendering: no warning nor error")
    return rendered_graphs


# ---------------------------------------------------------------------------
# Argument validators
# ---------------------------------------------------------------------------


def valid_trace_file(trace_arg: str) -> Trace:
    """Custom argparse type to decode and validate the trace files"""

    match = re.search(r"(?P<filename>.*):(?P<logical_name>.*):(?P<power_metric>.*)", trace_arg)
    if not match:
        raise argparse.ArgumentTypeError(
            f"{trace_arg} does not match 'trace_filename:logical_name:power_metric' syntax"
        )

    # The trace is read and validated when rendered, one trace at a time, from the cache of the
    # output directory: see render_trace_set()
    if not pathlib.Path(match.group("filename")).is_file():
        raise argparse.ArgumentTypeError(f"{match.group('filename')} is not a valid file")
    return Trace(match.group("filename"), match.group("logical_name"), match.group("power_metric"), load=False)


def valid_events(event_arg: str) -> Event:
    """Custom argparse type to decode and validate the event list"""

    match = re.search(r"(?P<event>.*):(?P<start>.*):(?P<duration>.*)", event_arg)
    if not match:
        raise argparse.ArgumentTypeError(f"{event_arg} does not match 'event_name:start_time:duration' syntax")

    try:
        event = Event(
            match.group("event"),
            int(match.group("start")),
            int(match.group("duration")),
        )
        event.validate()
        return event
    except BaseException as e:
        # Print validation failure and pass it on
        print(f"Event validation failure: {e}")
        raise e


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------


def list_metrics_in_trace(args: argparse.Namespace):
    """List power metrics of a trace file, or the contexts of the traces of a directory"""
    if args.contexts:
        print_contexts(pathlib.Path(args.contexts))
    else:
        Trace(args.trace).list_power_metrics()
    sys.exit(0)


def write_cmdline(output_dir: pathlib.Path):
    """Save the actual cmdline in the output directory so it's easier to regenerate graph"""
    # Do not expose the actual hwbench path like /home/user/hwbench/...
    argv = ["hwgraph", *sys.argv[1:]]
    # Keep quotes from the argument list with shlex
    output_dir.joinpath("cmdline").write_text(" ".join(shlex.quote(arg) for arg in argv))


def render_traces(args: argparse.Namespace):
    """Render the trace files passed in arguments, or each context found by --auto-traces"""
    init_matplotlib(args)
    if not args.auto_traces:
        render_and_remove_cache(args, pathlib.Path(args.outdir))
        return

    # The traces of each context are rendered in a subdirectory named after it, so the
    # renderings of several contexts can share the same --outdir
    for index, auto_traces in enumerate(args.auto_traces, start=1):
        context_args = copy.copy(args)
        output_dir = pathlib.Path(args.outdir, auto_traces.output_directory_name())
        # A banner on the console separates the rendering of each context
        banner = f"Context {index}/{len(args.auto_traces)}: {auto_traces.context or 'none'}"
        print(f"\n{'=' * 80}\n{banner}\n{'=' * 80}")
        output_dir.mkdir(parents=True, exist_ok=True)
        # The traces found are listed in the output directory, and on the console only when verbose
        description = auto_traces.description()
        traces_file = output_dir.joinpath(AUTO_TRACES_FILE)
        traces_file.write_text("\n".join(description) + "\n")
        if args.verbose:
            print("\n".join(description))
        else:
            print(
                f"{len(auto_traces.traces)} traces {auto_traces.label()} "
                f"found in {auto_traces.directory}, listed in {traces_file}"
            )
        context_args.traces = auto_traces.traces
        render_and_remove_cache(context_args, output_dir)


def render_and_remove_cache(args: argparse.Namespace, output_dir: pathlib.Path):
    """Render the traces of args.traces in output_dir, then delete the cache of their conversion unless
    --keep-cache: it takes about the size of the traces. A rendering stopping keeps it: running it again
    in the same output directory reads the traces without converting them again."""
    render_trace_set(args, output_dir)
    if not args.keep_cache:
        remove_cache(args.traces, output_dir.joinpath(CACHE_DIRECTORY))


def render_trace_set(args: argparse.Namespace, output_dir: pathlib.Path):
    """Render the traces of args.traces in output_dir"""
    output_dir.mkdir(parents=True, exist_ok=True)
    write_cmdline(output_dir)
    # The traces are read from now on from their conversion in the cache of the output directory, then
    # validated, one at a time: the main process holds the content of a single trace
    cache_directory = output_dir.joinpath(CACHE_DIRECTORY)
    # Converting the traces of a fleet takes a while: the workers convert them, then the main process
    # validates them in their order, which numbers the serials left unset
    print(f"cache: preparing {len(args.traces)} traces in {cache_directory}")
    filenames = [trace.get_filename() for trace in args.traces]
    with ProcessPoolExecutor(max_workers=max(1, min(args.jobs, len(filenames)))) as pool:
        conversions = pool.map(convert_trace, filenames, itertools.repeat(cache_directory))
        for index, trace in enumerate(args.traces, 1):
            try:
                trace.use_cache(cache_directory, next(conversions))
            except (ValueError, OSError, tarfile.TarError, EOFError) as e:
                # Not waiting for the conversion of the other traces before stopping
                pool.shutdown(cancel_futures=True)
                fatal(f"Trace validation failure: {e}")
            trace.validate()
            trace.forget_content()
            progress("cache", index, len(args.traces), "traces ready")

    # The context of the runs, given to hwbench with --context, gets its own line in the
    # header of every graph, under the line naming the benchmark: see context_header()
    args.context = context_line(args.traces)
    if args.context:
        print(args.context)
    # The location the servers share goes in the headers of the graphs of several servers,
    # under the context: see location_header(); a single server gives its own under its serial
    # The graphs give its narrowest place in bold, the console as is
    args.location = shared_location_line(args.traces, emphasis=True) if len(args.traces) > 1 else None
    if args.location:
        print(shared_location_line(args.traces))
    # So do the CDUs monitored with all the servers, under the location: see cdu_header()
    args.cdus = shared_cdu_lines(args.traces) if len(args.traces) > 1 else []
    for cdu in args.cdus:
        print(f"CDU: {cdu}")

    compare_traces(args)
    generate_stats(args)

    # Write the per-host benchmarks summary text table before rendering any graph,
    # so the key to what each benchmark tests is available up front. args.no_env is
    # True when environmental graphs are enabled (--no-env, store_false, disables).
    if args.no_env:
        host_output_dir = output_dir.joinpath("environment", "by_host")
        for trace in args.traces:
            write_benchmarks_summary(args, host_output_dir, trace)
        if not args.verbose:
            print(
                f"benchmarks: wrote the benchmarks summary of {len(args.traces)} traces in "
                f"{host_output_dir}/<trace>/benchmarks_summary.txt"
            )

    # Collect all graph generation tasks
    # (This also performs validation and creates output directories)
    tasks = []
    tasks.extend(_collect_group_tasks(args, output_dir))
    tasks.extend(_collect_environment_tasks(args, output_dir))
    tasks.extend(_collect_plot_tasks(args, output_dir))

    if not tasks:
        print("No graphs to render")
        return

    rendered_graphs = _execute_tasks(args, tasks, output_dir)
    print(f"{rendered_graphs} graphs can be found in '{output_dir}' directory")


# ---------------------------------------------------------------------------
# Sequential helpers (unchanged, used by task workers)
# ---------------------------------------------------------------------------


def generate_stats(args) -> None:
    if not args.no_stats:
        return
    # One line per trace only when verbose: a fleet would flood the console
    if not args.verbose:
        print(
            f"stats: rendering {sum(len(trace.bench_list()) for trace in args.traces)} jobs of {len(args.traces)} traces"
        )
    # The max of each power metric of all the traces: where it is reached, its benchmark and its value.
    # The cores give a single line, a server holding hundreds of them.
    max_power: dict[str, tuple[str, str, float]] = {}
    for index, trace in enumerate(args.traces, 1):
        benches = trace.bench_list()
        if args.verbose:
            print(f"stats: rendering {len(benches)} jobs from {trace.get_filename()} ({trace.get_name()})")
        for bench_name in sorted(benches):
            bench = trace.bench(bench_name)
            for context in PowerConsumptionContextKeys:
                try:
                    metrics = bench.get_component(MonitoringContextKeys.PowerConsumption, context)
                except KeyError:
                    continue
                for metric, values in metrics.items():
                    # If a metric has no measure, let's ignore it
                    if len(values.get_samples()) == 0:
                        if args.verbose:
                            print(f"{bench_name}: No samples found in {context}.{metric}, ignoring metric.")
                        continue
                    max_values = values.get_max()
                    if not len(max_values):
                        continue
                    core = metric.startswith("Core_")
                    name = f"{context}.Core_*" if core else f"{context}.{metric}"
                    where = f"{trace.get_name()} {metric}" if core else trace.get_name()
                    current_max = float(max(max_values))
                    if name not in max_power or current_max > max_power[name][2]:
                        max_power[name] = (where, bench_name, current_max)
        # Read one at a time, as by the rest of the main process: kept, the traces of a fleet fill the memory
        trace.forget_content()
        if not args.verbose:
            progress("stats", index, len(args.traces), "traces read")

    print(f"{MonitoringContextKeys.PowerConsumption}")
    # Only report a max when data was actually found (a bench was recorded).
    if not max_power:
        return
    # Aligned in columns: the metric, its value, its benchmark
    name_width = max(len(name) for name in max_power)
    value_width = max(len(f"{value:.2f}") for _, _, value in max_power.values())
    bench_width = max(len(bench_name) for _, bench_name, _ in max_power.values())
    unit = bench.get_metric_unit(MonitoringContextKeys.PowerConsumption)
    for name, (where, bench_name, value) in max_power.items():
        print(
            f"    {name:<{name_width}} max : {value:>{value_width}.2f} {unit} in {bench_name:<{bench_width}} of {where}"
        )


def compare_traces(args) -> None:
    """Check if benchmark definition are similar."""
    # To ensure a fair comparison, jobs must come from the same configuration file
    # But the number and names can be different regarding the hardware configuration.
    # To determine if traces can be compared, we'll compare only
    # the original configuration files, not the actual jobs.

    names = []
    for trace in args.traces:
        # Is the current trace config file matches the first trace ?
        if args.traces[0].get_original_config() != trace.get_original_config():
            # If a trace is not having the same configuration file,
            # It's impossible to compare & graph the results.
            differences = config_differences(args.traces[0].get_original_config(), trace.get_original_config())
            fatal(
                f"{trace.filename} is not having the same configuration file as previous traces\n"
                f"--- {args.traces[0].filename}\n+++ {trace.filename}\n" + "\n".join(differences)
            )
        if trace.get_name() in names:
            fatal(f"{trace.filename} is using '{trace.get_name()}' as logical_name while it's already in use")
        else:
            names.append(trace.get_name())


def graph_monitoring_metrics(args, trace: Trace, bench_name: str, output_dir) -> int:
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    for metric_name in MonitorContextKeys:
        try:
            metrics = bench.get_component(MonitoringContextKeys.Monitor, metric_name)
        except KeyError:
            print(f"{bench_name}: {metric_name} metric is not present in trace file, skipping.")
            continue
        if metrics:
            for metric in metrics:
                # The timeouts are counts, rendered together by timeouts_graph()
                if metric == TIMEOUTS:
                    continue
                # If a metric has no measure, let's ignore it
                if len(metrics[metric].get_samples()) == 0:
                    if args.verbose:
                        print(f"{bench_name}: No samples found in {metric_name}.{metric}, ignoring metric.")
                else:
                    try:
                        rendered_graphs += yerr_graph(
                            args,
                            output_dir,
                            bench,
                            MonitoringContextKeys.Monitor,
                            metrics[metric],
                            prefix=f"{metric_name}.",
                        )
                    except InvalidValue as e:
                        print(f"An error occurred while generating the graph for {bench_name} ({metric_name}): {e}")

    rendered_graphs += timeouts_graph(args, output_dir, bench)
    return rendered_graphs


def graph_fans(args, trace: Trace, bench_name: str, output_dir) -> int:
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    fans = bench.get_component(MonitoringContextKeys.Fans, FansContextKeys.Fan)
    if not fans:
        print(f"{bench_name}: no fans")
        return rendered_graphs
    for second_axis in [MonitoringContextKeys.Thermal, MonitoringContextKeys.PowerConsumption]:
        rendered_graphs += generic_graph(args, output_dir, bench, MonitoringContextKeys.Fans, "Fans speed", second_axis)

    for fan in fans:
        rendered_graphs += yerr_graph(args, output_dir, bench, MonitoringContextKeys.Fans, fans[fan])

    return rendered_graphs


def graph_component_family(
    args,
    output_dir,
    bench,
    context: MonitoringContextKeys,
    item_title: str,
    unit: ScalingUnit,
    renderings: list,
    components: list | None = None,
) -> int:
    """Render one metric of one component family: time series + distribution.

    'unit' is the ScalingUnit of the family being rendered -- not necessarily the
    one the benchmark scales on -- and carries which components to filter on and
    how to name them.

    'renderings' is a list of (dir_suffix, names, title_note): the same metric is
    plotted once per entry, each in its own subdirectory, so a view restricted to
    the components a benchmark actually used never collides with the full one.
    """
    rendered_graphs = 0
    filter = unit.family
    for dir_suffix, names, title_note in renderings:
        # The full view is rendered from the list the caller already resolved;
        # a restricted view is that same list filtered, so the context is walked
        # once per metric instead of once per graph.
        rendered = components
        if names is not None and components is not None:
            rendered = [component for component in components if component.get_name() in names]
        for second_axis in [None, MonitoringContextKeys.Thermal, MonitoringContextKeys.PowerConsumption]:
            rendered_graphs += generic_graph(
                args,
                output_dir,
                bench,
                context,
                item_title,
                second_axis,
                filter=filter,
                names=names,
                dir_suffix=dir_suffix,
                title_note=title_note,
                components=rendered,
            )
        rendered_graphs += component_distribution_graph(
            args,
            output_dir,
            bench,
            context,
            item_title,
            filter=filter,
            names=names,
            dir_suffix=dir_suffix,
            title_note=title_note,
            item_name=unit.item_name,
            components=rendered,
        )
    return rendered_graphs


def graph_cpu(args, trace: Trace, bench_name: str, output_dir) -> int:
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    cpu_graphs = [
        ("CPU Core power consumption", MonitoringContextKeys.PowerConsumption, "Core"),
        ("Package power consumption", MonitoringContextKeys.PowerConsumption, "package"),
        ("Core frequency", MonitoringContextKeys.Freq, "Core"),
        ("Core IPC", MonitoringContextKeys.IPC, "Core"),
    ]
    # Per-core metrics (filter "Core") are rendered twice: once for all the
    # cores of the system, once restricted to the cores that were pinned during
    # this benchmark job.
    pinned_core_names = bench.pinned_core_names()
    pinned_note = f"View limited to the pinned logical cores {bench.pinned_cpu_range()}"

    for item_title, context, filter in cpu_graphs:
        if filter == CORE_FAMILY:
            renderings = [("all_cores", None, None)]  # type: list
            if pinned_core_names:
                renderings.append(("pinned_cores", pinned_core_names, pinned_note))
        else:
            # Non per-core metrics (e.g. package power) keep a single rendering,
            # and no distribution: there is a single component to distribute.
            rendered_graphs += sum(
                generic_graph(args, output_dir, bench, context, item_title, second_axis, filter=filter)
                for second_axis in [None, MonitoringContextKeys.Thermal, MonitoringContextKeys.PowerConsumption]
            )
            continue
        rendered_graphs += graph_component_family(
            args, output_dir, bench, context, item_title, CPU_SCALING_UNIT, renderings
        )

    return rendered_graphs


def graph_gpu(args, trace: Trace, bench_name: str, output_dir) -> int:
    """Render the per-GPU environment metrics.

    Built like graph_cpu(), with one difference: GPUs are never pinned, so the
    restricted view is the GPUs the benchmark used rather than the pinned cores.
    The components come from two independent sources -- all-smi reports
    GPU_<index> while the BMC reports BMC_GPU_<redfish id>. Both live in the
    "GPU" family of their context and are plotted together.
    """
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    gpu_graphs = [
        ("GPU power consumption", MonitoringContextKeys.PowerConsumption),
        ("GPU frequency", MonitoringContextKeys.Freq),
        ("GPU temperature", MonitoringContextKeys.Thermal),
        ("GPU utilization", MonitoringContextKeys.Utilization),
        ("GPU memory usage", MonitoringContextKeys.Memory),
    ]

    # Only a subset of the GPUs is loaded by a pantheon benchmark, so, like the
    # pinned cores of graph_cpu(), they get their own rendering: the idle GPUs
    # would otherwise flatten the used ones. The subset only covers the
    # all-smi metrics, as Redfish ids cannot be mapped to accelerator indexes.
    #
    # The unit is the GPU one, not bench.scaling_unit(): this renders the GPU
    # family whatever the benchmark scales on, and the unit of a CPU benchmark
    # would name the restricted view after its pinned cores.
    used_gpu_names = bench.gpu_names()
    used_note = f"View limited to the GPUs used by this benchmark {bench.gpu_list()}"

    for item_title, context in gpu_graphs:
        components = bench.get_all_metrics(context, GPU_SCALING_UNIT.family)
        if not components:
            continue

        renderings = [(None, None, None)]  # type: list
        if used_gpu_names and any(component.get_name() not in used_gpu_names for component in components):
            renderings.append((GPU_SCALING_UNIT.subset_dir, used_gpu_names, used_note))

        rendered_graphs += graph_component_family(
            args, output_dir, bench, context, item_title, GPU_SCALING_UNIT, renderings, components=components
        )

    return rendered_graphs


def graph_cpu_numa(args, trace: Trace, bench_name: str, output_dir) -> int:
    """Render per-core CPU metrics aggregated by NUMA domain (one line per domain).

    Requires the NUMA topology in the trace; older traces without it are skipped.
    """
    numa_nodes = trace.get_numa_nodes()
    if not numa_nodes:
        print(f"{bench_name}: no NUMA metric present in trace file, skipping.")
        return 0
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    numa_graphs = {
        "Core frequency per NUMA domain": MonitoringContextKeys.Freq,
        "Core IPC per NUMA domain": MonitoringContextKeys.IPC,
        "CPU Core power consumption per NUMA domain": MonitoringContextKeys.PowerConsumption,
    }
    # Metrics that also get a per-domain x time heatmap next to their line graph.
    heatmap_metrics = {MonitoringContextKeys.Freq, MonitoringContextKeys.IPC}
    # Like the per-core graphs: one rendering averaging every core of each domain
    # (all_numa), and one restricted to the cores pinned during this job, grouped
    # by the domains those pinned cores belong to (pinned_numa).
    pinned_core_names = bench.pinned_core_names()
    # Each rendering is a dir suffix, the pinned-core filter, and a title note.
    renderings = [("all_numa", None, None)]  # type: list
    if pinned_core_names:
        pinned_note = f"View limited to the pinned logical cores {bench.pinned_cpu_range()}"
        renderings.append(("pinned_numa", pinned_core_names, pinned_note))

    for graph_name, metric in numa_graphs.items():
        for dir_suffix, pinned_cores, title_note in renderings:
            components = numa_aggregated_components(bench, metric, numa_nodes, pinned_cores)
            if not components:
                continue
            rendered_graphs += generic_graph(
                args,
                output_dir,
                bench,
                metric,
                graph_name,
                dir_suffix=dir_suffix,
                components=components,
                title_note=title_note,
            )
            # Companion heatmap: NUMA domain x time, color = per-domain value.
            if metric in heatmap_metrics:
                rendered_graphs += numa_performance_heatmap(
                    args,
                    output_dir,
                    bench,
                    metric,
                    graph_name,
                    numa_nodes,
                    dir_suffix=dir_suffix,
                    pinned_cores=pinned_cores,
                    title_note=title_note,
                )
            # Companion violin: one steady-state distribution per NUMA domain.
            rendered_graphs += numa_distribution_graph(
                args,
                output_dir,
                bench,
                metric,
                graph_name,
                numa_nodes,
                dir_suffix=dir_suffix,
                pinned_cores=pinned_cores,
                title_note=title_note,
            )
    return rendered_graphs


def graph_pdu(args, trace: Trace, bench_name: str, output_dir) -> int:
    rendered_graphs = 0
    bench = trace.bench(bench_name)
    pdu_graphs = {}
    pdu_graphs["PDU power reporting"] = {MonitoringContextKeys.PowerConsumption: "PDU"}
    for graph_name in pdu_graphs:
        # Let's render the performance, perf_per_temp, perf_per_watt graphs
        for metric, filter in pdu_graphs[graph_name].items():
            for second_axis in [None, MonitoringContextKeys.Thermal, MonitoringContextKeys.PowerConsumption]:
                rendered_graphs += generic_graph(
                    args,
                    output_dir,
                    bench,
                    metric,
                    graph_name,
                    second_axis,
                    filter=filter,
                )

    return rendered_graphs


def graph_thermal(args, trace: Trace, bench_name: str, output_dir) -> int:
    rendered_graphs = 0
    rendered_graphs += generic_graph(
        args, output_dir, trace.bench(bench_name), MonitoringContextKeys.Thermal, "Thermal"
    )
    return rendered_graphs


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        prog="hwgraph",
        description="compare hwbench results and plot them",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    subparsers = parser.add_subparsers(help="hwgraph sub-commands")

    parser_graph = subparsers.add_parser("graph", help="Generate graphs from trace files")
    traces_group = parser_graph.add_mutually_exclusive_group(required=True)
    traces_group.add_argument(
        "--traces",
        type=valid_trace_file,
        nargs="+",
        help="""List of benchmarks to compare.
Syntax: <trace_filename>:<logical_name>:<power_metric>
trace_filename : a results.json output file from hwbench, or the hwbench-<serial>-<timestamp>.tar.xz archive
logical_name   : a name to represent the trace in the graph
                 if omitted, it will be replaced by the system serial number
                 'CPU' magic keyword implicit the use of CPU model as logical_name but must be unique over all trace files.
power_metric   : the name of a power metric, from the monitoring, to be used for 'watts' and 'perf per watt' graphs; for example CPU.package or BMC.ServerInChassis.
                 In order to know exeactly what metric names you can use for a given trace, use the "list" toplevel subcommand.
""",
    )
    # Searched after the parsing, see main(): reading every archive of the directory would delay --help
    traces_group.add_argument(
        "--auto-traces",
        help="""Use the traces of a context, found in a directory.
Syntax: <directory>:<context>:<power_metric>
directory    : where the results.json and the hwbench-<serial>-<timestamp>.tar.xz archives are looked for, recursively
context      : the context given to hwbench with --context, or empty (<directory>::<power_metric>) to render every context,
               then the traces without context, together in the no_context subdirectory;
               the traces are named after their server, which must appear once in a context
power_metric : the power metric of every trace, as for --traces
The graphs of each context are rendered in a subdirectory of --outdir named after it, in ASCII, '_' replacing the spaces and the other characters.
The traces used are listed on the console and in its auto_traces.txt.
Use "hwgraph list --contexts <directory>" to list the contexts of a directory.
""",
    )
    parser_graph.add_argument("--no-env", help="Disable environmental graphs", action="store_false")
    parser_graph.add_argument("--no-scaling", help="Disable 'Performance scaling' graphs", action="store_false")
    parser_graph.add_argument("--no-versus", help="Disable 'max versus' graphs", action="store_false")
    parser_graph.add_argument("--no-stats", help="Disable stats", action="store_false")
    parser_graph.add_argument("--title", help="Title of the graph", default="")
    parser_graph.add_argument("--dpi", help="Graph dpi", type=int, default="72")
    parser_graph.add_argument("--width", help="Graph width", type=int, default="1920")
    parser_graph.add_argument("--height", help="Graph height", type=int, default="1080")
    parser_graph.add_argument(
        "--events",
        type=valid_events,
        nargs="+",
        help="""List events that occurred during the benchmark.
Syntax: <event_name>:<start_time>:<duration>
event_name   : the name of an event
start_time   : the starting time of the event (in seconds)
duration     : duration of the event (in seconds)
""",
    )
    parser_graph.add_argument(
        "--format",
        help="Graph file format",
        type=str,
        choices=["svg", "png"],
        default="svg",
    )
    parser_graph.add_argument(
        "--engine",
        help="Select the matplotlib backend engine",
        choices=["pgf", "svg", "agg", "cairo"],
        default="cairo",
    )
    parser_graph.add_argument(
        "--outdir",
        help="Name of the output directory, mandatory with --traces; with --auto-traces, its directory by default",
    )
    parser_graph.add_argument(
        "--same-chassis",
        help="All traces are from the same chassis",
        action="store_true",
    )
    group_group = parser_graph.add_mutually_exclusive_group()
    group_group.add_argument(
        "--same-group",
        help="All traces are from the same group of servers",
        action="store_true",
    )
    group_group.add_argument(
        "--auto-group",
        help="""Render the graphs of a group for each place shared by several traces, found in their location:
in by_group/, one subdirectory per place of the location, from the widest, like by_group/FR/PA99/DH2/Cage_1/A12.
A place holding the same traces as its single subplace is only rendered in the subplace.""",
        action="store_true",
    )
    parser_graph.add_argument(
        "--ashrae",
        default="",
        metavar="CLASSES",
        help="""The ASHRAE classes the rack graphs color the temperatures against, separated by commas, at most one
per family, like --ashrae A1,W40,S40: the air entering the servers (A1 to A4, H1), the facility water of the primary circuit
of the CDUs (W17 to W+), the liquid of their secondary circuit (S30 to S50). They replace the classes the
traces give, from the topology or from the sections of the CDUs.""",
    )
    parser_graph.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose mode",
    )

    parser_graph.add_argument(
        "--ignore-missing-datapoint",
        choices=["zero", "last"],
        default="",
        help="Replace a missing datapoint instead of stopping the rendering. Could be by a zero or the last known value.",
    )
    parser_graph.add_argument(
        "--keep-cache",
        action="store_true",
        help=f"Keep the traces converted in <outdir>/{CACHE_DIRECTORY}, for the next renderings in the same directory",
    )
    parser_graph.add_argument(
        "--jobs",
        "-j",
        help="Number of parallel worker processes for graph generation (default: number of CPUs)",
        type=int,
        default=DEFAULT_JOBS,
    )
    parser_graph.set_defaults(func=render_traces)

    parser_list = subparsers.add_parser(
        "list",
        help="list monitoring metrics from a trace file, or the contexts of the traces of a directory",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    list_group = parser_list.add_mutually_exclusive_group(required=True)
    list_group.add_argument(
        "--trace",
        type=str,
        metavar="TRACE_FILENAME",
        help="""List power metrics of a trace file: a results.json, or a hwbench-<serial>-<timestamp>.tar.xz archive.""",
    )
    list_group.add_argument(
        "--contexts",
        metavar="DIRECTORY",
        help="""List the contexts of the traces found in a directory, with their traces.
Example: hwgraph list --contexts runs
  auto-traces: looking for the traces in runs
  auto-traces: reading the 4 files found
  auto-traces: 4/4 files read
  Contexts found in runs:
  bios-v1: 1 trace
    SRV01  runs/hwbench-out-20261022110000/results.json
  bios-v2: 2 traces
    SRV01  runs/hwbench-SRV01-20261022120000.tar.xz
    SRV02  runs/other/hwbench-out-20261022121000/results.json
  1 trace without context
""",
    )
    parser_list.set_defaults(func=list_metrics_in_trace)

    args = parser.parse_args(args=None if len(sys.argv) > 1 else ["--help"])
    if args.func is render_traces and args.auto_traces:
        args.auto_traces = find_auto_traces(args.auto_traces, args.jobs)
    # The traces found by --auto-traces are rendered next to them by default
    if args.func is render_traces and not args.outdir:
        if not args.auto_traces:
            parser_graph.error("the following arguments are required with --traces: --outdir")
        args.outdir = str(args.auto_traces[0].directory)

    if args.func is render_traces:
        # The classes of each family, replacing the ones of the traces, separated by commas as in the
        # section of a CDU
        args.ashrae, problems = ashrae.parse([name.strip() for name in args.ashrae.split(",") if name.strip()])
        if problems:
            parser_graph.error(f"--ashrae: {'; '.join(problems)}")

    # Call the appropriate sub command
    args.func(args)


if __name__ == "__main__":
    main()
