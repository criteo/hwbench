# AGENTS.md: documentation

This file holds the rules of the documentation pages; the rules of the whole repository are in the top-level `AGENTS.md`.

## Style

- English. The documentation is **generic**: say "the target machine", never "that machine" or "the machine"; the only named machine is the example CPU of `cpu-selection.md` (AMD EPYC 8534P, 64 cores, 8 NUMA domains, 4 quadrants, NPS4 with LLC as NUMA).
- Every statement is checked against the code: exact keyword values, exact error messages, exact output formats (e.g. the benchmark start line). Describe the real behavior, even when it is a bug to fix later.
- Page layout: title `# Name: subtitle` (e.g. `# fio: storage benchmarking`), a short intro, a TOC of the `#` sections, a `Related pages:` line, then the sections, ending with `# Implementation notes` (files, classes, methods) when useful.
- Tables:
  - the values of an option: `| Value | Effect |`;
  - keys: `| Key | Value | Effect |`.
- Callouts:
  ```
  > ℹ️ **Info**
  >
  > text
  ```
  and `> 💡 **Good practice**` with the same shape.
- Commands are written `uv run hwbench …`; job file snippets use an ```` ```ini ```` fence.
- Headings of keywords are lowercase, as the keyword (`### outlet`), so the anchors match; check every `#anchor` link after renaming a heading.
- `configuration.md` is the unique reference of the job file keywords: the other pages link to it rather than repeating it.
- The images of the hwgraph pages (`documentation/img/hwgraph-*.png`) are generated, never edited by hand: they come from the reference dataset `documentation/example/traces/` through `make doc_images` (`documentation/example/render.sh`). Run it, and look at the images, whenever you change a `hwgraph*.md` page (a caption, a command, a graph name), the dataset, `render.sh`, or the rendering code of `graph/`; a graph that is no longer produced makes `render.sh` fail, which is the signal to update the page. Every image of `render.sh` must be used by a page, and every command shown with `hwgraph graph` must use the files of the dataset.
- Topology vocabulary: NPS sets how the memory controllers (DDR) are associated to the cores, which gives the **quadrants**; LLC as NUMA exposes each L3 cache as a **NUMA domain**. What `numa<x>` covers therefore depends on the BIOS settings and cannot be known in advance by a job file.
