#!/bin/bash
# Script to capture real turbostat output as a test file of the parsing
# Usage: update_turbostat_test.sh [name]
# The file is hwbench/tests/parsing/turbostat/<name>, by default named after the
# CPU model (e.g. intel_core_ultra_7_165u): every file of the directory is parsed
# by hwbench/environment/test_turbostat.py. The "run" file is also the turbostat
# output of the benchmarks tests: refresh it with "update_turbostat_test.sh run".

model=$(grep -m1 "^model name" /proc/cpuinfo | cut -d: -f2 | sed -e 's/([^)]*)//g' -e 's/ CPU\b//' -e 's/@.*//' -e 's/Processor//')
name=${1:-$(echo "$model" | tr '[:upper:]' '[:lower:]' | sed -e 's/[^a-z0-9]\+/_/g' -e 's/^_//' -e 's/_$//')}
testfile="hwbench/tests/parsing/turbostat/$name"

echo "Capturing turbostat output..."
# turbostat needs root: use sudo only when not already root
sudo=""
if [ "$EUID" -ne 0 ]; then
    echo "turbostat requires root privileges, running it with sudo."
    sudo="sudo"
fi

# Run turbostat and capture output to a temporary file
tmpfile=$(mktemp)
$sudo env LC_ALL=C turbostat --quiet --cpu core --debug --num_iterations 1 > "$tmpfile" 2>&1

if [ $? -ne 0 ]; then
    echo "Error running turbostat:"
    cat "$tmpfile"
    rm -f "$tmpfile"
    exit 1
fi

echo "Successfully captured turbostat output"
echo ""
echo "Converting to Python list format..."

# Create Python list format using the temp file
python3 << EOF
import sys

# Read the turbostat output from temp file
with open('$tmpfile', 'r') as f:
    lines = f.read().strip().split('\n')

# Filter out empty lines
lines = [line for line in lines if line.strip()]

# Create Python list representation
python_list = "[\n"
for i, line in enumerate(lines):
    # Escape any special characters and add proper formatting
    escaped_line = line.replace('\\\\', '\\\\\\\\').replace('"', '\\\\"')
    python_list += f'                "{escaped_line}"'
    if i < len(lines) - 1:
        python_list += ","
    python_list += "\n"
python_list += "            ]"

# Write to test file
with open('$testfile', 'w') as f:
    f.write(python_list + "\n")

print(f"Successfully updated $testfile with {len(lines)} lines")
print("\nFirst few lines:")
for line in lines[:3]:
    print(f"  {line}")
EOF

# Clean up
rm -f "$tmpfile"

echo ""
echo "Done! You can now run the tests to verify:"
echo "  uv run pytest hwbench/environment/test_turbostat.py hwbench/bench -v"
