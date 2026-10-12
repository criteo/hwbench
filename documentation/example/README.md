# Reference dataset of the hwgraph documentation

The graphs of the hwgraph pages are rendered from the traces of this
directory, so that every image can be reproduced:

```bash
make doc_images
```

The script runs `uv run hwgraph` on the traces, and copies the graphs used by the
documentation to `documentation/img/`. Run it from the root of the repository, and
review the images before committing them.

| Trace | Machine | Content |
|---|---|---|
| `traces/baseline.json`, `traces/hpc.json` | the same server, HPE ProLiant DL365 Gen11, 2x AMD EPYC 9845 160-Core (320 physical cores, 640 threads), run twice with a different configuration | the `cpu` job (`float128`) and the `memrate` job, 6 scaling steps each from 32 to 640 workers, monitored with `BMC.Server` |
| `traces/cdu_reboot.json` | a third server, HPE ProLiant DL365 Gen11, 2x AMD EPYC 9845 160-Core | a single `full_cpu_load` benchmark of 600 seconds (`stressng cpu matrixprod`, 320 workers) during which the cooling distribution unit (CDU) was rebooted for 100 seconds, to illustrate `--events` |
| `traces/cdu_reboot_2.json`, `traces/cdu_reboot_3.json`, `traces/cdu_reboot_4.json` | three other servers of the same kind, which ran the same benchmark at the same time as `cdu_reboot.json` | with `cdu_reboot.json`, a group of four servers, to illustrate `--same-group` |
| `traces/numa.json` | another server, HPE ProLiant DL385 Gen11, 2x AMD EPYC 9124 16-Core (32 physical cores, 64 threads, 8 NUMA domains) | the `cpu` job (`int128`), 8 scaling steps from 2 to 62 workers, with the NUMA topology |

The traces are real results of hwbench, reduced and anonymized:

- the benchmarks were thinned to a few evenly spread scaling steps, to keep the files small;
- the serial numbers, the host name, the BMC address and the root UUID were replaced, the kernel
  release was simplified, and the
  SMART and udev data of the block devices (which contain serial numbers) were emptied;
- nothing else was changed: the performance and the monitoring metrics are the measured ones, and
  the embedded job file is the original one, which is why it still uses older keywords.

The traces were recorded before some features of hwgraph, so some graphs cannot be illustrated:
the NUMA comparison between two traces needs two traces with the topology, the
chassis graphs need several servers of a same chassis, and
no trace has a PDU.
