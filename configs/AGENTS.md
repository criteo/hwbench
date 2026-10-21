# AGENTS.md: sample configs

This file holds the rules of the sample job configs; the rules of the whole repository are in the top-level `AGENTS.md`.

## Rules

- The file starts with `# Intention: <what the file measures>`.
- Each job has `# engine <name>: see documentation/<engine>.md#<section>` above `engine=`.
- A contextualized comment above each `selected_cpus`, `*_scaling` and `stressor_*` line says what it does in this job, with a link to the exact section: `# <what it does here>: see documentation/<page>.md#<section>`.
- Do not write directives that only repeat their default value, except `selected_*` and `*_scaling` in a GPU job file: they say what the job loads.
- The name says what the file does (`curve-cpu.conf`, `curve-numa.conf`).
