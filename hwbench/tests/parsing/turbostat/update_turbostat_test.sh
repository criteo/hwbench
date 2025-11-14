#!/bin/bash
# Script to capture real turbostat output and update the test file

echo "Capturing turbostat output..."
echo "This requires root privileges."

# Run turbostat and capture output to a temporary file
tmpfile=$(mktemp)
sudo turbostat --quiet --cpu core --debug --num_iterations 1 > "$tmpfile" 2>&1

if [ $? -ne 0 ]; then
    echo "Error running turbostat. Make sure you have root privileges."
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
with open('hwbench/tests/parsing/turbostat/run', 'w') as f:
    f.write(python_list + "\n")

print(f"Successfully updated hwbench/tests/parsing/turbostat/run with {len(lines)} lines")
print("\nFirst few lines:")
for line in lines[:3]:
    print(f"  {line}")
EOF

# Clean up
rm -f "$tmpfile"

echo ""
echo "Done! You can now run the tests to verify:"
echo "  uv run pytest hwbench/bench/test_benchmarks.py -v"
