#!/bin/bash
mkdir -p "/tmp/os28-test/my dir"
printf 'def a():\n    pass\n' > "/tmp/os28-test/my dir/a b.py"
printf "def z(): pass\nit's here\n-x test(\n" > /tmp/os28-test/z.py
echo "Test dosyaları hazır."
