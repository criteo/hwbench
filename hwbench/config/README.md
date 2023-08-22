# Usage
The configuration file is a typical init file with sections:
 - global : defines items for all others sections
 - <job>  : defines a new test with "job" as name
            - items defined in global are merged into it
            - if a global item is redefined, the value is overrided

config/config.txt file defines the syntax and logic associated to each
keyword but here is the main principles:

Each job selects:
   - 'engine': implement the logic of a benchmark tool, i.e stress-ng
   - 'engine_module': one specific logic of an engine, i.e cpu, memory
   - 'engine_module_parameter': one mode of the engine_module, i.e int8
   - 'hosting_cpu_cores': defines the list of logical cpu to receive a stress test
   - 'stressor_range': defines the number of stressors to run on each hosting_cpu_cores

stressors & hosting_cpu_cores has an associated _scaling parameter
defining how cpu and stressors are associated at each interation.

The current implementation only has 'one by one' approach like :

	[job_all_cores_once]
	....
	hosting_cpu_cores=0-63
	stressor_range=1

	[job_all_cores_twice]
	....
	hosting_cpu_cores=0-63
	stressor_range=1-2

job_all_cores_once will test all cores, 1 by 1 with a single cpu load for a total of 64 runs.
job_all_cores_twice will test all cores with two tests: 1 cpu load, 2 cpu loads for a total of 128 runs.
